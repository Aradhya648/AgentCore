// 工具执行阶段进度 (联网搜索前端展示优化): the transport-only live sibling extractToolPhases.
// It reads the running-tool phase off raw SSE events (never journaled, kept OUT of the
// ProjectedTurn) so the mobile waiting UI shows 正在检索 / 排队中 / 改用备用引擎 instead of a
// static 进行中 — and clears a tool's phase the moment it ends.

import {
  extractEvidenceLedger,
  extractGraphAppendActKinds,
  extractGraphAppendAuthorizedBy,
  extractStageCardTraces,
  extractToolPhases,
  extractWorkerToolPhases,
  fold,
} from "@/protocol/fold";
import type { SSEEvent } from "@agentcore/contract-types";
import { diffProjected, loadFixtures } from "@agentcore/protocol-conformance";
import { describe, expect, it } from "vitest";

function ev(type: SSEEvent["type"], payload: unknown): SSEEvent {
  return { type, timestamp: "", payload } as SSEEvent;
}

describe("extractGraphAppendActKinds", () => {
  it("透传 graph_append.act_kind（开辩论幕）", () => {
    const map = extractGraphAppendActKinds([
      ev("graph_append", {
        execution_id: "exec1",
        host_message_id: "m1",
        append_message_id: "m2",
        added_count: 3,
        act_id: "act-2",
        act_kind: "debate",
      }),
    ]);
    expect(map.get("exec1")).toBe("debate");
  });
});

describe("extractGraphAppendAuthorizedBy / stage_card process", () => {
  it("透传 authorized_by", () => {
    const map = extractGraphAppendAuthorizedBy([
      ev("graph_append", {
        execution_id: "exec1",
        host_message_id: "m1",
        append_message_id: "m2",
        added_count: 1,
        act_kind: "debate",
        authorized_by: "stage_card",
      }),
    ]);
    expect(map.get("exec1")).toBe("stage_card");
  });

  it("stage_card_required 落 process marker；traces 跟踪去向", () => {
    const turn = fold([
      ev("message_start", { message_id: "m1", conversation_id: "c1" }),
      ev("content_delta", { delta: "调研呈报。" }),
      ev("stage_card_required", {
        stage_card_id: "sc1",
        conversation_id: "c1",
        motion: "是否开辩",
        sides: [],
        form: "debate",
      }),
      ev("message_end", { finish_reason: "end_turn" }),
    ]);
    expect(turn.process.some((s) => s.kind === "stage_card")).toBe(true);
    const traces = extractStageCardTraces([
      ev("stage_card_required", {
        stage_card_id: "sc1",
        conversation_id: "c1",
        motion: "是否开辩",
        sides: [],
        form: "debate",
      }),
      ev("stage_card_resolved", {
        stage_card_id: "sc1",
        decision: "start_debate",
      }),
    ]);
    expect(traces.get("sc1")?.outcome).toBe("resolved");
    expect(traces.get("sc1")?.decision).toBe("start_debate");
  });
});

