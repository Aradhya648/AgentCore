/**
 * Product notices REST client (全局公告 — not IM / standing-task inbox).
 */

import { api } from "@/services/api";
import type { components } from "@/types/api.generated";

type Schemas = components["schemas"];

export type ActiveNotice = Schemas["ActiveNotice"];
export type ActiveNoticesResponse = Schemas["ActiveNoticesResponse"];

export async function fetchActive(): Promise<ActiveNoticesResponse> {
  return api.get<ActiveNoticesResponse>("/v1/notices/active");
}

/** Dismiss once; ``never`` → 409. Idempotent 204 when already dismissed. */
export async function dismissNotice(id: string): Promise<void> {
  await api.post(`/v1/notices/${encodeURIComponent(id)}/dismiss`);
}
