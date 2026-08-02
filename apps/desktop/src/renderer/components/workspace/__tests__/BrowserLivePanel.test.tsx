// @vitest-environment jsdom
/**
 * L3「团队浏览器」M1 直播 + M2 接管 tab body (BrowserLivePanel) 渲染单测：
 * - 连接中 / 无直播(no_session) / 会话已结束(session_closed) / 断线重连各态文案。
 * - 逐帧换图：帧到达即 createObjectURL 换 <img src>、并 revoke 上一帧 URL（防泄漏）。
 * - 卸载回收：unmount 时 revoke 末帧 URL + stop() 收口 SSE。
 * - M2 接管流转：有活直播才显「接管」；turn 运行中仍显（D8）；pending browserLogin
 *   仅影响归还提示；start 成功→接管中条+归还；start 失败(no_session)显因回落；归还/会话结束/卸载
 *   都收口 end 并把留档乐观并入 store；键盘输入捕获 → 批量 POST。
 * mock services/browserLive 直接驱动回调；services/browserTakeover 仅 mock 网络（保留真坐标/批处理/
 * 文案纯函数）；桩 URL.createObjectURL/revoke（jsdom 缺失）。块注释隔开 @vitest-environment 指令。
 */

import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/services/browserLive", () => ({
  startBrowserLive: vi.fn(),
}));

vi.mock("@/services/browserTakeover", async (importOriginal) => {
  const actual =
    await importOriginal<typeof import("@/services/browserTakeover")>();
  return {
    ...actual,
    startBrowserTakeover: vi.fn(),
    endBrowserTakeover: vi.fn(),
    sendBrowserInput: vi.fn(),
    listBrowserTakeovers: vi.fn(),
  };
});

import type {
  BrowserLiveClient,
  BrowserLiveHandlers,
} from "@/services/browserLive";
import { startBrowserLive } from "@/services/browserLive";
import {
  endBrowserTakeover,
  sendBrowserInput,
  startBrowserTakeover,
} from "@/services/browserTakeover";
import { useBrowserTakeoverStore } from "@/stores/browserTakeover";
import { useConversationStore } from "@/stores/conversation";
import { EMPTY_RUNTIME } from "@/stores/conversation/runtime";
import type { Message } from "@/stores/conversation/types";
import {
  type ExecutionPlan,
  type RunFrame,
  useExecutionStore,
} from "@/stores/execution";
import { BrowserLivePanel } from "../BrowserLivePanel";

const mockStart = vi.mocked(startBrowserLive);
const mockStartTakeover = vi.mocked(startBrowserTakeover);
const mockEndTakeover = vi.mocked(endBrowserTakeover);
const mockSendInput = vi.mocked(sendBrowserInput);

let captured: BrowserLiveHandlers | null;
let stopSpy: ReturnType<typeof vi.fn>;
let urlSeq: number;

beforeEach(() => {
  captured = null;
  stopSpy = vi.fn();
  urlSeq = 0;
  URL.createObjectURL = vi.fn(
    () => `blob:frame-${++urlSeq}`,
  ) as unknown as typeof URL.createObjectURL;
  URL.revokeObjectURL = vi.fn() as unknown as typeof URL.revokeObjectURL;
  mockStart.mockReset();
  mockStart.mockImplementation((_conversationId, handlers) => {
    captured = handlers;
    return { stop: stopSpy } satisfies BrowserLiveClient;
  });
  mockStartTakeover.mockReset().mockResolvedValue({
    active: true,
    reason: "started",
  });
  mockEndTakeover.mockReset().mockResolvedValue(undefined);
  mockSendInput.mockReset().mockResolvedValue(undefined);
  useBrowserTakeoverStore.setState({ byConversation: {} });
  useExecutionStore.setState({ byId: {} });
  useConversationStore.setState({
    currentConversationId: null,
    byId: {},
  });
});

afterEach(cleanup);

/** Drive one or more live callbacks inside an act() so React flushes the update. */
function emit(fn: (h: BrowserLiveHandlers) => void): void {
  act(() => {
    if (captured) fn(captured);
  });
}

const FRAME = (frame_b64: string) => ({ frame_b64, width: 4, height: 4 });