describe("fold · graph_append / cross-turn append", () => {
  it("multi_agent_cross_turn_append fixture aligns with golden", () => {
    const fixture = loadFixtures().find(
      (f) => f.name === "multi_agent_cross_turn_append",
    );
    expect(fixture).toBeTruthy();
    if (!fixture) return;
    const actual = fold(fixture.events as SSEEvent[]);
    expect(diffProjected(fixture.projected, actual)).toEqual([]);
  });

  it("graph_append 透传 process 锚点；host_message_id run_plan 不插 team", () => {
    const turn = fold([
      ev("message_start", { message_id: "m2", conversation_id: "c1" }),
      ev("content_delta", { delta: "再加一人。" }),
      ev("graph_append", {
        execution_id: "exec1",
        host_message_id: "m1",
        append_message_id: "m2",
        added_count: 2,
        roles: ["撰写员", "校对"],
        added_run_ids: ["r3", "r4"],
      }),
      ev("run_plan", {
        execution_id: "exec1",
        plan_type: "multi_agent",
        task_summary: "追加",
        host_message_id: "m1",
        agents: [
          {
            id: "w3",
            role: "撰写员",
            thinking: false,
          },
        ],
        runs: [{ id: "r3", agent_id: "w3", task: "写", depends_on: [] }],
      }),
    ]);
    expect(turn.process).toEqual([
      { kind: "content", text: "再加一人。" },
      {
        kind: "graph_append",
        execution_id: "exec1",
        host_message_id: "m1",
        added_count: 2,
      },
    ]);
    expect(turn.process.some((s) => s.kind === "team")).toBe(false);
    expect(turn.runs.map((r) => r.id)).toEqual(["r3"]);
  });

  it("message_start 清正文/process，同 execution_id 保留 agents/runs", () => {
    const turn = fold([
      ev("message_start", { message_id: "m1", conversation_id: "c1" }),
      ev("content_delta", { delta: "第一回合。" }),
      ev("run_plan", {
        execution_id: "exec1",
        plan_type: "multi_agent",
        task_summary: "建图",
        agents: [
          {
            id: "w1",
            role: "研究员",
            thinking: true,
          },
        ],
        runs: [{ id: "r1", agent_id: "w1", task: "调研", depends_on: [] }],
      }),
      ev("run_started", {
        run_id: "r1",
        agent_id: "w1",
        parent_run_id: null,
        kind: "agent",
      }),
      ev("run_completed", {
        run_id: "r1",
        agent_id: "w1",
        output_summary: "ok",
        duration_ms: 10,
      }),
      ev("message_end", { finish_reason: "end_turn" }),
      ev("message_start", { message_id: "m2", conversation_id: "c1" }),
      ev("content_delta", { delta: "追加回合。" }),
      ev("graph_append", {
        execution_id: "exec1",
        host_message_id: "m1",
        append_message_id: "m2",
        added_count: 1,
      }),
      ev("run_plan", {
        execution_id: "exec1",
        plan_type: "multi_agent",
        task_summary: "生长",
        host_message_id: "m1",
        agents: [
          {
            id: "w1",
            role: "研究员",
            thinking: true,
          },
          {
            id: "w2",
            role: "撰写员",
            thinking: false,
          },
        ],
        runs: [
          { id: "r1", agent_id: "w1", task: "调研", depends_on: [] },
          { id: "r2", agent_id: "w2", task: "写", depends_on: [] },
        ],
      }),
      ev("run_started", {
        run_id: "r2",
        agent_id: "w2",
        parent_run_id: null,
        kind: "agent",
      }),
      ev("run_completed", {
        run_id: "r2",
        agent_id: "w2",
        output_summary: "done",
        duration_ms: 20,
      }),
      ev("message_end", { finish_reason: "end_turn" }),
    ]);
    expect(turn.content).toBe("追加回合。");
    expect(turn.process.map((s) => s.kind)).toEqual([
      "content",
      "graph_append",
    ]);
    expect(turn.agents.map((a) => a.id)).toEqual(["w1", "w2"]);
    expect(turn.runs.map((r) => r.id)).toEqual(["r1", "r2"]);
    expect(turn.runs.find((r) => r.id === "r1")?.status).toBe("completed");
    expect(turn.runs.find((r) => r.id === "r2")?.status).toBe("completed");
    // 不同 execution 才清空重建；同 id merge 不把宿主已完成节点 skip 掉
    expect(turn.runs.every((r) => r.status !== "skipped")).toBe(true);
  });
});

describe("fold · replaces_run_id", () => {
  it("透传 plan.replaces_run_id 与 run_started.replaces_run_id", () => {
    const turn = fold([
      ev("message_start", {
        message_id: "m1",
        conversation_id: "c1",
      }),
      ev("run_plan", {
        execution_id: "e1",
        plan_type: "multi_agent",
        task_summary: "补派",
        agents: [
          { id: "a1", role: "写手", thinking: false },
          {
            id: "a1b",
            role: "写手",
            thinking: false,
          },
        ],
        runs: [
          { id: "r1", agent_id: "a1", task: "写", depends_on: [] },
          {
            id: "r1b",
            agent_id: "a1b",
            task: "写（补派）",
            depends_on: [],
            replaces_run_id: "r1",
          },
        ],
      }),
      ev("run_started", {
        run_id: "r1b",
        agent_id: "a1b",
        parent_run_id: null,
        kind: "agent",
        replaces_run_id: "r1",
      }),
    ]);
    expect(turn.runs.find((r) => r.id === "r1b")?.replacesRunId).toBe("r1");
  });
});

