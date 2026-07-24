import { foldDebatePretrial } from "@/stores/execution/debate";
import { describe, expect, it } from "vitest";

describe("foldDebatePretrial", () => {
  it("started → running；orders 写入任务单；progress 只更新台账计数；completed 权威覆盖", () => {
    let state = foldDebatePretrial(null, "debate_pretrial_started", {
      thorough: true,
      sides: [
        { key: "pro", name: "支持方" },
        { key: "con", name: "反对方" },
      ],
    });
    expect(state?.status).toBe("running");
    expect(state?.orders).toEqual([]);

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
    });
    expect(state?.status).toBe("done");
    expect(state?.investigators).toHaveLength(1);
    expect(state?.evidenceReady).toBe(true);
    expect(state?.investigatorCountPerSide).toBeUndefined();
  });

  it("fast skip：completed 权威为 skipped", () => {
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
    });
    expect(state?.status).toBe("skipped");
    expect(state?.skipReason).toBe("fast");
  });

  it("progress 在 started 之前不落态", () => {
    expect(
      foldDebatePretrial(null, "debate_pretrial_progress", {
        evidence_ledger_count: 1,
      }),
    ).toBeNull();
  });
});
