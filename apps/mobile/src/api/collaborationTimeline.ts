import { apiFetch } from "@/api/client";
import type { components } from "@/types/api.generated";

type Schemas = components["schemas"];

export type CollaborationTimelineAct = Schemas["CollaborationTimelineAct"];
export type CollaborationDossierRef = Schemas["CollaborationDossierRef"];
export type CollaborationTimelineItem = Schemas["CollaborationTimelineItem"];
export type CollaborationTimelineResponse =
  Schemas["CollaborationTimelineResponse"];

/** 项目协作时间线（读时聚合 · GET /v1/folders/{id}/collaboration-timeline）。 */
export async function fetchCollaborationTimeline(
  folderId: string,
  opts?: { limit?: number; offset?: number },
): Promise<CollaborationTimelineResponse> {
  const limit = opts?.limit ?? 20;
  const offset = opts?.offset ?? 0;
  const q = new URLSearchParams({
    limit: String(limit),
    offset: String(offset),
  });
  const res = await apiFetch(
    `/v1/folders/${encodeURIComponent(folderId)}/collaboration-timeline?${q}`,
  );
  if (!res.ok) throw new Error(`加载协作时间线失败 (${res.status})`);
  return (await res.json()) as CollaborationTimelineResponse;
}

export function formatActChain(
  acts: CollaborationTimelineAct[] | undefined | null,
): string {
  if (!acts?.length) return "";
  return acts.map((a) => a.title?.trim() || a.act_id).join(" → ");
}
