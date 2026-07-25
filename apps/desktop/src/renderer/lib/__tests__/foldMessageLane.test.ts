import {
  ensureTimelineMarkersFromJournal,
  foldCheckpointMarker,
  foldContentDelta,
  foldContentReset,
  foldReasoningDelta,
  foldTeamMarker,
  foldToolUseEnd,
  foldToolUsePhase,
  foldToolUseStart,
  messageLaneFromMessage,
} from "@/lib/foldMessageLane";
import type {
  ToolUseEndPayload,
  ToolUseProgressPayload,
  ToolUseStartPayload,
} from "@/types/events";
import { describe, expect, it } from "vitest";

const startPayload = (
  over: Partial<ToolUseStartPayload> = {},
): ToolUseStartPayload => ({
  tool_call_id: "call_1",
  tool_name: "web_search",
  arguments: { query: "深圳天气" },
  ...over,
});

describe("foldMessageLane", () => {
  it("foldContentDelta appends content and process step", () => {
    const base = messageLaneFromMessage({ content: "hi" });
    const next = foldContentDelta(base, " there");
    expect(next.content).toBe("hi there");
    expect(next.process).toEqual([{ kind: "content", text: " there" }]);
  });

  it("foldContentReset(finish_guard) clears content and leaves the rework chip", () => {
    const base = messageLaneFromMessage({
      content: "bad draft",
      process: [
        { kind: "reasoning", text: "think" },
        { kind: "content", text: "bad draft" },
      ],
    });
    const next = foldContentReset(base, "finish_guard");
    expect(next.content).toBe("");
    expect(next.process).toEqual([
      { kind: "reasoning", text: "think" },
      { kind: "rework" },
    ]);
  });

  // 非 finish_guard（LLM 透明重试等）：清正文照旧、不折 rework chip（误报根治）。
  it("foldContentReset(retry) clears content without a rework chip", () => {
    const base = messageLaneFromMessage({
      content: "transient",
      process: [
        { kind: "reasoning", text: "think" },
        { kind: "content", text: "transient" },
      ],
    });
    const next = foldContentReset(base, "retry");
    expect(next.content).toBe("");
    expect(next.process).toEqual([{ kind: "reasoning", text: "think" }]);
  });

  it("foldReasoningDelta appends reasoning lane", () => {
    const base = messageLaneFromMessage({ content: "" });
    const next = foldReasoningDelta(base, "hmm");
    expect(next.reasoning).toBe("hmm");
    expect(next.process).toEqual([{ kind: "reasoning", text: "hmm" }]);
  });

  // 工具执行阶段进度 (联网搜索前端展示优化)
  it("foldToolUsePhase stamps a running tool step's phase", () => {
    const started = foldToolUseStart(
      messageLaneFromMessage({ content: "" }),
      startPayload(),
    );
    const next = foldToolUsePhase(started, {
      tool_call_id: "call_1",
      tool_name: "web_search",
      phase: "querying",
    } satisfies ToolUseProgressPayload);
    const step = next.process[0];
    expect(step.kind === "tool" && step.phase).toBe("querying");
  });

  it("foldToolUsePhase no-ops after the tool has ended (not running)", () => {
    const started = foldToolUseStart(
      messageLaneFromMessage({ content: "" }),
      startPayload(),
    );
    const ended = foldToolUseEnd(started, {
      tool_call_id: "call_1",
      tool_name: "web_search",
      result: "ok",
      status: "success",
    } as ToolUseEndPayload);
    const after = foldToolUsePhase(ended, {
      tool_call_id: "call_1",
      tool_name: "web_search",
      phase: "querying",
    } satisfies ToolUseProgressPayload);
    // Same reference (no-op) and no phase leaked onto the resolved step.
    expect(after).toBe(ended);
    const step = after.process[0];
    expect(step.kind === "tool" && step.phase).toBeUndefined();
  });

  it("foldToolUsePhase no-ops for a delegated worker's call (run_id)", () => {
    // A worker call never entered the captain timeline, so there is nothing to stamp.
    const base = messageLaneFromMessage({ content: "" });
    const after = foldToolUsePhase(base, {
      tool_call_id: "call_worker",
      tool_name: "web_search",
      phase: "querying",
      run_id: "run_2",
    } satisfies ToolUseProgressPayload);
    expect(after).toBe(base);
  });

  it("foldCheckpointMarker absorbs trailing content into the card slot", () => {
    const base = messageLaneFromMessage({
      content: "帮你梳理一下起步方案：",
      process: [
        { kind: "reasoning", text: "想一下" },
        { kind: "content", text: "帮你梳理一下起步方案：" },
      ],
    });
    const next = foldCheckpointMarker(base, "cp_1");
    expect(next.content).toBe("");
    expect(next.process).toEqual([
      { kind: "reasoning", text: "想一下" },
      { kind: "checkpoint", checkpoint_id: "cp_1" },
    ]);
  });
});