describe("extractToolPhases", () => {
  it("keeps the LATEST phase per running tool_call_id", () => {
    const phases = extractToolPhases([
      ev("tool_use_start", { tool_call_id: "c1", tool_name: "web_search" }),
      ev("tool_use_progress", {
        tool_call_id: "c1",
        tool_name: "web_search",
        phase: "querying",
      }),
      ev("tool_use_progress", {
        tool_call_id: "c1",
        tool_name: "web_search",
        phase: "fallback",
      }),
    ]);
    expect(phases.get("c1")).toBe("fallback");
  });

  it("clears a tool's phase on its matching tool_use_end", () => {
    const phases = extractToolPhases([
      ev("tool_use_progress", {
        tool_call_id: "c1",
        tool_name: "web_search",
        phase: "querying",
      }),
      ev("tool_use_end", {
        tool_call_id: "c1",
        tool_name: "web_search",
        result: "ok",
        status: "success",
      }),
    ]);
    expect(phases.has("c1")).toBe(false);
  });

  it("tracks concurrent tool calls independently", () => {
    const phases = extractToolPhases([
      ev("tool_use_progress", {
        tool_call_id: "c1",
        tool_name: "web_search",
        phase: "queued",
      }),
      ev("tool_use_progress", {
        tool_call_id: "c2",
        tool_name: "web_search",
        phase: "querying",
      }),
      ev("tool_use_end", {
        tool_call_id: "c1",
        tool_name: "web_search",
        result: "ok",
        status: "success",
      }),
    ]);
    expect(phases.get("c1")).toBeUndefined();
    expect(phases.get("c2")).toBe("querying");
  });

  it("returns an empty map for a turn with no progress events (history replay)", () => {
    const phases = extractToolPhases([
      ev("content_delta", { delta: "hi" }),
      ev("tool_use_start", { tool_call_id: "c1", tool_name: "web_search" }),
      ev("tool_use_end", {
        tool_call_id: "c1",
        tool_name: "web_search",
        result: "ok",
        status: "success",
      }),
    ]);
    expect(phases.size).toBe(0);
  });
});

describe("extractWorkerToolPhases", () => {
  it("keeps the LATEST phase per worker run_id", () => {
    const phases = extractWorkerToolPhases([
      ev("tool_use_progress", {
        tool_call_id: "c1",
        tool_name: "web_search",
        phase: "queued",
        run_id: "run-2",
      }),
      ev("tool_use_progress", {
        tool_call_id: "c1",
        tool_name: "web_search",
        phase: "querying",
        run_id: "run-2",
      }),
    ]);
    expect(phases.get("run-2")).toEqual({
      phase: "querying",
      toolName: "web_search",
    });
  });

  it("ignores CEO-scoped progress (no run_id)", () => {
    const phases = extractWorkerToolPhases([
      ev("tool_use_progress", {
        tool_call_id: "c1",
        tool_name: "web_search",
        phase: "querying",
      }),
    ]);
    expect(phases.size).toBe(0);
  });

  it("clears a worker phase on tool_use_end with run_id", () => {
    const phases = extractWorkerToolPhases([
      ev("tool_use_progress", {
        tool_call_id: "c1",
        tool_name: "web_search",
        phase: "fallback",
        run_id: "run-9",
      }),
      ev("tool_use_end", {
        tool_call_id: "c1",
        tool_name: "web_search",
        result: "ok",
        status: "success",
        run_id: "run-9",
      }),
    ]);
    expect(phases.size).toBe(0);
  });
});

describe("extractEvidenceLedger", () => {
  it("合并 debate_pretrial_completed.evidence_ledger_delta（#e1 不靠收场后再补）", () => {
    const ledger = extractEvidenceLedger([
      ev("debate_pretrial_completed", {
        execution_id: "exec1",
        moderator_run_id: "mod",
        status: "done",
        evidence_ledger_delta: [
          {
            id: "#e1",
            title: "庭前证据",
            url: "https://example.com/e1",
            site: "example.com",
          },
        ],
      }),
    ]);
    expect(ledger.map((e) => e.id)).toEqual(["#e1"]);
  });

  it("pretrial delta 与 round delta 累积；debate_result 权威覆盖", () => {
    const ledger = extractEvidenceLedger([
      ev("debate_pretrial_completed", {
        execution_id: "exec1",
        moderator_run_id: "mod",
        evidence_ledger_delta: [
          { id: "#e1", title: "pretrial", url: "https://a.example" },
        ],
      }),
      ev("debate_round", {
        execution_id: "exec1",
        moderator_run_id: "mod",
        round_no: 1,
        focus: "焦点",
        summary: "",
        verdict: null,
        sides: [],
        clashes: [],
        evidence_ledger_delta: [
          { id: "#e2", title: "round", url: "https://b.example" },
        ],
      }),
      ev("debate_result", {
        execution_id: "exec1",
        evidence_ledger: [
          { id: "#e9", title: "final", url: "https://z.example" },
        ],
      }),
    ]);
    expect(ledger.map((e) => e.id)).toEqual(["#e9"]);
  });
});
