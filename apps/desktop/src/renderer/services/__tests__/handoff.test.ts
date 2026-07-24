import { buildReviewRows, buildSelections } from "@/lib/handoff-review";
import { BASE_URL, api } from "@/services/api";
import { performWorkspaceOp } from "@/services/workspaceOps";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  applyHandoffJob,
  dispatchHandoffJob,
  getHandoffDiff,
  readLocalShas,
} from "../handoff";

vi.mock("@/services/workspaceOps", () => ({
  performWorkspaceOp: vi.fn(() => Promise.resolve()),
}));

vi.mock("@/services/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/services/api")>();
  return {
    ...actual,
    api: { get: vi.fn(), post: vi.fn() },
  };
});

const performOp = vi.mocked(performWorkspaceOp);
const apiGet = vi.mocked(api.get);

/** Build a one-shot SSE Response whose body yields the given events then closes. */
function sseResponse(events: unknown[]): Response {
  const body = events.map((e) => `data: ${JSON.stringify(e)}\n\n`).join("");
  const stream = new ReadableStream({
    start(controller) {
      controller.enqueue(new TextEncoder().encode(body));
      controller.close();
    },
  });
  return new Response(stream, {
    status: 200,
    headers: { "Content-Type": "text/event-stream" },
  });
}

const postedBody = (fetchMock: ReturnType<typeof vi.fn>, call = 0) =>
  JSON.parse((fetchMock.mock.calls[call][1] as RequestInit).body as string);

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  performOp.mockReset();
  performOp.mockResolvedValue(undefined);
  apiGet.mockReset();
  fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("dispatchHandoffJob", () => {
  it("POSTs {task}, fulfils workspace_op_required, returns job ids from SSE", async () => {
    const opPayload = {
      request_id: "op-1",
      conversation_id: "c1",
      root_id: "root-1",
      op: "archive",
      args: {},
    };
    fetchMock.mockResolvedValue(
      sseResponse([
        { type: "workspace_op_required", payload: opPayload },
        {
          type: "handoff_job_started",
          payload: {
            job_id: "job-1",
            conversation_id: "c1",
            job_conversation_id: "job-conv-1",
          },
        },
      ]),
    );

    const started = await dispatchHandoffJob("c1", "调研竞品");

    expect(fetchMock.mock.calls[0][0]).toBe(
      `${BASE_URL}/v1/conversations/c1/workspace/handoff/dispatch`,
    );
    expect(postedBody(fetchMock)).toEqual({ task: "调研竞品" });
    expect(performOp).toHaveBeenCalledWith(opPayload, "c1");
    expect(started).toEqual({
      jobId: "job-1",
      jobConversationId: "job-conv-1",
    });
  });
});

describe("getHandoffDiff", () => {
  it("maps snake_case wire rows into camelCase HandoffDiff", async () => {
    apiGet.mockResolvedValueOnce({
      job_id: "job-1",
      data: [
        {
          path: "a.txt",
          change_type: "modified",
          base_sha: "b1",
          result_sha: "r1",
          is_binary: false,
          content: "hi",
          size_bytes: 2,
        },
      ],
      total: 1,
      added: 0,
      modified: 1,
      deleted: 0,
    });

    const diff = await getHandoffDiff("c1", "job-1");

    expect(apiGet).toHaveBeenCalledWith(
      "/v1/conversations/c1/handoff/jobs/job-1/diff",
    );
    expect(diff).toEqual({
      jobId: "job-1",
      changes: [
        {
          path: "a.txt",
          changeType: "modified",
          baseSha: "b1",
          resultSha: "r1",
          isBinary: false,
          content: "hi",
          sizeBytes: 2,
        },
      ],
      total: 1,
      added: 0,
      modified: 1,
      deleted: 0,
    });
  });
});

