import { type ExecutionJournal, useExecutionStore } from "@/stores/execution";
import { foldDebatePretrial } from "@/stores/execution/debate";
import { beforeEach, describe, expect, it } from "vitest";
import {
  MID,
  plan,
  resetExecutionStore,
  rt,
  store,
} from "../../__tests__/execution/fixtures";

describe("foldDebatePretrial", () => {
  it("started → running（不宣称完整度）；orders 写入任务单；progress 只更新台账计数；completed 权威覆盖", () => {
    let state = foldDebatePretrial(null, "debate_pretrial_started", {
      thorough: true,
      sides: [
        { key: "pro", name: "支持方" },
        { key: "con", name: "反对方" },
      ],
    });
    expect(state?.status).toBe("running");
    expect(state?.orders).toEqual([]);
    expect(state?.completeness).toBeUndefined();
    expect(state?.incomplete).toBeUndefined();

    state = foldDebatePretrial(state, "debate_pretrial_orders", {
      thorough: true,
      sides: [
        { key: "pro", name: "支持方" },
        { key: "con", name: "反对方" },
      ],
      orders: [
        {
          side_key: "pro",
          tasks: [{ query: "成本", purpose: "立论" }],
          source: "debater",
        },
      ],
      investigator_count_per_side: 1,
    });
    expect(state?.orders).toHaveLength(1);
    expect(state?.investigatorCountPerSide).toBe(1);
    // orders 不破坏「权威=completed」：仍不宣称完整度。
    expect(state?.completeness).toBeUndefined();
    expect(state?.incomplete).toBeUndefined();

    state = foldDebatePretrial(state, "debate_pretrial_progress", {
      evidence_ledger_count: 2,
    });
    expect(state?.evidenceLedgerCount).toBe(2);
    expect(state?.investigators).toEqual([]);

    state = foldDebatePretrial(state, "debate_pretrial_completed", {
      status: "done",
      thorough: true,
      sides: [
        { key: "pro", name: "支持方" },
        { key: "con", name: "反对方" },
      ],
      orders: [
        {
          side_key: "pro",
          tasks: [{ query: "成本", purpose: "立论" }],
          source: "debater",
        },
      ],
      investigators: [
        {
          side_key: "pro",
          run_id: "inv1",
          parent_run_id: "pro1",
          ok: true,
          task_query: "成本",
        },
      ],
      evidence_ledger_count: 2,
      evidence_ready: true,
      fallback_self_search: false,
      completeness: "full",
      incomplete: false,
      failed_sides: [],
    });
    expect(state?.status).toBe("done");
    expect(state?.investigators).toHaveLength(1);
    expect(state?.evidenceReady).toBe(true);
    expect(state?.completeness).toBe("full");
    expect(state?.incomplete).toBe(false);
    expect(state?.failedSides).toEqual([]);
    expect(state?.investigatorCountPerSide).toBeUndefined();
  });

  it("旧 journal 缺 completeness/incomplete → 未知（不默认 empty→incomplete）", () => {
    const state = foldDebatePretrial(null, "debate_pretrial_completed", {
      status: "done",
      thorough: true,
      sides: [
        { key: "pro", name: "支持方" },
        { key: "con", name: "反对方" },
      ],
      orders: [],
      investigators: [],
      evidence_ledger_count: 0,
      evidence_ready: false,
      fallback_self_search: false,
      failed_sides: [],
    });
    expect(state?.status).toBe("done");
    expect(state?.completeness).toBeUndefined();
    expect(state?.incomplete).toBeUndefined();
  });

  it("fast skip：completed 权威为 skipped；保留 wire 上的 incomplete（UI 靠 skipReason 抑制失败态）", () => {
    let state = foldDebatePretrial(null, "debate_pretrial_started", {
      thorough: false,
      skip_reason: "fast",
      sides: [
        { key: "pro", name: "支持方" },
        { key: "con", name: "反对方" },
      ],
    });
    state = foldDebatePretrial(state, "debate_pretrial_completed", {
      status: "skipped",
      thorough: false,
      skip_reason: "fast",
      sides: [
        { key: "pro", name: "支持方" },
        { key: "con", name: "反对方" },
      ],
      orders: [],
      investigators: [],
      evidence_ledger_count: 0,
      evidence_ready: false,
      fallback_self_search: false,
      completeness: "empty",
      incomplete: false,
      failed_sides: [],
    });
    expect(state?.status).toBe("skipped");
    expect(state?.skipReason).toBe("fast");
    expect(state?.incomplete).toBe(false);
    expect(state?.completeness).toBe("empty");
  });

  it("部分失败：degraded + failedSides", () => {
    const state = foldDebatePretrial(null, "debate_pretrial_completed", {
      status: "degraded",
      thorough: true,
      sides: [
        { key: "pro", name: "支持方" },
        { key: "con", name: "反对方" },
      ],
      orders: [],
      investigators: [
        {
          side_key: "pro",
          run_id: "inv1",
          parent_run_id: "pro1",
          ok: true,
        },
        {
          side_key: "con",
          run_id: "inv2",
          parent_run_id: "con1",
          ok: false,
        },
      ],
      evidence_ledger_count: 1,
      evidence_ready: true,
      fallback_self_search: false,
      completeness: "partial",
      incomplete: true,
      failed_sides: ["con"],
    });
    expect(state?.status).toBe("degraded");
    expect(state?.completeness).toBe("partial");
    expect(state?.incomplete).toBe(true);
    expect(state?.failedSides).toEqual(["con"]);
  });

  it("Evidence Pack 齐全：skip 外证 + budget=0", () => {
    const state = foldDebatePretrial(null, "debate_pretrial_completed", {
      status: "skipped",
      thorough: true,
      sides: [
        { key: "pro", name: "支持方" },
        { key: "con", name: "反对方" },
      ],
      skip_reason: "evidence_pack",
      orders: [],
      investigators: [],
      evidence_ledger_count: 1,
      evidence_ready: true,
      fallback_self_search: false,
      completeness: "full",
      incomplete: false,
      failed_sides: [],
      external_evidence_mode: "skip",
      external_evidence_reason: "evidence_pack_full",
      retrieval_budget_per_investigator: 0,
    });
    expect(state?.skipReason).toBe("evidence_pack");
    expect(state?.completeness).toBe("full");
    expect(state?.incomplete).toBe(false);
    expect(state?.externalEvidenceMode).toBe("skip");
    expect(state?.externalEvidenceReason).toBe("evidence_pack_full");
    expect(state?.retrievalBudgetPerInvestigator).toBe(0);
  });

  it("Evidence Pack 缺口：gap_fill + partial", () => {
    const state = foldDebatePretrial(null, "debate_pretrial_completed", {
      status: "degraded",
      thorough: true,
      sides: [
        { key: "pro", name: "支持方" },
        { key: "con", name: "反对方" },
      ],
      orders: [],
      investigators: [],
      evidence_ledger_count: 2,
      evidence_ready: true,
      fallback_self_search: false,
      completeness: "partial",
      incomplete: true,
      failed_sides: ["con"],
      external_evidence_mode: "gap_fill",
      external_evidence_reason: "evidence_pack_gap",
      retrieval_budget_per_investigator: 2,
    });
    expect(state?.externalEvidenceMode).toBe("gap_fill");
    expect(state?.externalEvidenceReason).toBe("evidence_pack_gap");
    expect(state?.retrievalBudgetPerInvestigator).toBe(2);
    expect(state?.failedSides).toEqual(["con"]);
  });

  it("progress 在 started 之前不落态", () => {
    expect(
      foldDebatePretrial(null, "debate_pretrial_progress", {
        evidence_ledger_count: 1,
      }),
    ).toBeNull();
  });
});

