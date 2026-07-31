import { StreamError } from "@/lib/errors";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// 隔离断言 sendTurn / runResume「探活 → 路由 / 降级收敛」这一段的可观察契约：
// sendTurn——探活 ok 走 sidecar、首探失败(probed)走云+提示一次、bad 缓存命中(!probed)静默走云、
// 回合启动期失败(recoverable)降级并标坏、中途失败(!recoverable)不自动降级；
// runResume——探活 ok 走 sidecar 续跑、探活失败保留续跑卡 + 出横幅、绝不降级走云（本机帧云端没有）。
// 协作者全 mock；conversation / pausedTurn store 用真实，使 stillOptimistic / 截断 / 帧认领忠实。
vi.mock("@/hooks/useConversations", () => ({
  getConversations: vi.fn(() => []),
  bumpConversationCache: vi.fn(),
  restoreConversationCache: vi.fn(),
}));
vi.mock("@/services/sidecarRouting", () => ({
  resolveSidecarRoot: vi.fn(),
  buildSidecarHistory: vi.fn(() => []),
}));
vi.mock("@/services/sidecarHealth", () => ({
  probeSidecar: vi.fn(),
  markSidecarUnhealthy: vi.fn(),
  clearSidecarHealth: vi.fn(),
}));
vi.mock("@/services/streamConversation", () => ({
  attachConversation: vi.fn(),
  regenerateConversation: vi.fn(),
  resumeConversation: vi.fn(),
  streamConversation: vi.fn(() => Promise.resolve()),
}));
vi.mock("@/services/streamConversationViaSidecar", () => ({
  resumeConversationViaSidecar: vi.fn(),
  streamConversationViaSidecar: vi.fn(),
}));
vi.mock("@/services/messages", () => ({ loadLatestWindow: vi.fn() }));
// notifyError 由 stream 错误路径间接引入；排队 toast 现由 turn_queued → queuedNotify。
vi.mock("@/lib/toast", () => ({ notifyInfo: vi.fn(), notifyError: vi.fn() }));

import { notifyInfo } from "@/lib/toast";
import {
  clearSidecarHealth,
  markSidecarUnhealthy,
  probeSidecar,
} from "@/services/sidecarHealth";
import { resolveSidecarRoot } from "@/services/sidecarRouting";
import {
  resumeConversation,
  streamConversation,
} from "@/services/streamConversation";
import {
  resumeConversationViaSidecar,
  streamConversationViaSidecar,
} from "@/services/streamConversationViaSidecar";
import { useConversationStore } from "@/stores/conversation";
import { type PendingResume, usePausedTurnStore } from "@/stores/pausedTurns";
import { runResume, sendTurn } from "../turns";

const resolveSidecarRootMock = vi.mocked(resolveSidecarRoot);
const probeSidecarMock = vi.mocked(probeSidecar);
const markSidecarUnhealthyMock = vi.mocked(markSidecarUnhealthy);
const clearSidecarHealthMock = vi.mocked(clearSidecarHealth);
const streamConversationMock = vi.mocked(streamConversation);
const streamViaSidecarMock = vi.mocked(streamConversationViaSidecar);
const resumeConversationMock = vi.mocked(resumeConversation);
const resumeViaSidecarMock = vi.mocked(resumeConversationViaSidecar);
const notifyInfoMock = vi.mocked(notifyInfo);

const TARGET = { rootId: "r1", subpath: "" };

function spec() {
  return {
    conversationId: "c1",
    content: "hi",
    attachments: [],
    optimisticUserId: "opt1",
  };
}

/** Seed the optimistic user bubble sendTurn expects: stillOptimistic = true → a
 *  fresh attempt (not regenerate-from-persisted). */
function seedOptimisticUser(): void {
  useConversationStore.getState().addMessage(
    {
      id: "opt1",
      role: "user",
      content: "hi",
      createdAt: "",
      executionId: null,
      isStreaming: false,
    },
    "c1",
  );
}

beforeEach(() => {
  useConversationStore.setState({ currentConversationId: null, byId: {} });
  usePausedTurnStore.setState({ pending: [] });
  vi.clearAllMocks();
  streamConversationMock.mockResolvedValue(undefined);
  seedOptimisticUser();
});

afterEach(() => {
  useConversationStore.setState({ currentConversationId: null, byId: {} });
  usePausedTurnStore.setState({ pending: [] });
});