// Reload 补标记（时间线一期）: journal → positional markers, invariant「有交互卡必有
// 时间线标记」without ever eating settled content (absorb is live-only semantics).
describe("ensureTimelineMarkersFromJournal", () => {
  const journal = [
    { type: "message_start", payload: { message_id: "m1" } },
    { type: "content_delta", payload: { delta: "我来安排团队。" } },
    { type: "run_plan", payload: { execution_id: "exec1" } },
    { type: "team_preview_required", payload: { checkpoint_id: "tp1" } },
    { type: "checkpoint_required", payload: { checkpoint_id: "cp1" } },
    { type: "question_posted", payload: { ask_id: "ask1" } },
    { type: "plan_review_required", payload: { checkpoint_id: "pr1" } },
  ];

  it("backfills every marker a bare persisted process is missing", () => {
    const process = ensureTimelineMarkersFromJournal(
      [{ kind: "content", text: "我来安排团队。" }],
      journal,
    );
    expect(process).toEqual([
      { kind: "content", text: "我来安排团队。" },
      // team_preview product order: inserted BEFORE the team marker (insertBeforeTeam).
      { kind: "team_preview", checkpoint_id: "tp1" },
      { kind: "team", execution_id: "exec1" },
      { kind: "checkpoint", checkpoint_id: "cp1" },
      { kind: "ask", ask_id: "ask1" },
      { kind: "plan_review", checkpoint_id: "pr1" },
    ]);
  });

  it("no-ops (dedup) when the persisted process already carries the markers", () => {
    const persisted = [
      { kind: "content", text: "我来安排团队。" },
      { kind: "team_preview", checkpoint_id: "tp1" },
      { kind: "team", execution_id: "exec1" },
      { kind: "checkpoint", checkpoint_id: "cp1" },
      { kind: "ask", ask_id: "ask1" },
      { kind: "plan_review", checkpoint_id: "pr1" },
      { kind: "content", text: "收尾。" },
    ] as const;
    const process = ensureTimelineMarkersFromJournal(
      [...persisted] as Parameters<typeof ensureTimelineMarkersFromJournal>[0],
      journal,
    );
    expect(process).toEqual([...persisted]);
  });

  it("never absorbs settled trailing content (unlike the live checkpoint fold)", () => {
    const process = ensureTimelineMarkersFromJournal(
      [{ kind: "content", text: "定稿正文，resolve 后的收尾。" }],
      [{ type: "checkpoint_required", payload: { checkpoint_id: "cp9" } }],
    );
    expect(process).toEqual([
      { kind: "content", text: "定稿正文，resolve 后的收尾。" },
      { kind: "checkpoint", checkpoint_id: "cp9" },
    ]);
  });

  it("backfills graph_append and skips team for host_message_id run_plan", () => {
    const process = ensureTimelineMarkersFromJournal(
      [{ kind: "content", text: "再加一人。" }],
      [
        {
          type: "graph_append",
          payload: {
            execution_id: "exec1",
            host_message_id: "m1",
            added_count: 1,
          },
        },
        {
          type: "run_plan",
          payload: {
            execution_id: "exec1",
            host_message_id: "m1",
          },
        },
      ],
    );
    expect(process).toEqual([
      { kind: "content", text: "再加一人。" },
      {
        kind: "graph_append",
        execution_id: "exec1",
        host_message_id: "m1",
        added_count: 1,
      },
    ]);
  });
});

describe("foldTeamMarker", () => {
  it("promotes scalar CEO lead-in before stamping team (图在回复下方)", () => {
    const base = messageLaneFromMessage({
      content: "这是个很有意思的方向",
      process: [{ kind: "reasoning", text: "想一下" }],
    });
    const next = foldTeamMarker(base, "exec1");
    expect(next.process).toEqual([
      { kind: "reasoning", text: "想一下" },
      { kind: "content", text: "这是个很有意思的方向" },
      { kind: "team", execution_id: "exec1" },
    ]);
  });
});
