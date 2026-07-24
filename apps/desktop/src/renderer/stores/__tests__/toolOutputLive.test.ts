import type { ToolUseProgressPayload } from "@/types/events";
import { beforeEach, describe, expect, it } from "vitest";
import { progressOutputChunk, useToolOutputLiveStore } from "../toolOutputLive";

const store = () => useToolOutputLiveStore.getState();

beforeEach(() => {
  useToolOutputLiveStore.setState({ byId: {}, selectedId: null });
});

describe("progressOutputChunk", () => {
  it("extracts stream/chunk only for phase=output", () => {
    expect(
      progressOutputChunk({
        tool_call_id: "t1",
        tool_name: "code_execute",
        phase: "executing",
      }),
    ).toBeNull();

    const payload = {
      tool_call_id: "t1",
      tool_name: "code_execute",
      phase: "output",
      stream: "stdout",
      chunk: "hi\n",
    } as ToolUseProgressPayload & { stream: string; chunk: string };
    expect(progressOutputChunk(payload)).toEqual({
      stream: "stdout",
      chunk: "hi\n",
    });
  });
});

describe("toolOutputLive store", () => {
  it("seeds and appends stripped chunks by stream", () => {
    store().seed({
      toolCallId: "t1",
      toolName: "code_execute",
      conversationId: "c1",
    });
    store().appendProgress(
      {
        tool_call_id: "t1",
        tool_name: "code_execute",
        phase: "output",
        stream: "stdout",
        chunk: "\u001b[32mok\u001b[0m\n",
      } as ToolUseProgressPayload,
      "c1",
    );
    store().appendProgress(
      {
        tool_call_id: "t1",
        tool_name: "code_execute",
        phase: "output",
        stream: "stderr",
        chunk: "warn\n",
      } as ToolUseProgressPayload,
      "c1",
    );
    const e = store().entry("t1");
    expect(e?.stdout).toBe("ok\n");
    expect(e?.stderr).toBe("warn\n");
  });

  it("markEnded freezes endedAt without dropping buffer", () => {
    store().seed({
      toolCallId: "t1",
      toolName: "code_execute",
      conversationId: "c1",
    });
    store().markEnded("t1");
    expect(store().entry("t1")?.endedAt).toBeTruthy();
    store().markEnded("t1"); // idempotent
    expect(store().entry("t1")?.stdout).toBe("");
  });

  it("clearConversation drops only that conversation's buffers", () => {
    store().seed({
      toolCallId: "t1",
      toolName: "code_execute",
      conversationId: "c1",
    });
    store().seed({
      toolCallId: "t2",
      toolName: "test_run",
      conversationId: "c2",
    });
    store().select("t1");
    store().clearConversation("c1");
    expect(store().entry("t1")).toBeNull();
    expect(store().entry("t2")).not.toBeNull();
    expect(store().selectedId).toBeNull();
  });
});
