import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  type InteractionEntry,
  applyInteractionWireEvent,
  entryToCheckpoint,
  entryToNonBlockingAsk,
  entryToPlanReview,
  hydrateInteractionsFromJournal,
  isAwaitingUserEntry,
  messageCheckpoints,
  messageNonBlockingAsks,
  messagePlanReviews,
  useInteractionStore,
} from "../interactions";

const store = () => useInteractionStore.getState();

beforeEach(() => {
  store().clear();
});

describe("InteractionStore", () => {
  it("upserts required payloads for all hot/cold kinds", () => {
    store().upsertRequired({
      kind: "approval",
      conversationId: "c1",
      messageId: "m1",
      payload: {
        approval_id: "a1",
        tool_name: "file_write",
        arguments: {},
      },
    });
    store().upsertRequired({
      kind: "ask_user",
      conversationId: "c1",
      messageId: "m1",
      payload: { checkpoint_id: "cp1", question: "继续吗？" },
    });
    expect(store().get("a1")?.status).toBe("pending");
    expect(store().get("cp1")?.kind).toBe("ask_user");
    expect(store().listPending("c1")).toHaveLength(2);
  });

  it("ignores duplicate required for an already-resolved id", () => {
    store().upsertRequired({
      kind: "approval",
      conversationId: "c1",
      messageId: "m1",
      payload: { approval_id: "a1", tool_name: "x", arguments: {} },
    });
    store().markResolved({ kind: "approval", id: "a1" });
    store().upsertRequired({
      kind: "approval",
      conversationId: "c1",
      messageId: "m1",
      payload: { approval_id: "a1", tool_name: "y", arguments: {} },
    });
    expect(store().get("a1")?.status).toBe("resolved");
    expect(
      (store().get("a1")?.payload as { tool_name?: string }).tool_name,
    ).toBe("x");
  });

  it("orphaned-before-required builds terminal stub; required cannot resurrect pending", () => {
    applyInteractionWireEvent(
      "interaction_orphaned",
      { interaction_id: "sc1", kind: "stage_card" },
      "c1",
      "m1",
    );
    expect(store().get("sc1")?.status).toBe("orphaned");
    expect(store().get("sc1")?.kind).toBe("stage_card");
    applyInteractionWireEvent(
      "stage_card_required",
      {
        stage_card_id: "sc1",
        motion: "是否开辩",
        sides: [],
        form: "debate",
      },
      "c1",
      "m1",
    );
    expect(store().get("sc1")?.status).toBe("orphaned");
  });

  it("beginSubmit / reopen / markOrphaned lifecycle", () => {
    store().upsertRequired({
      kind: "escalation",
      conversationId: "c1",
      messageId: "m1",
      payload: { escalation_id: "e1", question: "q", assumption: "a" },
    });
    expect(store().beginSubmit("e1")).toBe(true);
    expect(store().get("e1")?.status).toBe("submitting");
    expect(store().beginSubmit("e1")).toBe(false);
    store().reopen("e1");
    expect(store().get("e1")?.status).toBe("pending");
    store().markOrphaned("e1");
    expect(store().get("e1")?.status).toBe("orphaned");
  });

  it("orphanConversation flips only hot pending cards", () => {
    store().upsertRequired({
      kind: "approval",
      conversationId: "c1",
      messageId: "m1",
      payload: { approval_id: "a1", tool_name: "x", arguments: {} },
    });
    store().upsertRequired({
      kind: "ask_user",
      conversationId: "c1",
      messageId: "m1",
      payload: { checkpoint_id: "cp1", question: "q" },
    });
    store().upsertRequired({
      kind: "approval",
      conversationId: "c2",
      messageId: "m2",
      payload: { approval_id: "a2", tool_name: "x", arguments: {} },
    });
    store().orphanConversation("c1", true);
    expect(store().get("a1")?.status).toBe("orphaned");
    expect(store().get("cp1")?.status).toBe("pending");
    expect(store().get("a2")?.status).toBe("pending");
  });

  it("hydratePending replaces pending set for a conversation", () => {
    store().upsertRequired({
      kind: "approval",
      conversationId: "c1",
      messageId: "m1",
      payload: { approval_id: "old", tool_name: "x", arguments: {} },
    });
    store().hydratePending("c1", [
      {
        kind: "delegation_authorization",
        id: "d1",
        messageId: "m9",
        payload: {
          authorization_id: "d1",
          execution_id: "ex1",
          workers: [],
          tools: ["file_write"],
        },
      },
    ]);
    expect(store().get("old")).toBeUndefined();
    expect(store().get("d1")?.status).toBe("pending");
    expect(store().get("d1")?.kind).toBe("delegation_authorization");
  });

  it("empty hydratePending keeps live pending (early empty recovery race)", () => {
    store().upsertRequired({
      kind: "approval",
      conversationId: "c1",
      messageId: "m1",
      payload: { approval_id: "a1", tool_name: "host_shell", arguments: {} },
    });
    store().hydratePending("c1", [], { liveRunning: true });
    expect(store().get("a1")?.status).toBe("pending");
    expect(store().listPending("c1")).toHaveLength(1);
  });

  it("empty hydratePending clears when turn is not live (resolved/orphan)", () => {
    store().upsertRequired({
      kind: "approval",
      conversationId: "c1",
      messageId: "m1",
      payload: { approval_id: "a1", tool_name: "file_write", arguments: {} },
    });
    store().hydratePending("c1", [], { liveRunning: false });
    expect(store().get("a1")).toBeUndefined();
    expect(store().listPending("c1")).toHaveLength(0);
  });

  it("empty hydratePending without liveRunning flag clears (terminal default)", () => {
    store().upsertRequired({
      kind: "approval",
      conversationId: "c1",
      messageId: "m1",
      payload: { approval_id: "a1", tool_name: "x", arguments: {} },
    });
    store().hydratePending("c1", []);
    expect(store().get("a1")).toBeUndefined();
  });

  it("non-empty hydratePending replaces even while live", () => {
    store().upsertRequired({
      kind: "approval",
      conversationId: "c1",
      messageId: "m1",
      payload: { approval_id: "old", tool_name: "x", arguments: {} },
    });
    store().hydratePending(
      "c1",
      [
        {
          kind: "approval",
          id: "new",
          messageId: "m1",
          payload: { approval_id: "new", tool_name: "y", arguments: {} },
        },
      ],
      { liveRunning: true },
    );
    expect(store().get("old")).toBeUndefined();
    expect(store().get("new")?.status).toBe("pending");
  });

  it("applyInteractionWireEvent handles orphaned + required + resolved", () => {
    applyInteractionWireEvent(
      "approval_required",
      {
        approval_id: "a1",
        conversation_id: "c1",
        tool_call_id: "t1",
        tool_name: "file_write",
        arguments: {},
      },
      "c1",
      "m1",
    );
    expect(store().get("a1")?.status).toBe("pending");
    applyInteractionWireEvent(
      "approval_resolved",
      { approval_id: "a1", decision: "approve" },
      "c1",
      "m1",
    );
    expect(store().get("a1")?.status).toBe("resolved");

    applyInteractionWireEvent(
      "escalation_required",
      { escalation_id: "e1", question: "q", assumption: "a" },
      "c1",
      "m1",
    );
    applyInteractionWireEvent(
      "interaction_orphaned",
      { interaction_id: "e1", kind: "escalation" },
      "c1",
      "m1",
    );
    expect(store().get("e1")?.status).toBe("orphaned");
  });
});