/** Seed conversation + execution with a pending `browserLogin` escalate. */
function seedPendingBrowserLogin(
  conversationId: string,
  messageId: string,
): void {
  const msg: Message = {
    id: messageId,
    role: "assistant",
    content: "",
    createdAt: "2026-07-26T00:00:00.000Z",
    executionId: "exec-1",
    isStreaming: false,
  };
  useConversationStore.setState({
    currentConversationId: conversationId,
    byId: {
      [conversationId]: { ...EMPTY_RUNTIME, messages: [msg] },
    },
  });
  const plan: ExecutionPlan = {
    id: "exec-1",
    planType: "multi_agent",
    taskSummary: "登录",
    agents: [{ id: "agent-1", role: "研究员" }],
    runs: [{ id: "run-1", agentId: "agent-1", task: "登", dependsOn: [] }],
  };
  const frames: RunFrame[] = [
    {
      t: 1,
      kind: "run_started",
      agentId: "agent-1",
      runId: "run-1",
      parentRunId: null,
      runKind: "agent",
      continuesRunId: null,
    },
    {
      t: 2,
      kind: "escalation_required",
      escalationId: "esc-login",
      runId: "run-1",
      agentId: "agent-1",
      question: "请在浏览器里登录后再继续",
      assumption: "用户已登录",
      escalationKind: "normal",
      browserLogin: true,
    },
  ];
  const exec = useExecutionStore.getState();
  exec.startExecution(plan, messageId);
  exec.recordFrames(frames, messageId);
}

/** Seed conversation + execution with a running turn (no pending browserLogin). */
function seedRunningTurn(conversationId: string, messageId: string): void {
  const msg: Message = {
    id: messageId,
    role: "assistant",
    content: "",
    createdAt: "2026-07-26T00:00:00.000Z",
    executionId: "exec-1",
    isStreaming: false,
  };
  useConversationStore.setState({
    currentConversationId: conversationId,
    byId: {
      [conversationId]: { ...EMPTY_RUNTIME, messages: [msg] },
    },
  });
  const plan: ExecutionPlan = {
    id: "exec-1",
    planType: "multi_agent",
    taskSummary: "查资料",
    agents: [{ id: "agent-1", role: "研究员" }],
    runs: [{ id: "run-1", agentId: "agent-1", task: "查", dependsOn: [] }],
  };
  const exec = useExecutionStore.getState();
  exec.startExecution(plan, messageId);
  exec.recordFrames(
    [
      {
        t: 1,
        kind: "run_started",
        agentId: "agent-1",
        runId: "run-1",
        parentRunId: null,
        runKind: "agent",
        continuesRunId: null,
      },
    ],
    messageId,
  );
}

describe("BrowserLivePanel · 状态文案", () => {
  it("attaches on mount with the conversation id and shows 连接中", () => {
    render(<BrowserLivePanel conversationId="c1" />);
    expect(mockStart).toHaveBeenCalledWith("c1", expect.anything(), undefined);
    expect(screen.getByText("连接中…")).toBeTruthy();
  });

  it("passes sessionId to startBrowserLive when provided", () => {
    render(<BrowserLivePanel conversationId="c1" sessionId="sess-live" />);
    expect(mockStart).toHaveBeenCalledWith("c1", expect.anything(), {
      sessionId: "sess-live",
    });
  });

  it("shows the no-session state", () => {
    render(<BrowserLivePanel conversationId="c1" />);
    emit((h) => h.onStatus("no_session"));
    expect(screen.getByText("当前没有进行中的直播")).toBeTruthy();
  });

  it("shows the reconnecting state when the transport drops", () => {
    render(<BrowserLivePanel conversationId="c1" />);
    emit((h) => h.onConnection("reconnecting"));
    expect(screen.getByText("连接已断开，正在重连…")).toBeTruthy();
  });

  it("shows the session-closed state with no prior frame", () => {
    render(<BrowserLivePanel conversationId="c1" />);
    emit((h) => h.onStatus("session_closed"));
    expect(screen.getByText("直播已结束")).toBeTruthy();
  });
});

