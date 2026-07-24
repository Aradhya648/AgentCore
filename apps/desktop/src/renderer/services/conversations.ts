import { BASE_URL, api } from "@/services/api";
import { type FolderMeta, toFolder } from "@/services/folders";
import type { ModelSelection } from "@/services/models";
import { trashBareConversationScratch } from "@/services/trashBareScratch";
import { authedFetch, saveBlob } from "@/services/workspaceHttp";
import type { Conversation } from "@/stores/conversation";
import type { components } from "@/types/api.generated";

// REST DTOs generated from the backend OpenAPI spec (`pnpm gen:api`), aliased to
// the local names so the mappers below read unchanged (API 开发规范, 渐进迁移).
type Schemas = components["schemas"];

/** A conversation row from the list/detail endpoints (server-shaped). */
type BackendConversation = Schemas["ConversationSummary"];
/** Paginated conversation list (`GET /v1/conversations`). */
type ConversationListResponse = Schemas["ConversationListResponse"];
/** Folders + ungrouped conversations in one trip (`/v1/conversations/grouped`). */
type GroupedConversationsResponse = Schemas["GroupedConversationsResponse"];

/** Placeholder shown until the backend generates a title (or for empty ones). */
const UNTITLED = "新对话";

/** Align with backend ``TITLE_MAX_CHARS`` (conversation title mint / fallback). */
export const TITLE_MAX_CHARS = 30;

/** Sidebar provisional title from the first user message (before ``title_generated``). */
export function provisionalConversationTitle(text: string): string {
  const trimmed = text.trim();
  if (!trimmed) return UNTITLED;
  return trimmed.length > TITLE_MAX_CHARS
    ? `${trimmed.slice(0, TITLE_MAX_CHARS)}…`
    : trimmed;
}

function toConversation(c: BackendConversation): Conversation {
  return {
    id: c.id,
    title: c.title?.trim() || UNTITLED,
    updatedAt: c.updated_at,
    // The list/grouped endpoints carry message_count (0 for an unsent chat).
    messageCount: c.message_count ?? 0,
    lastMessagePreview: null,
    folderId: c.folder_id ?? null,
    localContainerRootId: c.local_container_root_id ?? null,
    pinned: c.pinned ?? false,
    archived: c.archived ?? false,
    permissionPreset:
      (c as { permission_preset?: Conversation["permissionPreset"] })
        .permission_preset ?? "workspace",
    model: c.model ?? null,
    modelOrigin: c.model_origin ?? null,
    modelProviderId: c.model_provider_id ?? null,
  };
}

/** Load the user's conversations, pinned-first then most-recent (server-ordered).
 * `archived` flips to the「已归档」view (归档对话): the live list excludes archived
 * rows, this returns only them. */
export async function listConversations(
  archived = false,
): Promise<Conversation[]> {
  const res = await api.get<ConversationListResponse>(
    `/v1/conversations?page_size=100&archived=${archived}`,
  );
  return res.data.map(toConversation);
}

/**
 * Load folders + every conversation (each tagged with its `folderId`) in one
 * round trip (§七). The flat conversation list stays the store's source of
 * truth; the sidebar shows the recent few and the /conversations page derives
 * the folder groups.
 */
export async function listGrouped(): Promise<{
  folders: FolderMeta[];
  conversations: Conversation[];
}> {
  const res = await api.get<GroupedConversationsResponse>(
    "/v1/conversations/grouped",
  );
  const folders = res.folders.map((f) =>
    toFolder({
      id: f.id,
      name: f.name,
      mode: f.mode,
      local_root_id: f.local_root_id,
      local_subpath: f.local_subpath,
      created_at: "",
      updated_at: "",
    }),
  );
  const conversations = [
    ...res.folders.flatMap((f) => f.conversations.map(toConversation)),
    ...res.ungrouped.map(toConversation),
  ];
  return { folders, conversations };
}

