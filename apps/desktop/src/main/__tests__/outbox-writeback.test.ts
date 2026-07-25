/**
 * Outbox writebacker: at-least-once drain + idempotent delivery.
 */
import {
  existsSync,
  mkdirSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { join } from "node:path";
import { afterAll, beforeEach, describe, expect, it, vi } from "vitest";

const h = vi.hoisted(() => {
  const base = process.env.TEMP || process.env.TMPDIR || "/tmp";
  return {
    dir: `${base}/outbox-wb-test-${Math.random().toString(36).slice(2)}`,
    bearerPostJson: vi.fn(),
  };
});

vi.mock("electron", () => ({
  app: {
    getPath: () => h.dir,
    on: vi.fn(),
  },
  ipcMain: { handle: vi.fn() },
  BrowserWindow: { getAllWindows: () => [] },
}));

vi.mock("../auth-client", () => ({
  bearerPostJson: h.bearerPostJson,
  refreshAccessToken: vi.fn(async () => "renewed" as const),
}));

import {
  computeBackoffDelayMs,
  deadLetterDir,
  drainOutbox,
  flushTurn,
  isPermanentHttpFailure,
  outboxDir,
  shouldDeleteOutboxAfterAck,
} from "../outbox-writeback";

const dir = () => outboxDir();

function writeReady(
  userMessageId: string,
  overrides: Record<string, unknown> = {},
) {
  mkdirSync(dir(), { recursive: true });
  writeFileSync(
    join(dir(), `${userMessageId}.json`),
    JSON.stringify({
      schema_version: 1,
      user_message_id: userMessageId,
      conversation_id: "c1",
      message_id: "m1",
      trace_id: "a".repeat(32),
      user_message: "hello",
      content: "world",
      phase: "ready",
      input_tokens: 1,
      output_tokens: 2,
      reasoning_tokens: 0,
      cache_hit_tokens: 0,
      cache_miss_tokens: 0,
      rounds: 1,
      finish_reason: "stop",
      ...overrides,
    }),
    "utf-8",
  );
}

function readRecord(userMessageId: string): Record<string, unknown> {
  return JSON.parse(
    readFileSync(join(dir(), `${userMessageId}.json`), "utf-8"),
  ) as Record<string, unknown>;
}

describe("drainOutbox", () => {
  afterAll(() => rmSync(h.dir, { recursive: true, force: true }));

  beforeEach(() => {
    rmSync(dir(), { recursive: true, force: true });
    rmSync(deadLetterDir(), { recursive: true, force: true });
    h.bearerPostJson.mockReset();
  });

  it("POSTs ready records and deletes on ack (at-least-once)", async () => {
    writeReady("u1");
    h.bearerPostJson.mockResolvedValueOnce({
      ok: true,
      status: 200,
      body: {
        user_message_id: "u1",
        assistant_message_id: "m1",
        title: "T",
      },
    });

    const status = await drainOutbox();
    expect(h.bearerPostJson).toHaveBeenCalledOnce();
    const [path, body] = h.bearerPostJson.mock.calls[0] as [
      string,
      { user_message_id: string; content: string },
    ];
    expect(path).toBe("/v1/conversations/c1/local-turns");
    expect(body.user_message_id).toBe("u1");
    expect(body.content).toBe("world");
    expect(status.pending).toEqual([]);
  });

  it("leaves the file when POST fails (retry later) and stamps backoff", async () => {
    writeReady("u2");
    h.bearerPostJson.mockResolvedValueOnce({
      ok: false,
      status: 503,
      body: { error: "busy" },
    });
    const status = await drainOutbox();
    expect(status.pending).toHaveLength(1);
    expect(status.pending[0]?.userMessageId).toBe("u2");
    const onDisk = readRecord("u2");
    expect(onDisk.retry_count).toBe(1);
    expect(typeof onDisk.next_attempt_at).toBe("number");
    expect(onDisk.next_attempt_at as number).toBeGreaterThan(Date.now());
  });

  it("moves permanent 4xx (e.g. 404) to dead-letter and drops from pending", async () => {
    writeReady("u-404");
    h.bearerPostJson.mockResolvedValueOnce({
      ok: false,
      status: 404,
      body: { error: "not_found" },
    });
    const status = await drainOutbox();
    expect(status.pending).toEqual([]);
    expect(existsSync(join(dir(), "u-404.json"))).toBe(false);
    expect(existsSync(join(deadLetterDir(), "u-404.json"))).toBe(true);
  });

  it("skips records still within backoff window", async () => {
    writeReady("u-backoff", {
      retry_count: 2,
      next_attempt_at: Date.now() + 60_000,
    });
    const status = await drainOutbox();
    expect(h.bearerPostJson).not.toHaveBeenCalled();
    expect(status.pending).toHaveLength(1);
    expect(status.pending[0]?.userMessageId).toBe("u-backoff");
  });

  it("retries when next_attempt_at has elapsed", async () => {
    writeReady("u-due", {
      retry_count: 1,
      next_attempt_at: Date.now() - 1_000,
    });
    h.bearerPostJson.mockResolvedValueOnce({
      ok: true,
      status: 200,
      body: {
        user_message_id: "u-due",
        assistant_message_id: "m1",
        title: null,
      },
    });
    const status = await drainOutbox();
    expect(h.bearerPostJson).toHaveBeenCalledOnce();
    expect(status.pending).toEqual([]);
  });

  it("flushTurn bypasses backoff and attempts immediately", async () => {
    writeReady("u-flush", {
      retry_count: 3,
      next_attempt_at: Date.now() + 60_000,
    });
    h.bearerPostJson.mockResolvedValueOnce({
      ok: true,
      status: 200,
      body: {
        user_message_id: "u-flush",
        assistant_message_id: "m1",
        title: null,
      },
    });
    const result = await flushTurn("u-flush");
    expect(result.ok).toBe(true);
    expect(h.bearerPostJson).toHaveBeenCalledOnce();
  });

  it("skips open records during regular drain (no mid-turn salvage)", async () => {
    writeReady("u3", { phase: "open", content: "partial" });
    const status = await drainOutbox();
    expect(h.bearerPostJson).not.toHaveBeenCalled();
    expect(status.pending).toHaveLength(1);
    expect(status.pending[0]?.phase).toBe("open");
  });

  it("includes sorted journal on writeback when runs is missing (crash salvage)", async () => {
    writeReady("u-j", {
      runs: null,
      finish_reason: "cancelled",
      journal: {
        "2": { kind: "run_completed", payload: { id: "r1" }, ts: null },
        "0": { kind: "run_started", payload: { id: "r1" }, ts: "t0" },
      },
    });
    h.bearerPostJson.mockResolvedValueOnce({
      ok: true,
      status: 200,
      body: {
        user_message_id: "u-j",
        assistant_message_id: "m1",
        title: null,
      },
    });

    await drainOutbox();
    expect(h.bearerPostJson).toHaveBeenCalledOnce();
    const body = h.bearerPostJson.mock.calls[0]?.[1] as {
      journal?: unknown[];
      finish_reason?: string;
      runs?: unknown;
    };
    expect(body.runs).toBeNull();
    expect(body.finish_reason).toBe("cancelled");
    expect(body.journal).toEqual([
      { kind: "run_started", payload: { id: "r1" }, ts: "t0" },
      { kind: "run_completed", payload: { id: "r1" }, ts: null },
    ]);
  });

  it("salvageOpen retains settled non-terminal open rows (D2 retain-open)", async () => {
    const { recoverLocalPersistence } = await import("../outbox-writeback");
    writeReady("u-retain", {
      phase: "open",
      content: "partial after kickoff",
      finish_reason: null,
      journal: {
        "0": {
          kind: "team_preview_required",
          payload: { checkpoint_id: "tp1" },
        },
        "1": {
          kind: "team_preview_resolved",
          payload: {
            checkpoint_id: "tp1",
            decision: "continue",
            resume_frame: {
              frame: { kind: "team_preview", checkpoint_id: "tp1" },
            },
          },
        },
      },
    });

    await recoverLocalPersistence();
    expect(h.bearerPostJson).not.toHaveBeenCalled();
    const record = readRecord("u-retain");
    expect(record.phase).toBe("open");
    expect(record.finish_reason).toBeNull();
  });

  it("ready terminal turns with settlement still writeback (retain only for open)", async () => {
    writeReady("u-done", {
      phase: "ready",
      finish_reason: "end_turn",
      journal: {
        "0": {
          kind: "team_preview_resolved",
          payload: {
            checkpoint_id: "tp1",
            decision: "continue",
            resume_frame: { frame: { kind: "team_preview" } },
          },
        },
      },
    });
    h.bearerPostJson.mockResolvedValueOnce({
      ok: true,
      status: 200,
      body: {
        user_message_id: "u-done",
        assistant_message_id: "m1",
        title: null,
      },
    });

    await drainOutbox();
    expect(h.bearerPostJson).toHaveBeenCalledOnce();
    expect(existsSync(join(dir(), "u-done.json"))).toBe(false);
  });

  it("salvageOpen promotes abandoned open rows as cancelled (not error)", async () => {
    const { recoverLocalPersistence } = await import("../outbox-writeback");
    writeReady("u-open", {
      phase: "open",
      content: "partial",
      finish_reason: null,
    });
    h.bearerPostJson.mockResolvedValueOnce({
      ok: true,
      status: 200,
      body: {
        user_message_id: "u-open",
        assistant_message_id: "m1",
        title: null,
      },
    });

    await recoverLocalPersistence();
    expect(h.bearerPostJson).toHaveBeenCalledOnce();
    const body = h.bearerPostJson.mock.calls[0]?.[1] as {
      finish_reason?: string;
    };
    expect(body.finish_reason).toBe("cancelled");
  });

  it("salvageOpen promotes open rows with empty content from captain stream_segments", async () => {
    const { recoverLocalPersistence } = await import("../outbox-writeback");
    writeReady("u-snap", {
      phase: "open",
      content: "",
      reasoning_content: null,
      finish_reason: null,
      stream_segments: {
        "captain:content": { text: "half reply from flush", generation: 0 },
        "captain:reasoning": { text: "mid think", generation: 0 },
      },
    });
    h.bearerPostJson.mockResolvedValueOnce({
      ok: true,
      status: 200,
      body: {
        user_message_id: "u-snap",
        assistant_message_id: "m1",
        title: null,
      },
    });

    await recoverLocalPersistence();
    expect(h.bearerPostJson).toHaveBeenCalledOnce();
    const body = h.bearerPostJson.mock.calls[0]?.[1] as {
      content?: string;
      reasoning_content?: string | null;
      finish_reason?: string;
    };
    expect(body.content).toBe("half reply from flush");
    expect(body.reasoning_content).toBe("mid think");
    expect(body.finish_reason).toBe("cancelled");
  });

  it("regular drain still skips open rows that only have stream_segments", async () => {
    writeReady("u-open-segs", {
      phase: "open",
      content: "",
      stream_segments: {
        "captain:content": {
          text: "should not promote mid-turn",
          generation: 0,
        },
      },
    });
    const status = await drainOutbox();
    expect(h.bearerPostJson).not.toHaveBeenCalled();
    expect(status.pending).toHaveLength(1);
    expect(status.pending[0]?.phase).toBe("open");
  });

  it("ready drain fills captain stream_segments into POST body", async () => {
    writeReady("u-ready-segs", {
      content: "",
      reasoning_content: null,
      stream_segments: {
        "captain:content": { text: "from segments", generation: 0 },
        "captain:reasoning": { text: "think", generation: 0 },
      },
    });
    h.bearerPostJson.mockResolvedValueOnce({
      ok: true,
      status: 200,
      body: {
        user_message_id: "u-ready-segs",
        assistant_message_id: "m1",
        title: null,
        noop: false,
      },
    });
    await drainOutbox();
    expect(h.bearerPostJson).toHaveBeenCalledOnce();
    const body = h.bearerPostJson.mock.calls[0]?.[1] as {
      content?: string;
      reasoning_content?: string | null;
    };
    expect(body.content).toBe("from segments");
    expect(body.reasoning_content).toBe("think");
  });

  it("false ack (null assistant + process) does not delete — dead-letters", async () => {
    writeReady("u-false", {
      content: "",
      runs: { events: [], finish_reason: "end_turn", process: [] },
    });
    h.bearerPostJson.mockResolvedValueOnce({
      ok: true,
      status: 200,
      body: {
        user_message_id: "u-false",
        assistant_message_id: null,
        title: null,
        noop: false,
      },
    });
    const status = await drainOutbox();
    expect(existsSync(join(dir(), "u-false.json"))).toBe(false);
    expect(existsSync(join(deadLetterDir(), "u-false.json"))).toBe(true);
    expect(status.pending).toEqual([]);
  });

  it("explicit noop ack deletes empty true-no-op without process", async () => {
    writeReady("u-noop", { content: "", runs: null, journal: undefined });
    h.bearerPostJson.mockResolvedValueOnce({
      ok: true,
      status: 200,
      body: {
        user_message_id: "u-noop",
        assistant_message_id: null,
        title: null,
        noop: true,
      },
    });
    await drainOutbox();
    expect(existsSync(join(dir(), "u-noop.json"))).toBe(false);
    expect(existsSync(join(deadLetterDir(), "u-noop.json"))).toBe(false);
  });

  it("listUnsyncedSummaries includes dead-letter as phase=dead", async () => {
    const { listUnsyncedSummaries } = await import("../outbox-writeback");
    mkdirSync(deadLetterDir(), { recursive: true });
    writeFileSync(
      join(deadLetterDir(), "u-dead.json"),
      JSON.stringify({
        schema_version: 1,
        user_message_id: "u-dead",
        conversation_id: "c1",
        message_id: "m-dead",
        trace_id: "a".repeat(32),
        user_message: "hello",
        content: "stuck body",
        phase: "ready",
        updated_at: 100,
        finish_reason: "end_turn",
      }),
      "utf-8",
    );
    const unsynced = await listUnsyncedSummaries("c1");
    expect(unsynced).toHaveLength(1);
    expect(unsynced[0]?.user_message_id).toBe("u-dead");
    expect(unsynced[0]?.phase).toBe("dead");
    expect(unsynced[0]?.content).toBe("stuck body");
  });
});

describe("writeback failure classification", () => {
  it("classifies permanent vs transient HTTP statuses", () => {
    expect(isPermanentHttpFailure(404)).toBe(true);
    expect(isPermanentHttpFailure(400)).toBe(true);
    expect(isPermanentHttpFailure(403)).toBe(true);
    expect(isPermanentHttpFailure(422)).toBe(true);
    expect(isPermanentHttpFailure(401)).toBe(false);
    expect(isPermanentHttpFailure(408)).toBe(false);
    expect(isPermanentHttpFailure(429)).toBe(false);
    expect(isPermanentHttpFailure(500)).toBe(false);
    expect(isPermanentHttpFailure(503)).toBe(false);
    expect(isPermanentHttpFailure(0)).toBe(false);
  });

  it("uses 2s base, doubles, caps at 5 min (jitter injectable)", () => {
    const noJitter = () => 0;
    expect(computeBackoffDelayMs(1, noJitter)).toBe(2_000);
    expect(computeBackoffDelayMs(2, noJitter)).toBe(4_000);
    expect(computeBackoffDelayMs(3, noJitter)).toBe(8_000);
    expect(computeBackoffDelayMs(10, noJitter)).toBe(5 * 60_000);
  });

  it("shouldDeleteOutboxAfterAck requires assistant id, noop, or legacy empty", () => {
    const withRuns = {
      user_message_id: "u",
      conversation_id: "c",
      runs: { events: [] },
    };
    const empty = {
      user_message_id: "u",
      conversation_id: "c",
    };
    expect(
      shouldDeleteOutboxAfterAck(
        { assistant_message_id: "m1", noop: false },
        withRuns,
      ),
    ).toBe(true);
    expect(
      shouldDeleteOutboxAfterAck(
        { assistant_message_id: null, noop: true },
        empty,
      ),
    ).toBe(true);
    expect(
      shouldDeleteOutboxAfterAck(
        { assistant_message_id: null, noop: false },
        withRuns,
      ),
    ).toBe(false);
    expect(
      shouldDeleteOutboxAfterAck(
        { assistant_message_id: null, noop: false },
        empty,
      ),
    ).toBe(true);
  });
});