describe("pretrial_completed evidence_ledger_delta → 场级台账", () => {
  beforeEach(() => {
    resetExecutionStore();
  });

  it("hydrate：pretrial_completed 带 #e1 → ledger 有条目（不靠收场后再补）", () => {
    const journal: ExecutionJournal = {
      finishReason: "end_turn",
      events: [
        {
          type: "run_plan",
          payload: {
            execution_id: "exec-pretrial-ledger",
            plan_type: "debate",
            task_summary: "庭前台账",
            agents: [{ id: "mod", role: "主持人", thinking: false }],
            runs: [
              {
                id: "mod",
                agent_id: "mod",
                task: "主持",
                depends_on: [],
              },
            ],
          },
          timestamp: "2026-01-01T00:00:00.001Z",
        },
        {
          type: "debate_pretrial_completed",
          payload: {
            execution_id: "exec-pretrial-ledger",
            moderator_run_id: "mod",
            status: "done",
            thorough: true,
            sides: [
              { key: "pro", name: "支持方" },
              { key: "con", name: "反对方" },
            ],
            orders: [],
            investigators: [],
            evidence_ledger_count: 1,
            evidence_ready: true,
            fallback_self_search: false,
            completeness: "full",
            incomplete: false,
            failed_sides: [],
            evidence_ledger_delta: [
              {
                id: "#e1",
                title: "庭前证据",
                url: "https://example.com/e1",
                site: "example.com",
              },
            ],
          },
          timestamp: "2026-01-01T00:00:00.002Z",
        },
      ],
    };
    store().hydrateFromJournal(MID, journal);
    expect(rt().evidenceLedger.map((e) => e.id)).toEqual(["#e1"]);
    expect(rt().debatePretrial?.evidenceLedgerCount).toBe(1);
  });

  it("live：recordEvidenceLedgerDelta 与 pretrial fold 同路径接通", () => {
    store().startExecution(
      { ...plan, planType: "debate", id: "exec-pretrial-live" },
      MID,
    );
    store().recordDebatePretrial(
      "debate_pretrial_completed",
      {
        execution_id: "exec-pretrial-live",
        moderator_run_id: "mod",
        status: "done",
        thorough: true,
        sides: [],
        orders: [],
        investigators: [],
        evidence_ledger_count: 1,
        evidence_ready: true,
        fallback_self_search: false,
        completeness: "full",
        incomplete: false,
        failed_sides: [],
        evidence_ledger_delta: [
          {
            id: "#e1",
            title: "live 庭前",
            url: "https://example.com/live",
          },
        ],
      },
      MID,
    );
    store().recordEvidenceLedgerDelta(
      [
        {
          id: "#e1",
          title: "live 庭前",
          url: "https://example.com/live",
        },
      ],
      MID,
    );
    expect(useExecutionStore.getState().byId[MID]?.evidenceLedger).toEqual([
      {
        id: "#e1",
        title: "live 庭前",
        url: "https://example.com/live",
      },
    ]);
  });
});