/** Soft-delete a conversation server-side. */
export async function deleteConversation(id: string): Promise<void> {
  await api.delete(`/v1/conversations/${id}`);
  // 裸聊本地 scratch → 系统回收站（软删）；项目共享目录不动。
  void trashBareConversationScratch(id);
  // W3: drop session read-only roots on this device (server grant store cleared too).
  void window.fsApi?.clearSessionReadonlyRoots?.(id);
}

/** Persist a new conversation title. */
export async function renameConversation(
  id: string,
  title: string,
): Promise<void> {
  await api.patch(`/v1/conversations/${id}`, { title });
}

/** Clone a conversation into a brand-new one carrying a copy of its transcript
 * (克隆对话). Returns the new (server-shaped) row — same folder as the source,
 * titled「… 副本」— so the caller can insert it into the sidebar and open it. */
export async function duplicateConversation(id: string): Promise<Conversation> {
  const res = await api.post<BackendConversation>(
    `/v1/conversations/${id}/duplicate`,
  );
  return toConversation(res);
}

/** Export formats offered by the backend (导出对话): a clean Markdown record or a
 * full-fidelity JSON dump. */
export type ExportFormat = "md" | "json";

/** Pull the download filename from a Content-Disposition header, preferring the
 * RFC 5987 `filename*=UTF-8''…` form (carries the non-ASCII title) over the ASCII
 * `filename="…"` fallback; returns `fallback` when the header is absent/unreadable
 * (the server must expose the header via CORS for this to be populated). */
function filenameFromDisposition(res: Response, fallback: string): string {
  const cd = res.headers.get("Content-Disposition") ?? "";
  const utf8 = /filename\*=UTF-8''([^;]+)/i.exec(cd);
  if (utf8?.[1]) {
    try {
      return decodeURIComponent(utf8[1]);
    } catch {
      // Malformed percent-encoding — fall through to the ASCII form.
    }
  }
  const ascii = /filename="?([^";]+)"?/i.exec(cd);
  return ascii?.[1]?.trim() || fallback;
}

/** Download a conversation's full transcript as a file (导出对话). Streams the
 * attachment via the cookie-authed raw-bytes path (bypassing the JSON `api`
 * helper) and saves it with the server's sanitized filename. */
export async function exportConversation(
  id: string,
  format: ExportFormat = "md",
): Promise<void> {
  const res = await authedFetch(
    `${BASE_URL}/v1/conversations/${id}/export?format=${format}`,
  );
  const blob = await res.blob();
  await saveBlob(blob, filenameFromDisposition(res, `conversation.${format}`));
}

/** Pin / unpin a conversation (置顶对话). Returns the updated row. */
export async function setConversationPinned(
  id: string,
  pinned: boolean,
): Promise<Conversation> {
  const res = await api.patch<BackendConversation>(`/v1/conversations/${id}`, {
    pinned,
  });
  return toConversation(res);
}

/** Archive / unarchive a conversation (归档对话, reversible). Returns the updated
 * row — unarchive (archived=false) yields a live-list row to put back. */
export async function setConversationArchived(
  id: string,
  archived: boolean,
): Promise<Conversation> {
  const res = await api.patch<BackendConversation>(`/v1/conversations/${id}`, {
    archived,
  });
  return toConversation(res);
}

/**
 * 切换会话使用的聊天模型（会话级模型切换）。传 (id, origin, providerId) 固定本会话模型；
 * 传 `null` 清除覆盖、回落账号默认。`origin === "byok"` 时**必须**带 `model_provider_id`
 * （否则后端 422）；`platform` 时留空。模型不可用 / 越权时后端返 422（由调用方 toast 呈现）。
 * 返回更新后的会话行，`model` / `modelOrigin` / `modelProviderId` 即服务端最终态。
 */
export async function setConversationModel(
  id: string,
  selection: ModelSelection | null,
): Promise<Conversation> {
  const model = selection?.id.trim() ? selection.id.trim() : null;
  const model_origin = model && selection ? selection.origin : null;
  const model_provider_id =
    model && selection?.origin === "byok"
      ? (selection.providerId ?? null)
      : null;
  const res = await api.patch<BackendConversation>(`/v1/conversations/${id}`, {
    model,
    model_origin,
    model_provider_id,
  });
  return toConversation(res);
}
