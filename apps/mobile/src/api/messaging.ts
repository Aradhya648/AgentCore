// 消息 (人际 IM) REST client for the mobile shell (前端技术与架构 §七 · 人际消息).
//
// The 消息 page is human↔human, a domain separate from the 对话 page's AI conversations,
// so this is its own service with its own types. messages.py is REST-only (no SSE), so the
// mobile client POLLS (the locked decision): the chat list and the open thread each refresh
// on an interval. REST DTOs track OpenAPI via @agentcore/contract-rest-types.
import { apiFetch } from "@/api/client";
import type { components } from "@/types/api.generated";

type Schemas = components["schemas"];

export type ChatType = Schemas["ChatSummary"]["type"];
export type ChatMemberState = Schemas["ChatSummary"]["state"];
export type ChatSenderType = Schemas["ChatMessageDetail"]["sender_type"];
export type MessageContentType = Schemas["ChatMessageDetail"]["content_type"];
export type SendContentType = Schemas["SendChatMessageRequest"]["content_type"];

export type StoredAttachment = Schemas["StoredAttachment"];
export type ChatParticipant = Schemas["ChatParticipant"];
export type ChatSummary = Schemas["ChatSummary"];
export type ChatMessageDetail = Schemas["ChatMessageDetail"];
export type UserSearchResult = Schemas["UserSearchResult"];
export type BlockedUser = Schemas["BlockedUser"];
export type ChatFileUploadResponse = Schemas["ChatFileUploadResponse"];

type ChatListResponse = Schemas["ChatListResponse"];
type ChatMembersResponse = Schemas["ChatMembersResponse"];
type UserSearchResponse = Schemas["UserSearchResponse"];
type ChatMessageListResponse = Schemas["ChatMessageListResponse"];
type BlockListResponse = Schemas["BlockListResponse"];

async function getJson<T>(path: string, fallback: string): Promise<T> {
  const res = await apiFetch(path);
  if (!res.ok) throw await toError(res, fallback);
  return (await res.json()) as T;
}

async function postJson<T>(
  path: string,
  body: unknown,
  fallback: string,
): Promise<T> {
  const res = await apiFetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body ?? {}),
  });
  if (!res.ok) throw await toError(res, fallback);
  return (await res.json()) as T;
}

// --- People search (任意搜人) ---

export async function searchUsers(
  query: string,
  limit = 20,
): Promise<UserSearchResult[]> {
  const res = await getJson<UserSearchResponse>(
    `/v1/messages/users/search?q=${encodeURIComponent(query)}&limit=${limit}`,
    "搜索失败",
  );
  return res.data;
}

// --- Chats ---

/** This user's chat list (recent first), with unread counts and dm peers. */
export async function listChats(): Promise<ChatSummary[]> {
  const res = await getJson<ChatListResponse>(
    "/v1/messages/chats",
    "加载会话失败",
  );
  return res.data;
}

/** Open (or reuse) a 1:1 chat with another user (by their user id). */
export async function startDm(userId: string): Promise<ChatSummary> {
  return postJson<ChatSummary>(
    "/v1/messages/chats/dm",
    { user_id: userId },
    "无法发起会话",
  );
}

/** A chat's members (group roster: resolves sender names for group bubbles). */
export async function listMembers(chatId: string): Promise<ChatParticipant[]> {
  const res = await getJson<ChatMembersResponse>(
    `/v1/messages/chats/${chatId}/members`,
    "加载成员失败",
  );
  return res.data;
}

/** Leave a group/official chat (removes this user's membership). */
export async function leaveChat(chatId: string): Promise<void> {
  await postJson(`/v1/messages/chats/${chatId}/leave`, {}, "退出会话失败");
}

// --- Messages ---

export interface MessagePage {
  messages: ChatMessageDetail[];
  total: number;
  page: number;
  pageSize: number;
}

/** A page of a chat's messages (oldest first). */
export async function listMessages(
  chatId: string,
  page = 1,
  pageSize = 50,
): Promise<MessagePage> {
  const res = await getJson<ChatMessageListResponse>(
    `/v1/messages/chats/${chatId}/messages?page=${page}&page_size=${pageSize}`,
    "加载消息失败",
  );
  return {
    messages: res.data,
    total: res.total,
    page: res.page,
    pageSize: res.page_size,
  };
}