describe("isAwaitingUserEntry (侧栏「等你」灯判定)", () => {
  const entry = (over: Partial<InteractionEntry>): InteractionEntry => ({
    id: "x1",
    kind: "approval",
    status: "pending",
    conversationId: "c1",
    messageId: "m1",
    payload: {},
    ...over,
  });

  it("counts hot blocking kinds while pending / submitting", () => {
    expect(isAwaitingUserEntry(entry({ kind: "approval" }))).toBe(true);
    expect(
      isAwaitingUserEntry(entry({ kind: "approval", status: "submitting" })),
    ).toBe(true);
    expect(
      isAwaitingUserEntry(entry({ kind: "delegation_authorization" })),
    ).toBe(true);
    expect(
      isAwaitingUserEntry(
        entry({ kind: "escalation", payload: { awaiting: "user" } }),
      ),
    ).toBe(true);
    expect(isAwaitingUserEntry(entry({ kind: "escalation" }))).toBe(true);
  });

  it("excludes CEO-arbitrated escalations (user has nothing to do)", () => {
    expect(
      isAwaitingUserEntry(
        entry({ kind: "escalation", payload: { awaiting: "ceo" } }),
      ),
    ).toBe(false);
  });

  it("excludes settled entries", () => {
    expect(isAwaitingUserEntry(entry({ status: "resolved" }))).toBe(false);
    expect(isAwaitingUserEntry(entry({ status: "orphaned" }))).toBe(false);
  });

  it("excludes cold kinds (pausedTurns 帧是权威) and non-blocking asks", () => {
    expect(isAwaitingUserEntry(entry({ kind: "ask_user" }))).toBe(false);
    expect(isAwaitingUserEntry(entry({ kind: "plan_review" }))).toBe(false);
    expect(isAwaitingUserEntry(entry({ kind: "team_preview" }))).toBe(false);
    expect(isAwaitingUserEntry(entry({ kind: "question_posted" }))).toBe(false);
  });
});