describe("sendTurn — 探活路由 / 降级收敛（探活增强）", () => {
  it("探活通过 → 走本地 sidecar，不碰云链路", async () => {
    resolveSidecarRootMock.mockResolvedValue(TARGET);
    probeSidecarMock.mockResolvedValue({
      healthy: true,
      probed: true,
      detail: null,
    });
    streamViaSidecarMock.mockResolvedValue(undefined as never);

    await sendTurn(spec());

    expect(probeSidecarMock).toHaveBeenCalledTimes(1);
    expect(streamViaSidecarMock).toHaveBeenCalledWith(
      expect.objectContaining({ conversationId: "c1", rootId: "r1" }),
    );
    expect(streamConversationMock).not.toHaveBeenCalled();
  });

  it("探活失败 → 提示一次（带诊断）并走云，不走 sidecar", async () => {
    resolveSidecarRootMock.mockResolvedValue(TARGET);
    probeSidecarMock.mockResolvedValue({
      healthy: false,
      probed: true,
      detail: "本地引擎启动失败：spawn uv ENOENT",
    });

    await sendTurn(spec());

    expect(notifyInfoMock).toHaveBeenCalledTimes(1);
    expect(String(notifyInfoMock.mock.calls[0][0])).toContain(
      "spawn uv ENOENT",
    );
    expect(streamConversationMock).toHaveBeenCalledTimes(1);
    expect(streamViaSidecarMock).not.toHaveBeenCalled();
  });

  it("探活通过但回合启动期失败(recoverable) → 标坏 + 降级走云", async () => {
    resolveSidecarRootMock.mockResolvedValue(TARGET);
    probeSidecarMock.mockResolvedValue({
      healthy: true,
      probed: true,
      detail: null,
    });
    streamViaSidecarMock.mockRejectedValue(
      new StreamError("sidecar", undefined, {
        serverMessage: "拉不起",
        recoverable: true,
      }),
    );

    await sendTurn(spec());

    expect(markSidecarUnhealthyMock).toHaveBeenCalledWith(TARGET);
    expect(streamConversationMock).toHaveBeenCalledTimes(1); // 降级走云
  });

  it("中途失败(!recoverable) → 不自动降级、不标坏（照常出横幅）", async () => {
    resolveSidecarRootMock.mockResolvedValue(TARGET);
    probeSidecarMock.mockResolvedValue({
      healthy: true,
      probed: true,
      detail: null,
    });
    streamViaSidecarMock.mockRejectedValue(
      new StreamError("sidecar", undefined, {
        serverMessage: "中途崩",
        recoverable: false,
      }),
    );

    await sendTurn(spec());

    expect(markSidecarUnhealthyMock).not.toHaveBeenCalled();
    expect(streamConversationMock).not.toHaveBeenCalled();
  });

  it("bad 缓存命中(!probed) → 静默走云、不再提示", async () => {
    resolveSidecarRootMock.mockResolvedValue(TARGET);
    // 该根本会话已探明坏：probeSidecar 命中缓存（probed:false），不该再 notifyInfo。
    probeSidecarMock.mockResolvedValue({
      healthy: false,
      probed: false,
      detail: null,
    });

    await sendTurn(spec());

    expect(streamConversationMock).toHaveBeenCalledTimes(1); // 静默走云
    expect(streamViaSidecarMock).not.toHaveBeenCalled();
    expect(notifyInfoMock).not.toHaveBeenCalled(); // 不再打扰
  });
});

/** 构造一个 sidecar 暂停帧（plan_review），续跑测试用：字段齐全、内容最小。 */
function pendingFrame(messageId: string, conversationId = "c1"): PendingResume {
  return {
    messageId,
    conversationId,
    checkpointId: "ck1",
    kind: "plan_review",
    userMessage: "原始请求",
    userMessageId: "u-orig",
    steps: [],
    pending: [],
    workers: [],
    tools: [],
    primitive: "delegate",
    motion: "",
    form: "",
    sides: [],
    maxRounds: 0,
    thorough: true,
    offerResearchFirst: false,
    researchFirstRecommended: false,
    question: "",
    context: "",
    assumptions: [],
    questions: [],
    styleOptions: [],
    formatOptions: [],
    intent: "kickoff",
    origin: "sidecar",
  };
}

