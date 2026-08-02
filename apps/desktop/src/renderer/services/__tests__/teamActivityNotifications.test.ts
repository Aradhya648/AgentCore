// @vitest-environment jsdom
import { getConversations } from "@/hooks/useConversations";
import { notifyInfo } from "@/lib/toast";
import { startTeamActivityNotifications } from "@/services/teamActivityNotifications";
import { useConversationStore } from "@/stores/conversation";
import { useInteractionStore } from "@/stores/interactions";
import { type PendingResume, usePausedTurnStore } from "@/stores/pausedTurns";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/hooks/useConversations", () => ({
  getConversations: vi.fn(() => []),
}));
vi.mock("@/lib/toast", () => ({
  notifyInfo: vi.fn(),
}));
vi.mock("@/lib/nativeNotification", () => ({
  showNativeNotification: vi.fn(() => Promise.resolve()),
}));

const getConversationsMock = vi.mocked(getConversations);
const notifyInfoMock = vi.mocked(notifyInfo);

const CID = "conv-away";
const OTHER = "conv-other";

function resume(
  over: Partial<PendingResume> & Pick<PendingResume, "kind" | "checkpointId">,
): PendingResume {
  return {
    messageId: "msg-1",
    conversationId: CID,
    userMessage: "hi",
    userMessageId: "u1",
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
    question: "",
    context: "",
    assumptions: [],
    questions: [],
    intent: "decision",
    origin: "server",
    ...over,
  };
}

function seedTitle(id: string, title: string): void {
  getConversationsMock.mockReturnValue([
    {
      id,
      title,
      updatedAt: "2020-01-01T00:00:00.000Z",
      messageCount: 0,
      lastMessagePreview: null,
    },
  ]);
}

function setGenerating(id: string, generating: boolean): void {
  useConversationStore.setState((s) => ({
    byId: {
      ...s.byId,
      [id]: {
        ...(s.byId[id] ?? {
          messages: [],
          memoryUpdates: [],
          abort: null,
          error: null,
          retry: null,
          errorAction: null,
          messageFocus: null,
          hasMoreBefore: false,
          hasMoreAfter: false,
          loadingOlder: false,
          loadingNewer: false,
          pendingTurnWarning: null,
        }),
        isGenerating: generating,
      },
    },
  }));
}

describe("startTeamActivityNotifications", () => {
  let stop: () => void;

  beforeEach(() => {
    notifyInfoMock.mockReset();
    getConversationsMock.mockReset();
    getConversationsMock.mockReturnValue([]);
    useConversationStore.setState({ currentConversationId: OTHER, byId: {} });
    usePausedTurnStore.getState().clear();
    useInteractionStore.getState().clear();
    window.location.hash = `#/conversations/${OTHER}`;
    stop = startTeamActivityNotifications();
  });

  afterEach(() => {
    stop();
    usePausedTurnStore.getState().clear();
    useInteractionStore.getState().clear();
    useConversationStore.setState({ currentConversationId: null, byId: {} });
  });

  it("paused 收口不弹已完成（isGenerating↓ 时已有 pausedTurns）", async () => {
    seedTitle(CID, "团队辩论");
    setGenerating(CID, true);
    // Same sync turn as finalizeLastMessage → surfaceResumeFromLiveTurn:
    // pause frame lands before the completion microtask.
    usePausedTurnStore
      .getState()
      .addLiveResume(resume({ kind: "plan_review", checkpointId: "cp-pr" }));
    setGenerating(CID, false);

    await Promise.resolve(); // flush queueMicrotask
    await Promise.resolve();

    const messages = notifyInfoMock.mock.calls.map((c) => String(c[0]));
    expect(messages.some((m) => m.includes("已完成"))).toBe(false);
    expect(messages).toContain("「团队辩论」等待你确认后才会继续");
  });

  it("普通收口仍弹已完成", async () => {
    seedTitle(CID, "调研");
    setGenerating(CID, true);
    setGenerating(CID, false);

    await Promise.resolve();
    await Promise.resolve();

    expect(notifyInfoMock).toHaveBeenCalledWith(
      "「调研」已完成",
      expect.any(Object),
    );
  });

  it("挂起 ask_user / plan_review 弹等待你确认后才会继续", () => {
    seedTitle(CID, "拍板会话");
    usePausedTurnStore
      .getState()
      .addLiveResume(resume({ kind: "ask_user", checkpointId: "cp-ask" }));
    expect(notifyInfoMock).toHaveBeenCalledWith(
      "「拍板会话」等待你确认后才会继续",
      expect.any(Object),
    );

    notifyInfoMock.mockClear();
    usePausedTurnStore
      .getState()
      .addLiveResume(resume({ kind: "plan_review", checkpointId: "cp-pr2" }));
    expect(notifyInfoMock).toHaveBeenCalledWith(
      "「拍板会话」等待你确认后才会继续",
      expect.any(Object),
    );
  });

  it("team_preview 挂起弹等待你确认后才会开工（且不与已完成双弹）", async () => {
    seedTitle(CID, "开工");
    setGenerating(CID, true);
    usePausedTurnStore
      .getState()
      .addLiveResume(resume({ kind: "team_preview", checkpointId: "cp-tp" }));
    setGenerating(CID, false);

    await Promise.resolve();
    await Promise.resolve();

    const messages = notifyInfoMock.mock.calls.map((c) => String(c[0]));
    expect(messages).toContain("「开工」等待你确认后才会开工");
    expect(messages.some((m) => m.includes("已完成"))).toBe(false);
  });

  it("幕终 pending stage_card 不弹已完成，弹需要你确认推进", async () => {
    seedTitle(CID, "调研收口");
    setGenerating(CID, true);
    useInteractionStore.getState().upsertRequired({
      kind: "stage_card",
      conversationId: CID,
      messageId: "msg-sc",
      payload: {
        stage_card_id: "sc-1",
        motion: "命题",
        form: "debate",
      },
    });
    setGenerating(CID, false);

    await Promise.resolve();
    await Promise.resolve();

    const messages = notifyInfoMock.mock.calls.map((c) => String(c[0]));
    expect(messages).toContain("「调研收口」需要你确认推进");
    expect(messages.some((m) => m.includes("已完成"))).toBe(false);
  });

  it("同 checkpoint 不重复弹（seed + dedup）", () => {
    seedTitle(CID, "开工");
    // Seed before subscribe would happen — restart notifier with pending already there
    stop();
    usePausedTurnStore
      .getState()
      .addLiveResume(resume({ kind: "team_preview", checkpointId: "cp-seed" }));
    stop = startTeamActivityNotifications();
    notifyInfoMock.mockClear();

    // Re-add same checkpoint (idempotent replace) — must not re-toast
    usePausedTurnStore
      .getState()
      .addLiveResume(resume({ kind: "team_preview", checkpointId: "cp-seed" }));
    expect(notifyInfoMock).not.toHaveBeenCalled();
  });
});
