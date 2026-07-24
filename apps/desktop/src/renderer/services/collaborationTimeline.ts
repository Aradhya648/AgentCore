import { api } from "@/services/api";
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
  return api.get<CollaborationTimelineResponse>(
    `/v1/folders/${encodeURIComponent(folderId)}/collaboration-timeline?${q}`,
  );
}

/** 幕序列一行摘要：多视角调研 → 辩论对抗 */
export function formatActChain(
  acts: CollaborationTimelineAct[] | undefined | null,
): string {
  if (!acts?.length) return "";
  return acts.map((a) => a.title?.trim() || a.act_id).join(" → ");
}

/** 案卷引用条来源的诚实短标签。 */
export function dossierSourceLabel(
  sources: CollaborationDossierRef["sources"] | undefined,
): string {
  const s = sources ?? [];
  const hasInject = s.includes("dossier_inject");
  const hasRead = s.includes("file_read");
  if (hasInject && hasRead) return "开赛注入 · 已读";
  if (hasInject) return "开赛注入";
  if (hasRead) return "会话内读取";
  return "案卷引用";
}
