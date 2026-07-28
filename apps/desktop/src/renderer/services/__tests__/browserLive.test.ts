/**
 * L3「团队浏览器」M1 直播 SSE 客户端 (services/browserLive.ts) 单测：
 * - 端点/信封：GET 附着端点 + credentials:"include"，解析 browser_live_frame / _status 信封。
 * - 帧更新 / 状态切换：onFrame / onStatus 逐条转发。
 * - 连接生命周期：connecting → open；掉线 → reconnecting → 退避重连再 fetch。
 * - 401：renewed 后重连；auth_dead 跳登录且不再重连。
 * - stop()：中止在飞请求（abort signal）+ 静默后续回调。
 * mock fetch + ReadableStream 造 SSE 流（沿 handoff.test.ts 的 sseResponse 先例）。
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/services/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/services/api")>();
  return {
    ...actual,
    tryRefresh: vi.fn(),
    notifyUnauthorized: vi.fn(),
  };
});

import { notifyUnauthorized, tryRefresh } from "@/services/api";
import { type BrowserLiveHandlers, startBrowserLive } from "../browserLive";

const mockRefresh = vi.mocked(tryRefresh);
const mockNotifyUnauthorized = vi.mocked(notifyUnauthorized);

let fetchMock: ReturnType<typeof vi.fn>;

function handlers() {
  return {
    onFrame: vi.fn(),
    onStatus: vi.fn(),
    onConnection: vi.fn(),
  } satisfies BrowserLiveHandlers;
}

/** One-shot SSE Response: emits the given events, then closes the stream. */
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

/** A live SSE Response whose frames the test pushes over time (and closes on demand). */
function liveStream() {
  let ctrl!: ReadableStreamDefaultController<Uint8Array>;
  const enc = new TextEncoder();
  const stream = new ReadableStream<Uint8Array>({
    start(c) {
      ctrl = c;
    },
  });
  return {
    response: new Response(stream, {
      status: 200,
      headers: { "Content-Type": "text/event-stream" },
    }),
    push: (e: unknown) =>
      ctrl.enqueue(enc.encode(`data: ${JSON.stringify(e)}\n\n`)),
    close: () => ctrl.close(),
  };
}

const conn = (h: ReturnType<typeof handlers>) =>
  h.onConnection.mock.calls.map((c) => c[0]);

beforeEach(() => {
  fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
  mockRefresh.mockReset();
  mockNotifyUnauthorized.mockReset();
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  vi.useRealTimers();
});

describe("startBrowserLive · 端点与信封", () => {
  it("attaches to the conversation's live endpoint with a credentialed GET", async () => {
    const s = liveStream();
    fetchMock.mockResolvedValue(s.response);
    const h = handlers();
    const client = startBrowserLive("conv-42", h);

    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain("/v1/conversations/conv-42/browser/live");
    expect(url).not.toContain("session_id=");
    expect(init.method).toBe("GET");
    expect(init.credentials).toBe("include");
    client.stop();
  });

  it("appends ?session_id= when opts.sessionId is set", async () => {
    const s = liveStream();
    fetchMock.mockResolvedValue(s.response);
    const h = handlers();
    const client = startBrowserLive("conv-42", h, { sessionId: "sess-tab-1" });

    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    const [url] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain("/v1/conversations/conv-42/browser/live?");
    expect(url).toContain("session_id=sess-tab-1");
    client.stop();
  });

  it("forwards frames and reports connecting → open", async () => {
    const s = liveStream();
    fetchMock.mockResolvedValue(s.response);
    const h = handlers();
    const client = startBrowserLive("c1", h);

    await vi.waitFor(() => expect(conn(h)).toEqual(["connecting", "open"]));
    s.push({ type: "browser_live_status", payload: { state: "started" } });
    s.push({
      type: "browser_live_frame",
      payload: { frame_b64: "AAAA", width: 1280, height: 720 },
    });

    await vi.waitFor(() =>
      expect(h.onFrame).toHaveBeenCalledWith({
        frame_b64: "AAAA",
        width: 1280,
        height: 720,
      }),
    );
    expect(h.onStatus).toHaveBeenCalledWith("started");
    client.stop();
  });

  it("forwards no_session / session_closed status", async () => {
    const s = liveStream();
    fetchMock.mockResolvedValue(s.response);
    const h = handlers();
    const client = startBrowserLive("c1", h);

    await vi.waitFor(() => expect(conn(h)).toContain("open"));
    s.push({ type: "browser_live_status", payload: { state: "no_session" } });
    await vi.waitFor(() =>
      expect(h.onStatus).toHaveBeenCalledWith("no_session"),
    );
    s.push({
      type: "browser_live_status",
      payload: { state: "session_closed" },
    });
    await vi.waitFor(() =>
      expect(h.onStatus).toHaveBeenCalledWith("session_closed"),
    );
    client.stop();
  });

  it("ignores heartbeat / unknown envelopes", async () => {
    const s = liveStream();
    fetchMock.mockResolvedValue(s.response);
    const h = handlers();
    const client = startBrowserLive("c1", h);
    await vi.waitFor(() => expect(conn(h)).toContain("open"));

    s.push({ type: "ready" });
    s.push({ type: "browser_live_status", payload: { state: "started" } });
    await vi.waitFor(() => expect(h.onStatus).toHaveBeenCalledWith("started"));
    expect(h.onFrame).not.toHaveBeenCalled();
    client.stop();
  });
});