export interface SendMessageInput {
  content?: string;
  contentType?: SendContentType;
  attachments?: StoredAttachment[];
  clientMsgId?: string;
  replyToMessageId?: string;
}

/** Send a message into a chat the user belongs to (text and/or attachments). */
export async function sendMessage(
  chatId: string,
  input: SendMessageInput,
): Promise<ChatMessageDetail> {
  return postJson<ChatMessageDetail>(
    `/v1/messages/chats/${chatId}/messages`,
    {
      content: input.content,
      content_type: input.contentType ?? "text",
      attachments: input.attachments ?? [],
      client_msg_id: input.clientMsgId,
      reply_to_message_id: input.replyToMessageId,
    },
    "发送失败",
  );
}

/** Advance this user's read cursor (drives unread counts). */
export async function markRead(
  chatId: string,
  lastReadMessageId: string,
): Promise<void> {
  await postJson(
    `/v1/messages/chats/${chatId}/read`,
    { last_read_message_id: lastReadMessageId },
    "标记已读失败",
  );
}

// --- Attachments (富消息: PUT raw bytes → reference the returned path in sendMessage) ---

const chatFilePath = (chatId: string, path: string): string =>
  `/v1/messages/chats/${chatId}/files/${path.split("/").map(encodeURIComponent).join("/")}`;

/** Upload an attachment's raw bytes into a chat's space; returns its stored path + size
 *  + (for images) a thumbnail path. The caller copies these onto a StoredAttachment. */
export async function uploadChatFile(
  chatId: string,
  path: string,
  body: Blob,
): Promise<ChatFileUploadResponse> {
  const res = await apiFetch(chatFilePath(chatId, path), {
    method: "PUT",
    headers: { "Content-Type": body.type || "application/octet-stream" },
    body,
  });
  if (!res.ok) throw await toError(res, "上传失败");
  return (await res.json()) as ChatFileUploadResponse;
}

/** Fetch an attachment as a Blob (Bearer-authed → object URL for inline images / share). */
export async function fetchChatAttachmentBlob(
  chatId: string,
  workspacePath: string,
): Promise<Blob> {
  const res = await apiFetch(chatFilePath(chatId, workspacePath));
  if (!res.ok) throw await toError(res, "下载附件失败");
  return res.blob();
}

// --- Blocking (任意搜人 护栏) ---

export async function listBlocks(): Promise<BlockedUser[]> {
  const res = await getJson<BlockListResponse>(
    "/v1/messages/blocks",
    "加载失败",
  );
  return res.data;
}

export async function blockUser(userId: string): Promise<void> {
  await postJson("/v1/messages/blocks", { user_id: userId }, "拉黑失败");
}

export async function unblockUser(targetId: string): Promise<void> {
  const res = await apiFetch(`/v1/messages/blocks/${targetId}`, {
    method: "DELETE",
  });
  if (!res.ok) throw await toError(res, "取消拉黑失败");
}

// --- Display helpers ---

const IMAGE_EXT = new Set(["png", "jpg", "jpeg", "gif", "webp", "bmp", "avif"]);

/** Whether a filename looks like an inline-renderable image (by extension). SVG is
 *  intentionally excluded (a document, shown as a chip). */
export function isImageAttachment(name: string): boolean {
  const dot = name.lastIndexOf(".");
  return dot >= 0 && IMAGE_EXT.has(name.slice(dot + 1).toLowerCase());
}

/** The display name for a chat row: dm → peer's name; group/official → its title. */
export function chatTitle(chat: ChatSummary): string {
  if (chat.type === "dm")
    return chat.peer?.display_name || chat.peer?.username || "对话";
  return chat.title || "群聊";
}

/**
 * A user-facing zh message for a failed messaging call. The backend ships precise zh
 * refusals (e.g. 对方仅允许联系人发起会话) in `{error:{message}}` — surface that verbatim;
 * else fall back to a status phrase. The 404 default avoids leaking chat existence.
 */
async function toError(res: Response, fallback: string): Promise<Error> {
  try {
    const body = (await res.json()) as { error?: { message?: string } };
    if (body.error?.message) return new Error(body.error.message);
  } catch {
    /* non-JSON */
  }
  if (res.status === 429) return new Error("操作过于频繁，请稍后再试");
  if (res.status === 403) return new Error("无法向该用户发送消息");
  if (res.status === 404) return new Error("用户或会话不存在");
  return new Error(`${fallback} (${res.status})`);
}