describe("runResume — 续跑探活（不降级、本机帧只在本地）", () => {
  beforeEach(() => {
    useConversationStore.setState({ currentConversationId: "c1", byId: {} });
    usePausedTurnStore.setState({ pending: [pendingFrame("m1")] });
    // Seed the paused assistant so resume reuses it (Option A) instead of fallback-create.
    const conv = useConversationStore.getState();
    conv.addMessage({
      id: "u-orig",
      role: "user",
      content: "原始请求",
      createdAt: "",
      executionId: null,
      isStreaming: false,
    });
    conv.addMessage({
      id: "client-paused",
      role: "assistant",
      content: "",
      createdAt: "",
      executionId: null,
      isStreaming: false,
      serverMessageId: "m1",
      finishReason: "paused",
    });
  });

  it("探活通过 → 本地 sidecar 续跑、认领续跑卡", async () => {
    resolveSidecarRootMock.mockResolvedValue(TARGET);
    probeSidecarMock.mockResolvedValue({
      healthy: true,
      probed: true,
      detail: null,
    });
    resumeViaSidecarMock.mockResolvedValue(undefined as never);

    const before = useConversationStore
      .getState()
      .byId.c1?.messages.filter((m) => m.role === "assistant").length;

    await runResume("m1", "continue", "");

    expect(resumeViaSidecarMock).toHaveBeenCalledWith(
      expect.objectContaining({
        messageId: "m1",
        rootId: "r1",
        userMessageId: "u-orig",
      }),
    );
    expect(resumeConversationMock).not.toHaveBeenCalled();
    expect(usePausedTurnStore.getState().pending).toHaveLength(0); // 帧已认领
    const assistants = useConversationStore
      .getState()
      .byId.c1?.messages.filter((m) => m.role === "assistant");
    expect(assistants).toHaveLength(before);
    expect(assistants[0].id).toBe("client-paused");
    expect(assistants[0].isStreaming).toBe(true);
  });

  it("探活失败 → 保留续跑卡 + 出横幅，绝不降级走云", async () => {
    resolveSidecarRootMock.mockResolvedValue(TARGET);
    probeSidecarMock.mockResolvedValue({
      healthy: false,
      probed: true,
      detail: "venv 损坏",
    });

    await expect(runResume("m1", "continue", "")).rejects.toThrow(
      /sidecar probe failed/,
    );

    expect(resumeViaSidecarMock).not.toHaveBeenCalled();
    expect(resumeConversationMock).not.toHaveBeenCalled(); // 不降级走云（云端没这帧）
    expect(usePausedTurnStore.getState().pending).toHaveLength(1); // 续跑卡保留
    expect(useConversationStore.getState().byId.c1?.error).toContain(
      "venv 损坏",
    );
  });

  it("sidecar 帧无 target → 留卡 + 横幅，绝不降级走云", async () => {
    resolveSidecarRootMock.mockResolvedValue(null);

    await expect(runResume("m1", "continue", "")).rejects.toThrow(
      /sidecar unavailable/,
    );

    expect(probeSidecarMock).not.toHaveBeenCalled();
    expect(resumeViaSidecarMock).not.toHaveBeenCalled();
    expect(resumeConversationMock).not.toHaveBeenCalled(); // 不降级走云（云端没这帧）
    expect(usePausedTurnStore.getState().pending).toHaveLength(1); // 续跑卡保留
    expect(useConversationStore.getState().byId.c1?.error).toContain(
      "本地引擎暂不可用",
    );
  });

  it("云端帧未绑本地根 → 不探活、直接走云 resume", async () => {
    resolveSidecarRootMock.mockResolvedValue(null);
    usePausedTurnStore.setState({
      pending: [{ ...pendingFrame("m1"), origin: "server" }],
    });
    resumeConversationMock.mockResolvedValue(undefined as never);

    await runResume("m1", "continue", "");

    expect(probeSidecarMock).not.toHaveBeenCalled();
    expect(resumeConversationMock).toHaveBeenCalledTimes(1);
    expect(resumeViaSidecarMock).not.toHaveBeenCalled();
    expect(usePausedTurnStore.getState().pending).toHaveLength(0);
  });

  it("云端暂停帧（origin=server）即使绑了本地根也走云 resume", async () => {
    resolveSidecarRootMock.mockResolvedValue(TARGET);
    usePausedTurnStore.setState({
      pending: [{ ...pendingFrame("m1"), origin: "server" }],
    });
    resumeConversationMock.mockResolvedValue(undefined as never);

    await runResume("m1", "continue", "");

    expect(probeSidecarMock).not.toHaveBeenCalled();
    expect(resumeConversationMock).toHaveBeenCalledTimes(1);
    expect(resumeViaSidecarMock).not.toHaveBeenCalled();
    expect(usePausedTurnStore.getState().pending).toHaveLength(0);
  });

  it("请求被拒(404) → 恢复续跑卡 + 横幅", async () => {
    resolveSidecarRootMock.mockResolvedValue(null);
    usePausedTurnStore.setState({
      pending: [{ ...pendingFrame("m1"), origin: "server" }],
    });
    resumeConversationMock.mockRejectedValue(
      new StreamError("http", 404, {
        code: "not_found",
        serverMessage: "暂停帧不存在",
      }),
    );

    await expect(runResume("m1", "continue", "")).rejects.toBeInstanceOf(
      StreamError,
    );

    expect(usePausedTurnStore.getState().pending).toHaveLength(1);
    expect(usePausedTurnStore.getState().pending[0]?.messageId).toBe("m1");
    expect(useConversationStore.getState().byId.c1?.error).toContain(
      "暂停帧不存在",
    );
  });

  it("请求被拒(409 turn_in_progress) → 恢复续跑卡 + 明确文案", async () => {
    resolveSidecarRootMock.mockResolvedValue(null);
    usePausedTurnStore.setState({
      pending: [{ ...pendingFrame("m1"), origin: "server" }],
    });
    resumeConversationMock.mockRejectedValue(
      new StreamError("http", 409, { code: "turn_in_progress" }),
    );

    await expect(runResume("m1", "continue", "")).rejects.toBeInstanceOf(
      StreamError,
    );

    expect(usePausedTurnStore.getState().pending).toHaveLength(1);
    expect(useConversationStore.getState().byId.c1?.error).toContain(
      "正在进行的回合",
    );
  });

  it("流中断(network) → 不恢复续跑卡", async () => {
    resolveSidecarRootMock.mockResolvedValue(null);
    usePausedTurnStore.setState({
      pending: [{ ...pendingFrame("m1"), origin: "server" }],
    });
    resumeConversationMock.mockRejectedValue(new StreamError("network"));
    // rejoinLiveTurn → attachConversation；返回 attached 表示已接手，不恢复卡。
    const { attachConversation } = await import(
      "@/services/streamConversation"
    );
    vi.mocked(attachConversation).mockResolvedValue("attached");

    await runResume("m1", "continue", "");

    expect(usePausedTurnStore.getState().pending).toHaveLength(0);
  });

  it("用户 abort → 不恢复续跑卡", async () => {
    resolveSidecarRootMock.mockResolvedValue(null);
    usePausedTurnStore.setState({
      pending: [{ ...pendingFrame("m1"), origin: "server" }],
    });
    resumeConversationMock.mockRejectedValue(
      new DOMException("Aborted", "AbortError"),
    );

    await runResume("m1", "continue", "");

    expect(usePausedTurnStore.getState().pending).toHaveLength(0);
    expect(useConversationStore.getState().byId.c1?.error).toBeNull();
  });

  it("探活失败横幅的「重试」清缓存强制重探（非死按钮）", async () => {
    resolveSidecarRootMock.mockResolvedValue(TARGET);
    probeSidecarMock.mockResolvedValue({
      healthy: false,
      probed: true,
      detail: null,
    });

    await expect(runResume("m1", "continue", "")).rejects.toThrow(
      /sidecar probe failed/,
    );
    expect(probeSidecarMock).toHaveBeenCalledTimes(1);

    const retry = useConversationStore.getState().byId.c1?.retry;
    expect(retry).toBeTypeOf("function");
    retry?.(); // 用户点「重试」
    expect(clearSidecarHealthMock).toHaveBeenCalledTimes(1); // 同步先清缓存

    // 清缓存后重试会真重探（生产里 clearSidecarHealth 清 map → probeSidecar 不再命中 bad）。
    await vi.waitFor(() => expect(probeSidecarMock).toHaveBeenCalledTimes(2));
    expect(usePausedTurnStore.getState().pending).toHaveLength(1); // 仍未续成功 → 帧保留
  });

  it("有冷卡 + isGenerating → 先收口再续跑（不挡死）", async () => {
    useConversationStore.getState().setGenerating(true, "c1");
    resolveSidecarRootMock.mockResolvedValue(TARGET);
    probeSidecarMock.mockResolvedValue({
      healthy: true,
      probed: true,
      detail: null,
    });
    resumeViaSidecarMock.mockResolvedValue(undefined as never);

    await runResume("m1", "continue", "");

    expect(resumeViaSidecarMock).toHaveBeenCalledTimes(1);
    expect(usePausedTurnStore.getState().pending).toHaveLength(0);
    expect(useConversationStore.getState().byId.c1?.error).toBeNull();
  });

  it("无冷卡 + isGenerating → 仍拦截（抛错 + 横幅）", async () => {
    usePausedTurnStore.setState({ pending: [] });
    useConversationStore.getState().setGenerating(true, "c1");
    resolveSidecarRootMock.mockResolvedValue(TARGET);

    await expect(runResume("m1", "continue", "")).rejects.toThrow(
      /still generating/,
    );

    expect(resumeViaSidecarMock).not.toHaveBeenCalled();
    expect(resumeConversationMock).not.toHaveBeenCalled();
    expect(useConversationStore.getState().byId.c1?.error).toContain(
      "仍在生成中",
    );
  });
});