describe("BrowserLivePanel · 逐帧换图 + objectURL 回收", () => {
  it("renders the first frame via an object URL and marks 直播中", () => {
    render(<BrowserLivePanel conversationId="c1" />);
    emit((h) => {
      h.onConnection("open");
      h.onStatus("started");
    });
    emit((h) => h.onFrame(FRAME("AAAA")));

    const img = screen.getByAltText("浏览器直播画面") as HTMLImageElement;
    expect(img.getAttribute("src")).toBe("blob:frame-1");
    expect(URL.createObjectURL).toHaveBeenCalledTimes(1);
    expect(screen.getByText("直播中")).toBeTruthy();
  });

  it("swaps to the newest frame and revokes the previous object URL", () => {
    render(<BrowserLivePanel conversationId="c1" />);
    emit((h) => {
      h.onConnection("open");
      h.onStatus("started");
    });
    emit((h) => h.onFrame(FRAME("AAAA")));
    emit((h) => h.onFrame(FRAME("BBBB")));

    const img = screen.getByAltText("浏览器直播画面") as HTMLImageElement;
    expect(img.getAttribute("src")).toBe("blob:frame-2");
    expect(URL.createObjectURL).toHaveBeenCalledTimes(2);
    // The superseded frame's URL is revoked; the current one is not.
    expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:frame-1");
    expect(URL.revokeObjectURL).not.toHaveBeenCalledWith("blob:frame-2");
  });

  it("keeps the last frame when the session closes, overlaying 直播已结束", () => {
    render(<BrowserLivePanel conversationId="c1" />);
    emit((h) => {
      h.onConnection("open");
      h.onStatus("started");
      h.onFrame(FRAME("AAAA"));
    });
    emit((h) => h.onStatus("session_closed"));

    // Last frame retained (not blanked) + an ended overlay.
    expect(screen.getByAltText("浏览器直播画面")).toBeTruthy();
    expect(screen.getByText("直播已结束")).toBeTruthy();
  });

  it("revokes the last object URL and stops the client on unmount", () => {
    const { unmount } = render(<BrowserLivePanel conversationId="c1" />);
    emit((h) => {
      h.onConnection("open");
      h.onStatus("started");
      h.onFrame(FRAME("AAAA"));
    });

    unmount();
    expect(stopSpy).toHaveBeenCalledTimes(1);
    expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:frame-1");
  });
});

/** Drive the panel to a live-with-frame state (started + open + a frame). */
function goLive(): void {
  emit((h) => {
    h.onConnection("open");
    h.onStatus("started");
  });
  emit((h) => h.onFrame(FRAME("AAAA")));
}

/** Click a button by its visible text, flushing the async takeover transition. */
async function clickAsync(text: string): Promise<void> {
  await act(async () => {
    fireEvent.click(screen.getByText(text));
  });
}

