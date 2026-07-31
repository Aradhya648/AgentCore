import { useConversationStore } from "@/stores/conversation";
import { useInteractionStore } from "@/stores/interactions";
import { usePausedTurnStore } from "@/stores/pausedTurns";
import { beforeEach, describe, expect, it } from "vitest";
import {
  type BackendMessage,
  shouldSetGeneratingOnHydrate,
  toMessage,
} from "../messages";

/** Minimal persisted row — enough for `toMessage` hydrate assertions. */
function row(
  over: Partial<BackendMessage> & Pick<BackendMessage, "id" | "role">,
): BackendMessage {
  return {
    conversation_id: "c1",
    content: "hello",
    reasoning_content: null,
    created_at: "2026-01-01T00:00:00Z",
    ...over,
  };
}

beforeEach(() => {
  usePausedTurnStore.getState().clear();
  useInteractionStore.getState().clear();
  useConversationStore.setState({ currentConversationId: null, byId: {} });
});

describe("toMessage (reload hydrate)", () => {
  it("stamps serverMessageId = row id on assistant so resume guards match live", () => {
    const msg = toMessage(
      row({ id: "srv-msg-1", role: "assistant", content: "ok" }),
    );

    expect(msg.id).toBe("srv-msg-1");
    expect(msg.role).toBe("assistant");
    expect(msg.serverMessageId).toBe("srv-msg-1");
  });

  it("does not stamp serverMessageId on user rows", () => {
    const msg = toMessage(
      row({ id: "srv-user-1", role: "user", content: "hi" }),
    );

    expect(msg.id).toBe("srv-user-1");
    expect(msg.role).toBe("user");
    expect(msg.serverMessageId).toBeUndefined();
  });

  it("maps status=running (no paused) to isStreaming for overlay partial", () => {
    const msg = toMessage(
      row({
        id: "m-live",
        role: "assistant",
        content: "partial…",
        status: "running",
      }),
    );
    expect(msg.isStreaming).toBe(true);
    expect(msg.finishReason).toBeUndefined();
    expect(shouldSetGeneratingOnHydrate([msg])).toBe(true);
  });

  it("maps status=running + paused to non-streaming finishReason=paused", () => {
    // Write latch keeps status=running; read lifts paused so reopen is not「仍在生成」.
    const msg = toMessage(
      row({
        id: "m-paused",
        role: "assistant",
        content: "checkpoint body",
        status: "running",
        paused: true,
      }),
    );
    expect(msg.isStreaming).toBe(false);
    expect(msg.finishReason).toBe("paused");
    expect(msg.status).toBe("running");
    expect(shouldSetGeneratingOnHydrate([msg])).toBe(false);
  });

  it("does not set generating chrome when last message is cold-paused", () => {
    const live = toMessage(
      row({ id: "m1", role: "user", content: "q", status: null }),
    );
    const paused = toMessage(
      row({
        id: "m2",
        role: "assistant",
        content: "a",
        status: "running",
        paused: true,
      }),
    );
    expect(shouldSetGeneratingOnHydrate([live, paused])).toBe(false);
  });

  it("surfaces pausedTurns when paused + journal cold interaction (hydrate gap)", () => {
    // Offline repro: hydrateInteractionsFromJournal alone left ResumePrompt empty.
    toMessage(
      row({
        id: "m-paused",
        role: "assistant",
        content: "checkpoint body",
        status: "running",
        paused: true,
        runs: {
          events: [
            {
              type: "plan_review_required",
              payload: {
                checkpoint_id: "pr-hydrate",
                conversation_id: "c1",
                steps: [{ run_id: "r1", role: "调研", summary: "方案就绪" }],
                pending: [{ run_id: "r2", role: "执行" }],
                ceo_review: {
                  conclusion: "方案可行，建议放行。",
                  risks: ["回滚预案缺失"],
                  suggestions: ["先灰度"],
                },
              },
            },
          ],
          finish_reason: "paused",
        } as NonNullable<BackendMessage["runs"]>,
      }),
    );

    const pending = usePausedTurnStore.getState().pending;
    expect(pending).toHaveLength(1);
    expect(pending[0]).toMatchObject({
      messageId: "m-paused",
      conversationId: "c1",
      checkpointId: "pr-hydrate",
      kind: "plan_review",
      origin: "server",
    });
    expect(pending[0].steps).toEqual([
      { run_id: "r1", role: "调研", summary: "方案就绪" },
    ]);
    // journal 冷加载同样带出把关摘要（拍板中心冷启动可见）。
    expect(pending[0].ceoReview).toEqual({
      conclusion: "方案可行，建议放行。",
      risks: ["回滚预案缺失"],
      suggestions: ["先灰度"],
    });
  });

  it("surface 画卡后清会话 isGenerating（冷挂起不变量）", () => {
    useConversationStore.getState().switchConversation("c1");
    useConversationStore.getState().addMessage(
      {
        id: "u1",
        role: "user",
        content: "q",
        createdAt: "2026-01-01T00:00:00Z",
        executionId: null,
        isStreaming: false,
      },
      "c1",
    );
    useConversationStore.getState().addMessage(
      {
        id: "m-paused",
        role: "assistant",
        content: "partial",
        createdAt: "2026-01-01T00:00:01Z",
        executionId: null,
        isStreaming: true,
        status: "running",
        serverMessageId: "m-paused",
      },
      "c1",
    );
    useConversationStore.getState().setGenerating(true, "c1");

    toMessage(
      row({
        id: "m-paused",
        role: "assistant",
        content: "checkpoint body",
        status: "running",
        paused: true,
        runs: {
          events: [
            {
              type: "checkpoint_required",
              payload: {
                checkpoint_id: "ask-h",
                conversation_id: "c1",
                question: "选哪个？",
                context: "",
                assumptions: [],
                questions: [],
                style_options: [],
              },
            },
          ],
          finish_reason: "paused",
        } as NonNullable<BackendMessage["runs"]>,
      }),
    );

    expect(usePausedTurnStore.getState().pending).toHaveLength(1);
    expect(usePausedTurnStore.getState().pending[0]?.kind).toBe("ask_user");
    expect(useConversationStore.getState().byId.c1?.isGenerating).toBe(false);
    expect(
      useConversationStore
        .getState()
        .byId.c1?.messages.find((m) => m.id === "m-paused")?.isStreaming,
    ).toBe(false);
  });

  it("journal cold interaction without ceo_review hydrates with no summary", () => {
    toMessage(
      row({
        id: "m-paused-no-cr",
        role: "assistant",
        content: "checkpoint body",
        status: "running",
        paused: true,
        runs: {
          events: [
            {
              type: "plan_review_required",
              payload: {
                checkpoint_id: "pr-no-cr",
                conversation_id: "c1",
                steps: [{ run_id: "r1", role: "调研", summary: "ok" }],
                pending: [],
              },
            },
          ],
          finish_reason: "paused",
        } as NonNullable<BackendMessage["runs"]>,
      }),
    );

    const pending = usePausedTurnStore.getState().pending;
    expect(pending).toHaveLength(1);
    expect(pending[0].ceoReview).toBeUndefined();
  });

  it("does not surface pausedTurns when paused without journal interactions", () => {
    toMessage(
      row({
        id: "m-paused-bare",
        role: "assistant",
        content: "a",
        status: "running",
        paused: true,
      }),
    );
    expect(usePausedTurnStore.getState().pending).toHaveLength(0);
  });
});