describe("escalation_resolved id matching (project frame)", () => {
  it("is covered by InteractionStore markResolved by escalation_id", () => {
    // The project.ts fix matches by f.escalationId; store path uses the same id field.
    applyInteractionWireEvent(
      "escalation_required",
      { escalation_id: "esc-b", question: "B?", assumption: "b" },
      "c1",
      "m1",
    );
    applyInteractionWireEvent(
      "escalation_required",
      { escalation_id: "esc-a", question: "A?", assumption: "a" },
      "c1",
      "m1",
    );
    applyInteractionWireEvent(
      "escalation_resolved",
      { escalation_id: "esc-a", status: "resolved", answer: "yes" },
      "c1",
      "m1",
    );
    expect(store().get("esc-a")?.status).toBe("resolved");
    expect(store().get("esc-b")?.status).toBe("pending");
  });
});

// Journal reload path (replaces retired conversation/projections *FromEvents helpers).
describe("hydrateInteractionsFromJournal (history replay)", () => {
  describe("plan_review", () => {
    it("folds a required→resolved pair into one resolved card", () => {
      hydrateInteractionsFromJournal("a", "m1", [
        {
          type: "plan_review_required",
          payload: {
            checkpoint_id: "c1",
            steps: [{ run_id: "run-1", role: "角色 run-1", summary: "产出" }],
            pending: [{ run_id: "next", role: "下游" }],
          },
        },
        {
          type: "plan_review_resolved",
          payload: { checkpoint_id: "c1", decision: "continue", note: "放行" },
        },
      ]);
      const cards = messagePlanReviews("a", "m1");
      expect(cards).toHaveLength(1);
      expect(cards[0]).toMatchObject({
        id: "c1",
        status: "resolved",
        decision: "continue",
        note: "放行",
      });
      expect(cards[0].steps.map((s) => s.run_id)).toEqual(["run-1"]);
      expect(cards[0].pending.map((p) => p.run_id)).toEqual(["next"]);
    });

    it("keeps an unresolved required as a pending card", () => {
      hydrateInteractionsFromJournal("a", "m1", [
        {
          type: "plan_review_required",
          payload: {
            checkpoint_id: "c1",
            steps: [{ run_id: "run-1", role: "R", summary: "s" }],
            pending: [],
          },
        },
      ]);
      const planEntry = store().get("c1");
      expect(planEntry).toBeDefined();
      if (!planEntry) return;
      expect(entryToPlanReview(planEntry)).toMatchObject({
        status: "pending",
        decision: null,
      });
    });

    it("preserves raise order across multiple checkpoints", () => {
      hydrateInteractionsFromJournal("a", "m1", [
        {
          type: "plan_review_required",
          payload: {
            checkpoint_id: "c1",
            steps: [{ run_id: "run-1", role: "R", summary: "s" }],
            pending: [],
          },
        },
        {
          type: "plan_review_required",
          payload: {
            checkpoint_id: "c2",
            steps: [{ run_id: "run-2", role: "R", summary: "s" }],
            pending: [],
          },
        },
        {
          type: "plan_review_resolved",
          payload: { checkpoint_id: "c1", decision: "stop", note: "" },
        },
      ]);
      const cards = messagePlanReviews("a", "m1");
      expect(cards.map((c) => c.id)).toEqual(["c1", "c2"]);
      expect(cards[0].status).toBe("resolved");
      expect(cards[1].status).toBe("pending");
    });
  });

  describe("ask_user", () => {
    const richPayload = {
      checkpoint_id: "c1",
      question: "我先按这个方案做这个落地页，对吗？",
      assumptions: [{ id: "a0", label: "部署", value: "纯静态" }],
      questions: [
        {
          id: "q0",
          prompt: "主要给谁看？",
          kind: "choice",
          options: [
            { label: "潜在客户", detail: "偏转化导向", recommended: true },
            { label: "投资人" },
          ],
          multiple: false,
          default: "潜在客户",
        },
      ],
      style_options: [{ id: "s0", label: "深色科技" }],
      format_options: [{ id: "f0", label: "PowerPoint（.pptx）" }],
    };

    it("folds a required event into one pending card (rich opening fields)", () => {
      hydrateInteractionsFromJournal("a", "m1", [
        { type: "checkpoint_required", payload: richPayload },
      ]);
      const cards = messageCheckpoints("a", "m1");
      expect(cards).toHaveLength(1);
      const checkpointEntry = store().get("c1");
      expect(checkpointEntry).toBeDefined();
      if (!checkpointEntry) return;
      expect(entryToCheckpoint(checkpointEntry)).toMatchObject({
        id: "c1",
        status: "pending",
        decision: null,
        assumptions: [{ id: "a0", label: "部署", value: "纯静态" }],
        styleOptions: [{ id: "s0", label: "深色科技" }],
        formatOptions: [{ id: "f0", label: "PowerPoint（.pptx）" }],
      });
      expect(cards[0].questions[0].default).toBe("潜在客户");
    });

    it("folds a required→resolved pair into one settled card", () => {
      hydrateInteractionsFromJournal("a", "m1", [
        { type: "checkpoint_required", payload: richPayload },
        {
          type: "checkpoint_resolved",
          payload: {
            checkpoint_id: "c1",
            decision: "continue",
            note: "就按这个开做",
            selected: ["潜在客户"],
          },
        },
      ]);
      const cards = messageCheckpoints("a", "m1");
      expect(cards).toHaveLength(1);
      expect(cards[0]).toMatchObject({
        id: "c1",
        status: "resolved",
        decision: "continue",
        note: "就按这个开做",
        selected: ["潜在客户"],
      });
    });

    it("preserves raise order across multiple checkpoints", () => {
      hydrateInteractionsFromJournal("a", "m1", [
        {
          type: "checkpoint_required",
          payload: { checkpoint_id: "c1", question: "q1" },
        },
        {
          type: "checkpoint_required",
          payload: { checkpoint_id: "c2", question: "q2" },
        },
        {
          type: "checkpoint_resolved",
          payload: { checkpoint_id: "c1", decision: "stop", note: "" },
        },
      ]);
      const cards = messageCheckpoints("a", "m1");
      expect(cards.map((c) => c.id)).toEqual(["c1", "c2"]);
      expect(cards[0].status).toBe("resolved");
      expect(cards[1].status).toBe("pending");
    });

    it("is empty when the journal has no checkpoint", () => {
      hydrateInteractionsFromJournal("a", "m1", []);
      expect(messageCheckpoints("a", "m1")).toEqual([]);
    });
  });

  describe("question_posted", () => {
    const postedPayload = {
      ask_id: "n1",
      question: "我先按响应式单页做，可以吗？",
      assumptions: [{ id: "a0", label: "部署", value: "纯静态" }],
      questions: [
        {
          id: "q0",
          prompt: "要不要双语？",
          kind: "choice",
          options: [{ label: "要" }, { label: "不要" }],
          multiple: false,
          default: "不要",
        },
      ],
      style_options: [],
    };

    it("folds a question_posted event into one card (rich fields)", () => {
      hydrateInteractionsFromJournal("a", "m1", [
        { type: "question_posted", payload: postedPayload },
      ]);
      const cards = messageNonBlockingAsks("a", "m1");
      expect(cards).toHaveLength(1);
      expect(cards[0]).toMatchObject({
        id: "n1",
        question: "我先按响应式单页做，可以吗？",
        assumptions: [{ id: "a0", label: "部署", value: "纯静态" }],
      });
      expect(cards[0].questions[0].default).toBe("不要");
      const askEntry = store().get("n1");
      expect(askEntry).toBeDefined();
      if (!askEntry) return;
      expect(entryToNonBlockingAsk(askEntry).id).toBe("n1");
    });

    it("dedupes a re-delivered event and preserves post order", () => {
      hydrateInteractionsFromJournal("a", "m1", [
        { type: "question_posted", payload: postedPayload },
        {
          type: "question_posted",
          payload: { ...postedPayload, ask_id: "n2", question: "q2" },
        },
        { type: "question_posted", payload: postedPayload },
      ]);
      expect(messageNonBlockingAsks("a", "m1").map((c) => c.id)).toEqual([
        "n1",
        "n2",
      ]);
    });

    it("is empty when the journal has no non-blocking ask", () => {
      hydrateInteractionsFromJournal("a", "m1", []);
      expect(messageNonBlockingAsks("a", "m1")).toEqual([]);
    });
  });
});

// silence unused vi in case of future mocks
void vi;
