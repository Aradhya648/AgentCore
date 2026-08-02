import { mkdirSync, rmSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { afterAll, describe, expect, it, vi } from "vitest";

// A throwaway data dir the mocked `app.getPath("userData")` points at; frame files
// live under `<dir>/sidecar/paused`, mirroring what the Python LocalPausedTurnStore
// writes. Computed in a hoisted block so the electron mock factory can close over it.
const h = vi.hoisted(() => {
  const base = process.env.TEMP || process.env.TMPDIR || "/tmp";
  return {
    dir: `${base}/sidecar-paused-test-${Math.random().toString(36).slice(2)}`,
  };
});

vi.mock("electron", () => ({
  app: { on: vi.fn(), getAppPath: () => "", getPath: () => h.dir },
  ipcMain: { handle: vi.fn() },
  BrowserWindow: { getAllWindows: () => [] },
}));

vi.mock("../log-service", () => ({
  logDesktop: vi.fn(),
}));

import { SidecarManager } from "../sidecar-service";

const pausedDir = join(h.dir, "sidecar", "paused");

function writeFrame(name: string, record: Record<string, unknown>): void {
  mkdirSync(pausedDir, { recursive: true });
  writeFileSync(join(pausedDir, name), JSON.stringify(record), "utf-8");
}

function summary(messageId: string) {
  return {
    message_id: messageId,
    kind: "ask_user",
    checkpoint_id: `cp-${messageId}`,
    user_message: `q-${messageId}`,
    steps: [],
    pending: [],
    question: "要继续吗？",
    context: "",
    assumptions: [],
    questions: [],
  };
}

function frameRecord(
  messageId: string,
  conversationId: string,
  createdAt: number,
) {
  return {
    message_id: messageId,
    conversation_id: conversationId,
    created_at: createdAt,
    summary: summary(messageId),
    frame: {},
    journal: [],
  };
}

describe("SidecarManager.recovery paused[] (local frame file read, no spawn)", () => {
  afterAll(() => rmSync(h.dir, { recursive: true, force: true }));

  it("lists a conversation's frames oldest-first, scoped, tolerating junk", async () => {
    // Two c1 frames (out of order on disk), one other-conversation frame, one torn.
    writeFrame("newer.json", frameRecord("m_new", "c1", 200));
    writeFrame("older.json", frameRecord("m_old", "c1", 100));
    writeFrame("other.json", frameRecord("m_x", "c2", 150));
    writeFrame("torn.json", { not: "a frame" });
    mkdirSync(pausedDir, { recursive: true });
    writeFileSync(join(pausedDir, "garbage.json"), "}{ not json", "utf-8");

    // A spawn here would be a bug — listing is a pure file read via recovery.
    const manager = new SidecarManager(() => {
      throw new Error("recovery must not spawn the sidecar");
    });
    const data = await manager.recovery({ conversationId: "c1" });

    expect(data.paused.map((d) => d.message_id)).toEqual(["m_old", "m_new"]); // oldest-first
    expect(data.paused.every((d) => d.kind === "ask_user")).toBe(true);
    expect(data.paused[0].question).toBe("要继续吗？");
    expect(data.liveRunning).toBe(false);
    expect(data.unsynced).toEqual([]);
  });

  it("returns paused=[] when no frames directory exists yet", async () => {
    const manager = new SidecarManager(() => {
      throw new Error("must not spawn");
    });
    const data = await manager.recovery({
      conversationId: "never-paused",
    });
    expect(data.paused).toEqual([]);
  });
});