describe("BrowserLivePanel · M2 接管流转", () => {
  it("offers 接管 only once a live frame is streaming", () => {
    render(<BrowserLivePanel conversationId="c1" />);
    expect(screen.queryByText("接管")).toBeNull();
    goLive();
    expect(screen.getByText("接管")).toBeTruthy();
  });

  it("offers 接管 while a turn is running (D8 anytime)", () => {
    seedRunningTurn("c1", "a1");
    render(<BrowserLivePanel conversationId="c1" />);
    goLive();
    expect(screen.getByText("接管")).toBeTruthy();
  });

  it("keeps 接管 while running if pending browserLogin", () => {
    seedPendingBrowserLogin("c1", "a1");
    render(<BrowserLivePanel conversationId="c1" />);
    goLive();
    expect(screen.getByText("接管")).toBeTruthy();
  });

  it("enters takeover: calls start, shows the 接管中 bar + 归还控制, hides 接管", async () => {
    render(<BrowserLivePanel conversationId="c1" />);
    goLive();
    await clickAsync("接管");

    expect(mockStartTakeover).toHaveBeenCalledWith("c1", undefined);
    expect(screen.getByText(/接管中/)).toBeTruthy();
    expect(screen.getByText("归还控制")).toBeTruthy();
    expect(screen.queryByText("接管")).toBeNull();
  });

  it("passes sessionId to takeover start/end", async () => {
    render(<BrowserLivePanel conversationId="c1" sessionId="sess-live" />);
    goLive();
    await clickAsync("接管");
    expect(mockStartTakeover).toHaveBeenCalledWith("c1", {
      sessionId: "sess-live",
    });
    await clickAsync("归还控制");
    expect(mockEndTakeover).toHaveBeenCalledWith("c1", {
      sessionId: "sess-live",
    });
  });

  it("surfaces a start failure (no_session reason) and stays idle", async () => {
    const { TakeoverStartError } = await import("@/services/browserTakeover");
    mockStartTakeover.mockRejectedValue(new TakeoverStartError("no_session"));
    render(<BrowserLivePanel conversationId="c1" />);
    goLive();
    await clickAsync("接管");

    expect(screen.getByText("当前没有进行中的浏览器会话")).toBeTruthy();
    // Back to idle → the 接管 affordance returns, no 接管中 bar.
    expect(screen.getByText("接管")).toBeTruthy();
    expect(screen.queryByText("归还控制")).toBeNull();
  });

  it("returns control: ends the takeover, records it, and shows 控制已归还 (no pending login)", async () => {
    render(<BrowserLivePanel conversationId="c1" />);
    goLive();
    await clickAsync("接管");
    await clickAsync("归还控制");

    expect(mockEndTakeover).toHaveBeenCalledWith("c1", undefined);
    const records = useBrowserTakeoverStore.getState().byConversation.c1 ?? [];
    expect(records).toHaveLength(1);
    expect(records[0].endedAt).not.toBeNull();
    // Chrome returns to the normal live header.
    expect(screen.queryByText("归还控制")).toBeNull();
    // 普通接管归还：不暗示登录 / 发继续。
    expect(screen.getByText("控制已归还")).toBeTruthy();
    expect(
      screen.queryByText("登录完成后，回到对话点「已登录，继续」"),
    ).toBeNull();
  });

  it("returns control during pending browserLogin: hint aligns with EscalationCard", async () => {
    seedPendingBrowserLogin("c1", "a1");
    render(<BrowserLivePanel conversationId="c1" />);
    goLive();
    await clickAsync("接管");
    await clickAsync("归还控制");

    expect(mockEndTakeover).toHaveBeenCalledWith("c1", undefined);
    expect(
      screen.getByText("登录完成后，回到对话点「已登录，继续」"),
    ).toBeTruthy();
    expect(screen.queryByText("控制已归还")).toBeNull();
  });

  it("auto-returns control when the session closes mid-takeover (no return hint)", async () => {
    render(<BrowserLivePanel conversationId="c1" />);
    goLive();
    await clickAsync("接管");

    await act(async () => {
      emit((h) => h.onStatus("session_closed"));
    });

    expect(mockEndTakeover).toHaveBeenCalledWith("c1", undefined);
    expect(screen.queryByText("归还控制")).toBeNull();
    expect(useBrowserTakeoverStore.getState().byConversation.c1).toHaveLength(
      1,
    );
    expect(screen.queryByText("控制已归还")).toBeNull();
    expect(
      screen.queryByText("登录完成后，回到对话点「已登录，继续」"),
    ).toBeNull();
  });

  it("best-effort ends the takeover on unmount", async () => {
    const { unmount } = render(<BrowserLivePanel conversationId="c1" />);
    goLive();
    await clickAsync("接管");

    unmount();
    expect(mockEndTakeover).toHaveBeenCalledWith("c1", undefined);
  });

  it("captures keyboard input on the takeover surface and batches it", async () => {
    render(<BrowserLivePanel conversationId="c1" />);
    goLive();
    await clickAsync("接管");

    const surface = screen.getByLabelText(/接管中的浏览器画面/);
    await act(async () => {
      fireEvent.keyDown(surface, { key: "a", code: "KeyA" });
      fireEvent.keyUp(surface, { key: "a", code: "KeyA" });
    });

    // keyUp is a commit event → flushes the batch (down + up) to the input endpoint.
    expect(mockSendInput).toHaveBeenCalledWith(
      "c1",
      expect.arrayContaining([
        expect.objectContaining({ kind: "key", type: "down", key: "a" }),
        expect.objectContaining({ kind: "key", type: "up", key: "a" }),
      ]),
    );
  });
});
