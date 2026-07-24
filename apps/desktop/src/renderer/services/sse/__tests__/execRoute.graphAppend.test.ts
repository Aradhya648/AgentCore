import { useConversationStore } from "@/stores/conversation";
import { enterTurnStreaming } from "@/stores/conversation/turnPhaseActions";
import { useExecutionStore } from "@/stores/execution";
import { beforeEach, describe, expect, it } from "vitest";
import { dispatchSSEEvent } from "../dispatch";
import {
  clearAllGraphAppendRedirects,
  execMessageId,
  noteGraphAppendRedirect,
} from "../helpers";

const CONV = "conv-graph-append-route";

function seedAssistant(id: string, extras: Record<string, unknown> = {}) {
  useConversationStore.getState().addMessage(
    {
      id,
      role: "assistant",
      content: "",
      createdAt: new Date().toISOString(),
      executionId: null,
      isStreaming: true,
      serverMessageId: id,
      ...extras,
    },
    CONV,
  );
}

beforeEach(() => {
  clearAllGraphAppendRedirects();
  useConversationStore.getState().dropConversationRuntime(CONV);
  useExecutionStore.setState({ byId: {} });
  useConversationStore.getState().switchConversation(CONV);
  enterTurnStreaming(CONV);
});

describe("execMessageId graph-append routing", () => {
  it("routes host_message_id hint to the host slot", () => {
    seedAssistant("m1", { executionId: "exec1" });
    seedAssistant("m2");
    expect(
      execMessageId(CONV, { host_message_id: "m1", execution_id: "exec1" }),
    ).toBe("m1");
  });

  it("sticky divert sends growth frames to host after graph_append", () => {
    seedAssistant("m1", { executionId: "exec1" });
    seedAssistant("m2");
    noteGraphAppendRedirect(CONV, "m1");
    expect(execMessageId(CONV)).toBe("m1");
  });

  it("live replay: append run_plan + run frames land on host; m2 only gets anchor", () => {
    // Turn 1 — build graph on m1
    dispatchSSEEvent(
      {
        type: "message_start",
        payload: { message_id: "m1", conversation_id: CONV },
        timestamp: "",
      },
      { conversationId: CONV, source: "server" },
    );
    dispatchSSEEvent(
      {
        type: "run_plan",
        payload: {
          execution_id: "exec1",
          plan_type: "multi_agent",
          task_summary: "调研",
          agents: [
            {
              id: "w1",
              role: "研究员",
              thinking: true,
            },
          ],
          runs: [{ id: "r1", agent_id: "w1", task: "调研", depends_on: [] }],
        },
        timestamp: "",
      },
      { conversationId: CONV, source: "server" },
    );
    dispatchSSEEvent(
      {
        type: "run_started",
        payload: {
          run_id: "r1",
          agent_id: "w1",
          parent_run_id: null,
          kind: "agent",
        },
        timestamp: "",
      },
      { conversationId: CONV, source: "server" },
    );
    dispatchSSEEvent(
      {
        type: "run_completed",
        payload: {
          run_id: "r1",
          agent_id: "w1",
          output_summary: "done",
          duration_ms: 10,
        },
        timestamp: "",
      },
      { conversationId: CONV, source: "server" },
    );
    dispatchSSEEvent(
      {
        type: "message_end",
        payload: { finish_reason: "end_turn" },
        timestamp: "",
      },
      { conversationId: CONV, source: "server" },
    );

    expect(useExecutionStore.getState().byId.m1?.status).toBe("completed");
    // 新开一轮（生产路径会 beginTurnPreflight→streaming；测试直接拨相）。
    useConversationStore.getState().setTurnPhase("streaming", CONV);

    // Turn 2 — append
    dispatchSSEEvent(
      {
        type: "message_start",
        payload: { message_id: "m2", conversation_id: CONV },
        timestamp: "",
      },
      { conversationId: CONV, source: "server" },
    );
    dispatchSSEEvent(
      {
        type: "graph_append",
        payload: {
          execution_id: "exec1",
          host_message_id: "m1",
          append_message_id: "m2",
          added_count: 1,
          roles: ["撰写员"],
          added_run_ids: ["r3"],
        },
        timestamp: "",
      },
      { conversationId: CONV, source: "server" },
    );

    const m2 = useConversationStore
      .getState()
      .byId[CONV].messages.find((m) => m.serverMessageId === "m2");
    expect(m2?.process?.some((s) => s.kind === "graph_append")).toBe(true);
    expect(m2?.process?.some((s) => s.kind === "team")).toBeFalsy();

    dispatchSSEEvent(
      {
        type: "run_plan",
        payload: {
          execution_id: "exec1",
          plan_type: "multi_agent",
          task_summary: "调研撰写",
          host_message_id: "m1",
          agents: [
            {
              id: "w1",
              role: "研究员",
              thinking: true,
            },
            {
              id: "w3",
              role: "撰写员",
              thinking: true,
            },
          ],
          runs: [
            { id: "r1", agent_id: "w1", task: "调研", depends_on: [] },
            { id: "r3", agent_id: "w3", task: "撰写", depends_on: [] },
          ],
        },
        timestamp: "",
      },
      { conversationId: CONV, source: "server" },
    );

    expect(useExecutionStore.getState().byId.m1?.status).toBe("running");
    expect(useExecutionStore.getState().byId.m2?.plan).toBeFalsy();

    dispatchSSEEvent(
      {
        type: "run_started",
        payload: {
          run_id: "r3",
          agent_id: "w3",
          parent_run_id: null,
          kind: "agent",
        },
        timestamp: "",
      },
      { conversationId: CONV, source: "server" },
    );
    dispatchSSEEvent(
      {
        type: "run_completed",
        payload: {
          run_id: "r3",
          agent_id: "w3",
          output_summary: "写完",
          duration_ms: 10,
        },
        timestamp: "",
      },
      { conversationId: CONV, source: "server" },
    );

    // Host settles by run terminals, not m2 message_end.
    expect(useExecutionStore.getState().byId.m1?.status).toBe("completed");

    dispatchSSEEvent(
      {
        type: "message_end",
        payload: { finish_reason: "end_turn" },
        timestamp: "",
      },
      { conversationId: CONV, source: "server" },
    );
    expect(useExecutionStore.getState().byId.m1?.status).toBe("completed");
    expect(useExecutionStore.getState().byId.m2?.plan).toBeFalsy();
  });
});
