// @vitest-environment jsdom
import { beforeEach, describe, expect, it } from "vitest";
import type { DebateModel } from "../../model";
import {
  canUseSplitLayout,
  loadDebateArenaLayout,
  partitionSides,
  saveDebateArenaLayout,
} from "../debateLayoutPreference";

describe("debateLayoutPreference", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it("defaults to split and persists stack", () => {
    expect(loadDebateArenaLayout()).toBe("split");
    saveDebateArenaLayout("stack");
    expect(loadDebateArenaLayout()).toBe("stack");
  });

  it("canUseSplitLayout requires debate form with pro/con", () => {
    const base: DebateModel = {
      form: "debate",
      motion: null,
      stopReason: null,
      moderatorRunId: null,
      narrativeFirst: false,
      rounds: [],
      brief: null,
      sides: [
        {
          key: "pro",
          name: "正方",
          stance: "支持采用方案 A",
          model: "",
          is_subject: false,
        },
        {
          key: "con",
          name: "反方",
          stance: "反对采用方案 A",
          model: "",
          is_subject: false,
        },
      ],
      closings: [],
      opening: null,
      settled: false,
      crossExamEnabled: false,
      evidenceLedger: [],
      subtopics: null,
      pretrial: null,
    };
    expect(canUseSplitLayout(base)).toBe(true);

    expect(canUseSplitLayout({ ...base, form: "red_team" })).toBe(false);
    expect(
      canUseSplitLayout({
        ...base,
        sides: null,
        rounds: [
          {
            roundNo: 1,
            focus: "",
            summary: "",
            verdict: null,
            inFlight: true,
            clashes: [],
            userInterjections: [],
            crossExam: [],
            witnessExam: [],
            scores: [],
            findings: [],
            threadTurns: [],
            sides: [
              {
                key: "r1",
                sideKey: "pro",
                name: "正方",
                stance: "pro",
                colorVar: "var(--debate-side-pro)",
                model: "",
                run: null,
              },
            ],
          },
        ],
      }),
    ).toBe(true);
  });

  it("partitionSides maps by stance or key", () => {
    const pro = { key: "1", sideKey: "pro", name: "正", stance: null };
    const con = { key: "2", sideKey: "con", name: "反", stance: null };
    expect(
      partitionSides(
        [con, pro],
        (s) => s.sideKey,
        (s) => s.stance,
      ),
    ).toEqual({ pro, con, others: [] });

    // 后端自定 key（非 pro/con）靠 stance 分列——「结辩/质询只认 key 会堆叠」的根因回归；
    // 多方第三方落 others。
    const p2 = { sideKey: "卖方", stance: "pro" as const };
    const c2 = { sideKey: "买方", stance: "con" as const };
    const third = { sideKey: "mid", stance: null };
    expect(
      partitionSides(
        [c2, third, p2],
        (s) => s.sideKey,
        (s) => s.stance,
      ),
    ).toEqual({ pro: p2, con: c2, others: [third] });
  });
});
