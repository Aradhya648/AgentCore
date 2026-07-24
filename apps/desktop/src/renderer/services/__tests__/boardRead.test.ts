import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// Drive the回填 through the REAL api.post by stubbing global fetch (not by mocking the api
// module) — same posture as workspaceOps.test.ts. The reader is injected via the module
// registry (registerBoardReader), so no window/IPC stubbing is needed.
import { BASE_URL } from "@/services/api";
import {
  type BoardRasterResult,
  performBoardRead,
  registerBoardReader,
} from "@/services/boardRead";
import type { BoardReadRequiredPayload } from "@/types/events";

const BOARD = "board-1";

const payload = (
  over: Partial<BoardReadRequiredPayload> = {},
): BoardReadRequiredPayload => ({
  request_id: "r1",
  conversation_id: "c1",
  board_id: BOARD,
  ids: ["el-1"],
  ...over,
});

const READ_URL = `${BASE_URL}/v1/conversations/c1/interactions/r1`;

// `headers.get` is read by api.request's captureCsrf before the status check, so the mock
// Response must carry one (else a TypeError masks the real ApiError path).
const noHeaders = { get: () => null };
const okResponse = () => ({
  ok: true,
  status: 200,
  headers: noHeaders,
  json: async () => ({}),
});
const errResponse = (status: number, body: string) => ({
  ok: false,
  status,
  headers: noHeaders,
  text: async () => body,
});

const postedBody = (fetchMock: ReturnType<typeof vi.fn>, call = 0) =>
  JSON.parse((fetchMock.mock.calls[call][1] as RequestInit).body as string);

let fetchMock: ReturnType<typeof vi.fn>;
const cleanups: Array<() => void> = [];

beforeEach(() => {
  fetchMock = vi.fn().mockResolvedValue(okResponse());
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => {
  vi.unstubAllGlobals();
  for (const off of cleanups.splice(0)) off();
});

const register = (
  reader: (ids: string[]) => Promise<BoardRasterResult>,
  boardId = BOARD,
) => {
  cleanups.push(registerBoardReader(boardId, reader));
};

describe("performBoardRead (白板读图回填)", () => {
  it("rasterizes the ids and posts the ok result (client_tool kind)", async () => {
    const reader = vi.fn().mockResolvedValue({ pngBase64: "abc", w: 10, h: 8 });
    register(reader);

    await performBoardRead(payload(), "c1");

    expect(reader).toHaveBeenCalledWith(["el-1"]);
    expect(fetchMock.mock.calls[0][0]).toBe(READ_URL);
    expect(postedBody(fetchMock)).toEqual({
      kind: "client_tool",
      ok: true,
      value: { pngBase64: "abc", w: 10, h: 8 },
    });
  });

  it("answers a clean error when the board's canvas is not open (no reader)", async () => {
    await performBoardRead(payload({ board_id: "not-open" }), "c1");

    const body = postedBody(fetchMock) as {
      ok: boolean;
      error: { kind: string; detail: string };
    };
    expect(body.ok).toBe(false);
    expect(body.error.kind).toBe("BoardReadError");
    expect(body.error.detail).toContain("未在前台打开");
  });

  it("maps a thrown rasterize error to a clean error envelope (never unanswered)", async () => {
    register(vi.fn().mockRejectedValue(new Error("没有可读取的元素")));

    await performBoardRead(payload(), "c1");

    const body = postedBody(fetchMock) as {
      ok: boolean;
      error: { kind: string; detail: string };
    };
    expect(body.ok).toBe(false);
    expect(body.error.detail).toContain("没有可读取的元素");
  });

  it("swallows a stale 404 from the resolve endpoint", async () => {
    register(vi.fn().mockResolvedValue({ pngBase64: "x", w: 1, h: 1 }));
    fetchMock.mockResolvedValue(errResponse(404, "gone"));

    await expect(performBoardRead(payload(), "c1")).resolves.toBeUndefined();
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});
