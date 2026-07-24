/**
 * 辩论主持人侧面板：从既有 execution 投影推导主持人身份与「主持台账」摘要，
 * 不新增 wire 字段。识别与协作图 {@link debateModeratorId} 同源。
 */
import { stopLabel, toDebateModel } from "@/components/chat/debate/model";
import { debateModeratorId } from "@/components/graph/helpers";
import type { AgentState, Execution } from "@/stores/execution";

/** 是否渲染「思考中」空占位：声明 thinking=false 的 run 不占位；已有 reasoning 仍由调用方照常显示。 */
export function isThinkingLivePlaceholder(
  agent: Pick<
    AgentState,
    "thinking" | "status" | "outputChunks" | "toolProgress"
  >,
): boolean {
  if (!agent.thinking) return false;
  return (
    agent.status === "working" &&
    agent.outputChunks.join("").length === 0 &&
    !agent.toolProgress
  );
}

/** 当前回合辩论主持人 run id；非辩论 / 尚无法从投影推导 → null。 */
export function resolveDebateModeratorRunId(
  execution: Execution,
): string | null {
  const settled = execution.debate?.moderator_run_id;
  if (settled) return settled;
  return debateModeratorId(execution.runs, null);
}

export function isDebateModeratorRun(
  execution: Execution,
  runId: string,
): boolean {
  const modId = resolveDebateModeratorRunId(execution);
  return modId != null && modId === runId;
}

export interface ModeratorLedgerRound {
  roundNo: number;
  focus: string;
  summary: string;
  /** 进行中当前轮（尚未裁判）；收场恒 false。 */
  inFlight: boolean;
}

/** 侧面板「主持台账」紧凑摘要——不含发言全文 / 质询 / 记分。 */
export interface ModeratorLedger {
  settled: boolean;
  opening: string | null;
  /** 收场收敛归因文案；进行中 null。 */
  stopLabel: string | null;
  rounds: ModeratorLedgerRound[];
}

export function buildModeratorLedger(
  execution: Execution,
): ModeratorLedger | null {
  const model = toDebateModel(execution);
  if (!model || model.rounds.length === 0) return null;
  return {
    settled: model.settled,
    opening: model.opening,
    stopLabel: model.settled ? stopLabel(model.stopReason) : null,
    rounds: model.rounds.map((r) => ({
      roundNo: r.roundNo,
      focus: r.focus,
      summary: r.summary,
      inFlight: r.inFlight,
    })),
  };
}