describe("startBrowserLive · 断线重连", () => {
  it("reconnects with backoff after the stream drops", async () => {
    vi.useFakeTimers();
    vi.spyOn(Math, "random").mockReturnValue(0);
    const dropped = sseResponse([
      { type: "browser_live_status", payload: { state: "started" } },
    ]);
    const revived = liveStream();
    fetchMock
      .mockResolvedValueOnce(dropped)
      .mockResolvedValueOnce(revived.response);
    const h = handlers();
    const client = startBrowserLive("c1", h);

    // First stream opens, emits, then closes → schedule a reconnect.
    await vi.advanceTimersByTimeAsync(0);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(conn(h)).toContain("reconnecting");

    // Backoff delay = 1000 * 2^0 (jitter pinned to 0) → fires the second attach.
    await vi.advanceTimersByTimeAsync(1000);
    expect(fetchMock).toHaveBeenCalledTimes(2);
    client.stop();
  });
});

describe("startBrowserLive · 401 鉴权", () => {
  it("refreshes once then reconnects when the token renews", async () => {
    vi.useFakeTimers();
    vi.spyOn(Math, "random").mockReturnValue(0);
    mockRefresh.mockResolvedValue("renewed");
    fetchMock
      .mockResolvedValueOnce(new Response(null, { status: 401 }))
      .mockResolvedValueOnce(liveStream().response);
    const h = handlers();
    const client = startBrowserLive("c1", h);

    await vi.advanceTimersByTimeAsync(0);
    expect(mockRefresh).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(1000);
    expect(fetchMock).toHaveBeenCalledTimes(2);
    client.stop();
  });

  it("drops to login and stops when auth is dead", async () => {
    vi.useFakeTimers();
    mockRefresh.mockResolvedValue("auth_dead");
    fetchMock.mockResolvedValue(new Response(null, { status: 401 }));
    const h = handlers();
    const client = startBrowserLive("c1", h);

    await vi.advanceTimersByTimeAsync(0);
    expect(mockNotifyUnauthorized).toHaveBeenCalledTimes(1);
    // No reconnect scheduled after auth death.
    await vi.advanceTimersByTimeAsync(5000);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    client.stop();
  });
});

describe("startBrowserLive · stop()", () => {
  it("aborts the in-flight request and halts callbacks", async () => {
    const s = liveStream();
    fetchMock.mockResolvedValue(s.response);
    const h = handlers();
    const client = startBrowserLive("c1", h);

    await vi.waitFor(() => expect(conn(h)).toContain("open"));
    const { signal } = fetchMock.mock.calls[0][1] as RequestInit;
    expect((signal as AbortSignal).aborted).toBe(false);

    client.stop();
    expect((signal as AbortSignal).aborted).toBe(true);

    const before = h.onFrame.mock.calls.length;
    try {
      s.push({
        type: "browser_live_frame",
        payload: { frame_b64: "AAAA", width: 1, height: 1 },
      });
    } catch {
      /* stream may already be torn down by the abort — fine */
    }
    await new Promise((r) => setTimeout(r, 0));
    expect(h.onFrame).toHaveBeenCalledTimes(before);
  });
});
