import { api } from "@/services/api";
import type { components } from "@/types/api.generated";

export type AdminSystemStatus = components["schemas"]["AdminSystemStatus"];

/**
 * 系统状态: a read-only deployment snapshot — billing mode + global quota defaults
 * + FX rate (config), database reachability, build provenance, and account
 * tallies. Nothing here is editable from the console (config is env + redeploy).
 */
export async function fetchSystemStatus(): Promise<AdminSystemStatus> {
  return api.get<AdminSystemStatus>("/v1/admin/system");
}
