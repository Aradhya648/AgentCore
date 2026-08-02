import { describe, expect, it } from "vitest";
import {
  ASK_INTENT_META,
  TEAM_PRIMITIVE_META,
  askResolvedOutcome,
  teamPendingMarkerLabel,
  teamResolvedOutcome,
} from "../meta";

describe("decision meta", () => {
  it("ask kickoff / proposal_pick / risk_ack / organize_plan / daily_review keep settled labels", () => {
    expect(askResolvedOutcome("kickoff", "continue").label).toBe(
      "已按你的决定继续",
    );
    expect(askResolvedOutcome("proposal_pick", "continue").label).toBe(
      "已选定方案",
    );
    expect(askResolvedOutcome("risk_ack", "continue").label).toBe(
      "已确认风险处理项",
    );
    expect(askResolvedOutcome("organize_plan", "continue").label).toBe(
      "已确认整理方案",
    );
    expect(askResolvedOutcome("daily_review", "continue").label).toBe(
      "已确认复盘提案",
    );
    expect(ASK_INTENT_META.daily_review.cta).toBe("确认落盘");
    expect(ASK_INTENT_META.daily_review.activeCaption).toBe(
      "复盘提案 · 确认要落盘的项",
    );
    expect(askResolvedOutcome("kickoff", "research_first").label).toBe(
      "已停止本回合",
    );
    expect(askResolvedOutcome("kickoff", "research_first").tone).toBe(
      "destructive",
    );
  });

  it("team debate research_first + continue-with-note overrides", () => {
    expect(teamResolvedOutcome("debate", "research_first", false).label).toBe(
      "已选先调研 · 辩论未开赛",
    );
    expect(teamResolvedOutcome("delegate", "research_first", false).label).toBe(
      "已停止 · 团队未启动",
    );
    expect(teamResolvedOutcome("delegate", "continue", true).label).toBe(
      "已授权开工 · 嘱咐已注入队员",
    );
    expect(teamResolvedOutcome("debate", "continue", true).label).toBe(
      "已授权开赛 · 嘱咐已注入",
    );
  });

  it("pending marker + resume captions share one table", () => {
    expect(teamPendingMarkerLabel("delegate", "2 名队员")).toBe(
      "等你确认 · 确认后才会开工（2 名队员）",
    );
    expect(TEAM_PRIMITIVE_META.debate.activeCaption).toBe(
      "等你确认 · 确认后才会开赛",
    );
    expect(ASK_INTENT_META.kickoff.activeCaption).toBe("需要你拍板");
    expect(ASK_INTENT_META.kickoff.cta).toBe("提交");
    expect(ASK_INTENT_META.decision.activeCaption).toBe(
      ASK_INTENT_META.kickoff.activeCaption,
    );
  });
});