describe("applyHandoffJob", () => {
  it("POSTs snake_case selections and maps handoff_apply_done", async () => {
    fetchMock.mockResolvedValue(
      sseResponse([
        {
          type: "handoff_apply_done",
          payload: {
            job_id: "job-1",
            conversation_id: "c1",
            results: [
              {
                path: "a.txt",
                status: "applied",
                change_type: "modified",
                detail: "",
              },
              {
                path: "b.txt",
                status: "conflict",
                change_type: "modified",
                detail: "local drifted",
              },
            ],
            applied: 1,
            skipped: 0,
            conflicts: 1,
            errors: 0,
          },
        },
      ]),
    );

    const summary = await applyHandoffJob("c1", "job-1", [
      {
        path: "a.txt",
        decision: "cloud",
        localSha: "b1",
        force: false,
      },
      {
        path: "b.txt",
        decision: "cloud",
        localSha: "x9",
        force: true,
      },
    ]);

    expect(fetchMock.mock.calls[0][0]).toBe(
      `${BASE_URL}/v1/conversations/c1/handoff/jobs/job-1/apply`,
    );
    expect(postedBody(fetchMock)).toEqual({
      selections: [
        {
          path: "a.txt",
          decision: "cloud",
          local_sha: "b1",
          force: false,
        },
        {
          path: "b.txt",
          decision: "cloud",
          local_sha: "x9",
          force: true,
        },
      ],
    });
    expect(summary).toEqual({
      jobId: "job-1",
      results: [
        {
          path: "a.txt",
          status: "applied",
          changeType: "modified",
          detail: "",
        },
        {
          path: "b.txt",
          status: "conflict",
          changeType: "modified",
          detail: "local drifted",
        },
      ],
      applied: 1,
      skipped: 0,
      conflicts: 1,
      errors: 0,
    });
  });
});

describe("readLocalShas (假 fsApi)", () => {
  it("hashes readable files and nulls missing / non-desktop", async () => {
    const workspaceOp = vi.fn(
      async (_root: string, _op: string, args: { path: string }) => {
        if (args.path === "ok.txt") {
          return { ok: true, value: btoa("hello") };
        }
        return { ok: false, error: { kind: "PathNotFound", detail: "" } };
      },
    );
    vi.stubGlobal("window", { fsApi: { workspaceOp } });

    const map = await readLocalShas("root-1", ["ok.txt", "gone.txt"]);

    expect(workspaceOp).toHaveBeenCalledWith("root-1", "read_bytes", {
      path: "ok.txt",
    });
    expect(map.get("ok.txt")).toMatch(/^[0-9a-f]{64}$/);
    expect(map.get("gone.txt")).toBeNull();

    vi.stubGlobal("window", {});
    const empty = await readLocalShas("root-1", ["x.txt"]);
    expect(empty.get("x.txt")).toBeNull();
  });
});

describe("应用前重哈希冲突门 (review → fresh shas → apply body)", () => {
  /**
   * Mirrors BackgroundTaskReview.onApply: re-read local shas right before
   * apply so a file edited since the review opened becomes a conflict (force
   * when the user still picks cloud) rather than a silent clobber.
   */
  it("fresh local drift flips clean→conflict and sets force on cloud pick", async () => {
    const change = {
      path: "a.txt",
      changeType: "modified" as const,
      baseSha: "base",
      resultSha: "result",
      isBinary: false,
      content: "cloud",
      sizeBytes: 5,
    };
    // Review-time: local still at base → clean, default cloud.
    const reviewRows = buildReviewRows([change], new Map([["a.txt", "base"]]));
    expect(reviewRows[0].verdict).toBe("clean");
    expect(reviewRows[0].decision).toBe("cloud");

    // Apply-time rehash: disk drifted → conflict; user keeps cloud → force.
    const freshShas = new Map<string, string | null>([["a.txt", "drifted"]]);
    const applyRows = buildReviewRows([change], freshShas);
    expect(applyRows[0].verdict).toBe("conflict");
    applyRows[0].decision = "cloud";
    const selections = buildSelections(applyRows);
    expect(selections).toEqual([
      {
        path: "a.txt",
        decision: "cloud",
        localSha: "drifted",
        force: true,
      },
    ]);

    fetchMock.mockResolvedValue(
      sseResponse([
        {
          type: "handoff_apply_done",
          payload: {
            job_id: "job-1",
            conversation_id: "c1",
            results: [
              {
                path: "a.txt",
                status: "applied",
                change_type: "modified",
                detail: "forced",
              },
            ],
            applied: 1,
            skipped: 0,
            conflicts: 0,
            errors: 0,
          },
        },
      ]),
    );

    await applyHandoffJob("c1", "job-1", selections);
    expect(postedBody(fetchMock).selections[0]).toEqual({
      path: "a.txt",
      decision: "cloud",
      local_sha: "drifted",
      force: true,
    });
  });
});
