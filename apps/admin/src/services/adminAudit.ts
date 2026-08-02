import { api } from "@/services/api";
import type { components } from "@/types/api.generated";

export type AdminAuditLogLine = components["schemas"]["AdminAuditLogLine"];
export type AdminAuditLogListResponse =
  components["schemas"]["AdminAuditLogListResponse"];

export async function listAuditLogs(params: {
  page?: number;
  pageSize?: number;
  action?: string;
  actorId?: string;
}): Promise<AdminAuditLogListResponse> {
  const q = new URLSearchParams();
  if (params.page) q.set("page", String(params.page));
  if (params.pageSize) q.set("page_size", String(params.pageSize));
  if (params.action) q.set("action", params.action);
  if (params.actorId) q.set("actor_id", params.actorId);
  const suffix = q.size ? `?${q}` : "";
  return api.get<AdminAuditLogListResponse>(`/v1/admin/audit-logs${suffix}`);
}

/** Human-readable labels for audit action codes. */
export const AUDIT_ACTION_LABELS: Record<string, string> = {
  "user.update": "修改用户",
  "user.reset_password": "重置密码",
  "user.set_password": "设置密码",
  "user.delete": "注销账号",
  "account.change_password": "修改密码",
  "conversation.replay": "回放对话",
};
