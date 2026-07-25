/**
 * L3「团队浏览器」M2 接管客户端 (services/browserTakeover.ts) 单测：
 * - REST：start/end/input/list 端点 + body 形；空批不发；wire→narrow 映射。
 * - start 成败靠 body.reason（200）：started|already_active 成功；其余 throw TakeoverStartError。
 * - list 读 `data`（非旧 `takeovers`）。
 * - start 失败语义：turn_running / no_session / already_active → zh 文案（+ 回落；兼容 ApiError.code）。
 * - 坐标换算 toFrameSpace：object-contain 缩放 + 信箱留白 + 钳制 + 非法尺寸兜底。
 * - 输入批处理 createInputBatcher：定时 flush、move 合并、commit 立即 flush、stop 收口、发失败吞掉。
 * - 修饰键 modifiersOf / 时长成文 formatTakeoverDuration。
 * mock `@/services/api` 的 api 方法（保留真 ApiError 以驱动 instanceof 分支）。
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/services/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/services/api")>();
  return {
    ...actual,
    api: {
      get: vi.fn(),
      post: vi.fn(),
      put: vi.fn(),
      patch: vi.fn(),
      delete: vi.fn(),
    },
  };
});

import { ApiError, api } from "@/services/api";
import {
  type BrowserInputEvent,
  TakeoverStartError,
  createInputBatcher,
  endBrowserTakeover,
  formatTakeoverDuration,
  listBrowserTakeovers,
  modifiersOf,
  sendBrowserInput,
  startBrowserTakeover,
  takeoverStartErrorMessage,
  toFrameSpace,
} from "../browserTakeover";

const mockPost = vi.mocked(api.post);
const mockGet = vi.mocked(api.get);

beforeEach(() => {
  mockPost.mockReset().mockResolvedValue({
    active: true,
    reason: "started",
  });
  mockGet.mockReset();
});

afterEach(() => {
  vi.useRealTimers();
});

describe("browserTakeover · REST", () => {
  it("starts a takeover and treats reason=started as success", async () => {
    const state = await startBrowserTakeover("conv-42");
    expect(mockPost).toHaveBeenCalledWith(
      "/v1/conversations/conv-42/browser/takeover",
      { action: "start" },
    );
    expect(state).toEqual({ active: true, reason: "started" });
  });

  it("treats reason=already_active as success (idempotent start)", async () => {
    mockPost.mockResolvedValue({
      active: true,
      reason: "already_active",
      started_at: "2026-07-25T00:00:00Z",
    });
    const state = await startBrowserTakeover("conv-42");
    expect(state.reason).toBe("already_active");
    expect(state.active).toBe(true);
  });

  it("throws TakeoverStartError when reason is a start failure", async () => {
    mockPost.mockResolvedValue({ active: false, reason: "turn_running" });
    await expect(startBrowserTakeover("c1")).rejects.toEqual(
      expect.objectContaining({
        name: "TakeoverStartError",
        reason: "turn_running",
      }),
    );
  });

  it("throws on no_session / not_active reasons", async () => {
    mockPost.mockResolvedValue({ active: false, reason: "no_session" });
    await expect(startBrowserTakeover("c1")).rejects.toBeInstanceOf(
      TakeoverStartError,
    );
    mockPost.mockResolvedValue({ active: false, reason: "not_active" });
    await expect(startBrowserTakeover("c1")).rejects.toMatchObject({
      reason: "not_active",
    });
  });

  it("ends a takeover with {action:'end'} (idempotent)", async () => {
    await endBrowserTakeover("conv-42");
    expect(mockPost).toHaveBeenCalledWith(
      "/v1/conversations/conv-42/browser/takeover",
      { action: "end" },
    );
  });

  it("posts input events in a batch", async () => {
    const events: BrowserInputEvent[] = [
      { kind: "mouse", type: "down", x: 10, y: 20, button: 0, click_count: 1 },
      { kind: "key", type: "down", key: "a", code: "KeyA" },
    ];
    await sendBrowserInput("c1", events);
    expect(mockPost).toHaveBeenCalledWith(
      "/v1/conversations/c1/browser/input",
      { events },
    );
  });

  it("does not POST an empty input batch", async () => {
    await sendBrowserInput("c1", []);
    expect(mockPost).not.toHaveBeenCalled();
  });

  it("lists takeovers from `data`, mapping snake_case wire → narrow records", async () => {
    mockGet.mockResolvedValue({
      data: [
        {
          id: "t1",
          started_at: "2026-07-20T10:00:00Z",
          ended_at: "2026-07-20T10:02:00Z",
        },
        { id: "t2", started_at: "2026-07-20T11:00:00Z" },
      ],
    });
    const out = await listBrowserTakeovers("c1");
    expect(mockGet).toHaveBeenCalledWith(
      "/v1/conversations/c1/browser/takeovers",
    );
    expect(out).toEqual([
      {
        id: "t1",
        startedAt: "2026-07-20T10:00:00Z",
        endedAt: "2026-07-20T10:02:00Z",
      },
      { id: "t2", startedAt: "2026-07-20T11:00:00Z", endedAt: null },
    ]);
  });

  it("encodes the conversation id in the path", async () => {
    await startBrowserTakeover("a/b?c");
    expect(mockPost).toHaveBeenCalledWith(
      "/v1/conversations/a%2Fb%3Fc/browser/takeover",
      { action: "start" },
    );
  });
});

describe("takeoverStartErrorMessage", () => {
  const withCode = (code: string) =>
    new ApiError(409, JSON.stringify({ error: { code } }));

  it("maps TakeoverStartError reason strings", () => {
    expect(
      takeoverStartErrorMessage(new TakeoverStartError("turn_running")),
    ).toContain("回合");
    expect(
      takeoverStartErrorMessage(new TakeoverStartError("no_session")),
    ).toContain("没有进行中");
    expect(takeoverStartErrorMessage("not_active")).toContain(
      "没有进行中的接管",
    );
  });

  it("maps the pinned start-failure codes (legacy ApiError.path)", () => {
    expect(takeoverStartErrorMessage(withCode("turn_running"))).toContain(
      "回合",
    );
    expect(takeoverStartErrorMessage(withCode("no_session"))).toContain(
      "没有进行中",
    );
    expect(takeoverStartErrorMessage(withCode("already_active"))).toContain(
      "已被接管",
    );
  });

  it("falls back to the server message then a generic default", () => {
    const withMsg = new ApiError(
      400,
      JSON.stringify({ error: { code: "weird", message: "服务端说明" } }),
    );
    expect(takeoverStartErrorMessage(withMsg)).toBe("服务端说明");
    expect(takeoverStartErrorMessage(new Error("x"))).toBe(
      "无法接管浏览器，请重试",
    );
  });
});

describe("toFrameSpace · object-contain 坐标换算", () => {
  it("maps the display center to the frame center (letterboxed left/right)", () => {
    // 容器 1000×500，帧 1000×1000 → scale 0.5，两侧各留白 250。
    const rect = { left: 0, top: 0, width: 1000, height: 500 };
    expect(toFrameSpace(500, 250, rect, 1000, 1000)).toEqual({
      x: 500,
      y: 500,
    });
  });

  it("maps the display center to the frame center (letterboxed top/bottom)", () => {
    // 容器 500×500，帧 1000×500 → scale 0.5，上下各留白 125。
    const rect = { left: 0, top: 0, width: 500, height: 500 };
    expect(toFrameSpace(250, 250, rect, 1000, 500)).toEqual({ x: 500, y: 250 });
  });

  it("accounts for the container's viewport offset", () => {
    const rect = { left: 100, top: 50, width: 1000, height: 500 };
    expect(toFrameSpace(600, 300, rect, 1000, 1000)).toEqual({
      x: 500,
      y: 500,
    });
  });

  it("clamps points in the letterbox / outside the frame to the edges", () => {
    const rect = { left: 0, top: 0, width: 1000, height: 500 };
    expect(toFrameSpace(0, 250, rect, 1000, 1000)).toEqual({ x: 0, y: 500 });
    expect(toFrameSpace(1000, 250, rect, 1000, 1000)).toEqual({
      x: 1000,
      y: 500,
    });
  });

  it("returns (0,0) for a degenerate frame / zero-size container", () => {
    expect(
      toFrameSpace(5, 5, { left: 0, top: 0, width: 100, height: 100 }, 0, 0),
    ).toEqual({ x: 0, y: 0 });
    expect(
      toFrameSpace(5, 5, { left: 0, top: 0, width: 0, height: 0 }, 100, 100),
    ).toEqual({ x: 0, y: 0 });
  });
});

describe("modifiersOf", () => {
  it("collects held modifiers, omitting when none", () => {
    expect(
      modifiersOf({
        altKey: false,
        ctrlKey: true,
        metaKey: false,
        shiftKey: true,
      }),
    ).toEqual(["ctrl", "shift"]);
    expect(
      modifiersOf({
        altKey: false,
        ctrlKey: false,
        metaKey: false,
        shiftKey: false,
      }),
    ).toBeUndefined();
  });
});

describe("formatTakeoverDuration", () => {
  it("formats minutes+seconds, and bare seconds under a minute", () => {
    expect(formatTakeoverDuration(65_000)).toBe("1分5秒");
    expect(formatTakeoverDuration(30_000)).toBe("30秒");
    expect(formatTakeoverDuration(0)).toBe("0秒");
    expect(formatTakeoverDuration(-100)).toBe("0秒");
  });
});

describe("createInputBatcher", () => {
  it("flushes buffered events after the interval", () => {
    vi.useFakeTimers();
    const send = vi.fn().mockResolvedValue(undefined);
    const b = createInputBatcher(send, 60);
    b.push({
      kind: "mouse",
      type: "down",
      x: 1,
      y: 1,
      button: 0,
      click_count: 1,
    });
    expect(send).not.toHaveBeenCalled();
    vi.advanceTimersByTime(60);
    expect(send).toHaveBeenCalledTimes(1);
    expect(send).toHaveBeenCalledWith([
      { kind: "mouse", type: "down", x: 1, y: 1, button: 0, click_count: 1 },
    ]);
  });

  it("coalesces consecutive mouse moves (only the latest survives)", () => {
    vi.useFakeTimers();
    const send = vi.fn().mockResolvedValue(undefined);
    const b = createInputBatcher(send, 60);
    b.push({ kind: "mouse", type: "move", x: 1, y: 1 });
    b.push({ kind: "mouse", type: "move", x: 2, y: 2 });
    vi.advanceTimersByTime(60);
    expect(send).toHaveBeenCalledWith([
      { kind: "mouse", type: "move", x: 2, y: 2 },
    ]);
  });

  it("flushes immediately on a commit event, batching prior events", () => {
    const send = vi.fn().mockResolvedValue(undefined);
    const b = createInputBatcher(send, 60);
    b.push({
      kind: "mouse",
      type: "down",
      x: 1,
      y: 1,
      button: 0,
      click_count: 1,
    });
    expect(send).not.toHaveBeenCalled();
    b.push({ kind: "mouse", type: "up", x: 1, y: 1, button: 0 });
    expect(send).toHaveBeenCalledTimes(1);
    expect(send).toHaveBeenCalledWith([
      { kind: "mouse", type: "down", x: 1, y: 1, button: 0, click_count: 1 },
      { kind: "mouse", type: "up", x: 1, y: 1, button: 0 },
    ]);
  });

  it("stop() flushes remaining events and ignores later pushes", () => {
    const send = vi.fn().mockResolvedValue(undefined);
    const b = createInputBatcher(send, 60);
    b.push({ kind: "key", type: "down", key: "a" });
    b.stop();
    expect(send).toHaveBeenCalledTimes(1);
    b.push({ kind: "key", type: "down", key: "b" });
    expect(send).toHaveBeenCalledTimes(1);
  });

  it("swallows send failures (best-effort, no throw)", () => {
    const send = vi.fn().mockRejectedValue(new Error("net down"));
    const b = createInputBatcher(send, 60);
    expect(() => b.push({ kind: "text", text: "secret" })).not.toThrow();
    expect(send).toHaveBeenCalledTimes(1);
  });
});
