/**
 * Agent 行为审计 REST 契约（Phase 1 + Phase 2 + 会话权限 P2）。
 *
 * 对齐 `apps/server/agentcore/api/schemas/agent_audit.py` 与
 * `GET /v1/conversations/{id}/messages/{mid}/audit`（`include_causal` 可选）、
 * `GET /v1/conversations/{id}/audit`（会话安全台账）、
 * `GET /v1/conversations/{id}/audit/file?path=…`、
 * `GET /v1/admin/audit/summary`。
 */

/** 审计事件类别（编排 / 工具 / 审批 / 通信 / 状态 / 失败 / 权限）。 */
export type AuditCategory =
  | "orchestration"
  | "tool"
  | "approval"
  | "comm"
  | "state"
  | "failure"
  | "permission";

/** 事件结果。 */
export type AuditOutcome = "ok" | "denied" | "failed" | "skipped";

/** 行为主体种类。 */
export type AuditActorKind = "captain" | "member" | "system";

/** 审计目标类型。 */
export type AuditTargetType =
  | "file"
  | "tool"
  | "run"
  | "note"
  | "interaction";

/** 单条 append-only 审计事件（`AgentAuditEventLine` 投影）。 */
export interface AgentAuditEvent {
  id: string;
  /** 助理消息 id（== turn_id）。 */
  turn_id: string;
  trace_id: string | null;
  execution_id: string | null;
  run_id: string | null;
  parent_run_id: string | null;
  /** turn 内单调序（审计独立编号，不与 journal seq 对齐）。 */
  seq: number;
  category: AuditCategory;
  /** 如 `delegate.plan` / `tool.file_write` / `approval.granted`。 */
  action: string;
  actor_kind: AuditActorKind;
  target_type: AuditTargetType | null;
  /** 工作区相对路径 / tool_call_id / note_id 等（非全文）。 */
  target_ref: string | null;
  outcome: AuditOutcome;
  /** 结构化摘要（禁止密钥 / 全文正文）。 */
  detail: Record<string, unknown>;
  created_at: string;
}

/** 因果图边种类。 */
export type AuditCausalEdgeKind = "parent" | "depends_on" | "inject";

/** 因果图 run 节点。 */
export interface AuditCausalNode {
  run_id: string;
  role?: string | null;
  parent_run_id?: string | null;
}

/** 因果图有向边。 */
export interface AuditCausalEdge {
  kind: AuditCausalEdgeKind;
  from: string;
  to: string;
}

/** 运行时从审计行重建的因果图（方案 C）。 */
export interface AuditCausalGraph {
  nodes: AuditCausalNode[];
  edges: AuditCausalEdge[];
}

/** Phase 2 权限 / 审批 / 状态增量 action（非穷举）。 */
export type AuditPhase2Action =
  | "permission.tool_disabled"
  | "permission.write_conflict"
  | "permission.preset_changed"
  | "permission.preset_snapshot"
  | "approval.swept"
  | "checkpoint.paused"
  | "checkpoint.resumed"
  | "run.retry";

/** `GET /v1/conversations/{id}/messages/{mid}/audit` 与会话级 `/audit` 响应。 */
export interface AgentAuditListResponse {
  data: AgentAuditEvent[];
  total: number;
  /** 仅当 `include_causal=true` 时返回。 */
  causal_graph?: AuditCausalGraph | null;
}

/** `GET /v1/admin/audit/summary` 平台聚合（固定近 7 日窗口，无查询参数）。 */
export interface AdminAgentAuditSummary {
  /** 窗口内审计事件总数。 */
  events: number;
  /** category=failure 的事件数。 */
  failures: number;
  /** action=approval.timeout 的事件数。 */
  approval_timeouts: number;
  /** action=approval.denied 的事件数。 */
  approval_denied: number;
  /** action=delegate.plan 的事件数。 */
  delegate_plans: number;
  /** turn_metrics.audit_drops 窗口内合计（采集降级计数）。 */
  audit_drops: number;
}
