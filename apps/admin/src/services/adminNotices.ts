import { api } from "@/services/api";
import type { components } from "@/types/api.generated";

export type Notice = components["schemas"]["NoticeSummary"];
export type NoticeListResponse = components["schemas"]["NoticeListResponse"];
export type CreateNoticeRequest = components["schemas"]["CreateNoticeRequest"];
export type UpdateNoticeRequest = components["schemas"]["UpdateNoticeRequest"];

export type NoticeStatus = "draft" | "published" | "archived";
export type NoticeSeverity = CreateNoticeRequest["severity"];
export type NoticeSurface = CreateNoticeRequest["surface"];
export type NoticeDismissPolicy = CreateNoticeRequest["dismiss_policy"];

export type ListNoticesParams = {
  status?: NoticeStatus;
  limit?: number;
  offset?: number;
};

/** Admin roster of product notices. */
export async function listNotices(
  params: ListNoticesParams = {},
): Promise<NoticeListResponse> {
  const search = new URLSearchParams();
  if (params.status) search.set("status", params.status);
  if (params.limit != null) search.set("limit", String(params.limit));
  if (params.offset != null) search.set("offset", String(params.offset));
  const qs = search.toString();
  return api.get<NoticeListResponse>(
    `/v1/admin/notices${qs ? `?${qs}` : ""}`,
  );
}

/** Create a draft notice (server defaults status to draft). */
export async function createNotice(
  body: CreateNoticeRequest,
): Promise<Notice> {
  return api.post<Notice>("/v1/admin/notices", body);
}

/** Patch editable fields. Archived notices are rejected server-side (409). */
export async function updateNotice(
  noticeId: string,
  body: UpdateNoticeRequest,
): Promise<Notice> {
  return api.patch<Notice>(`/v1/admin/notices/${noticeId}`, body);
}

/** Publish a draft (or re-publish flow as defined by the backend). */
export async function publishNotice(noticeId: string): Promise<Notice> {
  return api.post<Notice>(`/v1/admin/notices/${noticeId}/publish`);
}

/** Archive a notice so it leaves active surfaces. */
export async function archiveNotice(noticeId: string): Promise<Notice> {
  return api.post<Notice>(`/v1/admin/notices/${noticeId}/archive`);
}
