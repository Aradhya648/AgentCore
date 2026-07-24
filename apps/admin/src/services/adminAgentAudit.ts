import { api } from "@/services/api";
import type { AdminAgentAuditSummary } from "@agentcore/contract-rest-types/audit";

export type { AdminAgentAuditSummary };

/** 运营观测：近 7 日 Agent 审计聚合（工具失败 / 审批拒绝·超时 / 委派计划 / 采集降级）。 */
export async function fetchAgentAuditSummary(): Promise<AdminAgentAuditSummary> {
  return api.get<AdminAgentAuditSummary>("/v1/admin/audit/summary");
}
