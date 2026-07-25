/**
 * 图头「待你拍板」行动条的数据层（批 R3 决策 3）。
 *
 * 聚合一个回合（execution）里全部**待你拍板**：检查点 / 阻塞升级（node 级，散在
 * 节点角标的那批）+ 工具审批 / 委派授权（execution 级交互卡）。行动条据此显示
 * 「待你拍板 N」并逐条定位——node 级直达对应节点（折叠幕内先聚焦幕再居中），
 * execution 级锚到团队代表节点 / 整图。
 *
 * 纯函数、无 React / 无 store——{@link useGraphPendingDecisions} 从交互 store 取
 * pending 交互引用后调本函数；单测直接钉聚合与锚定逻辑。**不建卡**：行动条只做
 * 导航，真正的拍板卡仍归聊天流 / 画布指挥台既有面（不与其重复）。
 */

import { escalationRowKindLabel } from "@/components/graph/agentNode/shared";
import type { Execution, RunNode } from "@/stores/execution";

export type GraphPendingKind =
  | "escalation"
  | "checkpoint"
  | "approval"
  | "delegation_authorization";

export interface GraphPendingDecision {
  /** 稳定去重键。 */
  id: string;
  kind: GraphPendingKind;
  /** 定位目标 run 节点；null = execution 级（定位退回整图 fit）。 */
  runId: string | null;
  /** 目标所属幕 actId（折叠幕内先聚焦该幕再居中）；null = 未知 / 不适用。 */
  actId: string | null;
  /** 主标题：node 级用角色名；execution 级用决策名（团队授权 / 工具审批）。 */
  title: string;
  /** 一行原因：待放行 / 待你拍板（缺输入）/ 放行开工 …。 */
  detail: string;
}

/** 由 store 派生的 pending 交互引用（工具审批 / 委派授权）。 */
export interface PendingInteractionRef {
  kind: "approval" | "delegation_authorization";
  id: string;
}

function escalationKindTag(esc: RunNode["escalations"][number]): string {
  const label = escalationRowKindLabel(esc);
  return label ? `（${label}）` : "";
}

/**
 * 聚合一个 execution 的全部待拍板。顺序：先按 run 顺序收 node 级（升级 → 检查点），
 * 再收 execution 级交互（授权 / 审批）——与「先扫节点、再看图头授权」的阅读序一致。
 */
export function collectGraphPendingDecisions(
  execution: Execution | null | undefined,
  interactions: readonly PendingInteractionRef[] = [],
): GraphPendingDecision[] {
  if (!execution) return [];
  const captainId =
    execution.runs.find((r) => r.kind === "captain")?.id ?? null;
  const roleOf = (r: RunNode): string =>
    execution.agents.find((a) => a.id === r.agentId)?.role ??
    r.role ??
    r.agentId;

  const out: GraphPendingDecision[] = [];
  for (const r of execution.runs) {
    if (r.id === captainId) continue;
    // 与节点「待你拍板」角标同口径：全部 pending 升级都计（含 CEO 仲裁中，节点角标亦显）。
    for (const [i, e] of r.escalations.entries()) {
      if (e.status !== "pending") continue;
      out.push({
        id: `esc:${e.id ?? `${r.id}:${i}`}`,
        kind: "escalation",
        runId: r.id,
        actId: r.actId ?? "act-1",
        title: roleOf(r),
        detail: `待你拍板${escalationKindTag(e)}`,
      });
    }
    if (r.checkpoint?.status === "pending") {
      out.push({
        id: `cp:${r.id}`,
        kind: "checkpoint",
        runId: r.id,
        actId: r.actId ?? "act-1",
        title: roleOf(r),
        detail: "待放行",
      });
    }
  }

  // execution 级（工具审批 / 委派授权）：锚到团队代表节点，使「点击定位」有真实目标；
  // 委派授权先于团队开工 → 锚首个 worker（团队入口）；工具审批多为 CEO 级 → 锚汇聚点。
  const firstWorker = execution.runs.find((r) => r.id !== captainId) ?? null;
  for (const it of interactions) {
    if (it.kind === "delegation_authorization") {
      out.push({
        id: `auth:${it.id}`,
        kind: "delegation_authorization",
        runId: firstWorker?.id ?? null,
        actId: firstWorker?.actId ?? null,
        title: "团队授权",
        detail: "放行开工",
      });
    } else {
      out.push({
        id: `appr:${it.id}`,
        kind: "approval",
        runId: captainId,
        actId: null,
        title: "工具审批",
        detail: "待放行",
      });
    }
  }
  return out;
}
