import { BASE_URL } from "@/services/api";
import {
  type ChatMention,
  type ChatMessageDetail,
  type ChatSummary,
  type MessageReplyTo,
  isImageAttachment,
} from "@/services/messaging";

/** Visible body token for `@所有人` (display only; truth is `kind: "everyone"`). */
export const EVERYONE_MENTION_LABEL = "所有人";

/** Resolve a backend-relative avatar URL for `<img src>`. */
export function avatarSrc(url: string | null | undefined): string | null {
  if (!url) return null;
  return url.startsWith("/") ? `${BASE_URL}${url}` : url;
}

/** Max chars for a reply quote preview (composer bar + bubble quote). */
export const REPLY_BODY_PREVIEW_MAX = 80;

/** Truncate a reply body preview with an ellipsis when over the soft cap. */
export function truncateReplyPreview(
  text: string,
  max = REPLY_BODY_PREVIEW_MAX,
): string {
  const compact = text.trim().replace(/\s+/g, " ");
  if (!compact) return "";
  if (compact.length <= max) return compact;
  return `${compact.slice(0, max)}…`;
}

/**
 * Build a local reply snapshot from the message being replied to (optimistic
 * bubble + composer bar). Server/firehose `reply_to` wins after reconcile.
 */
export function buildReplySnapshot(
  message: ChatMessageDetail,
  senderDisplayName: string,
): MessageReplyTo {
  return {
    sender_user_id: message.sender_user_id,
    sender_display_name: senderDisplayName.trim() || "成员",
    body_preview: replyBodyPreview(message),
  };
}

/** Body/attachment label used in reply quotes (never empty for a sendable msg). */
export function replyBodyPreview(message: ChatMessageDetail): string {
  const text = truncateReplyPreview(message.content ?? "");
  if (text) return text;
  const attachments = message.attachments ?? [];
  if (attachments.length > 0) {
    if (attachments.every((a) => isImageAttachment(a.name))) return "[图片]";
    return "[文件]";
  }
  switch (message.content_type) {
    case "image":
      return "[图片]";
    case "file":
      return "[文件]";
    case "system_card":
      return "[通知]";
    default:
      return "";
  }
}

/** Brand display name for the site-wide official broadcast chat. */
export const OFFICIAL_CHAT_DISPLAY_NAME = "AgentCore 官方";

/** The list-row / thread-header name for a chat. */
export function chatDisplayName(chat: ChatSummary): string {
  if (chat.type === "dm") {
    return chat.peer?.display_name || chat.peer?.username || "未知用户";
  }
  if (chat.type === "official") return OFFICIAL_CHAT_DISPLAY_NAME;
  return chat.title || "群聊";
}

/** Site-wide official broadcast chat id from a loaded chat list, if present. */
export function findOfficialChatId(
  chats: readonly ChatSummary[],
): string | null {
  return chats.find((c) => c.type === "official")?.id ?? null;
}

/** First character for a fallback avatar (CJK-safe; never splits a surrogate). */
export function avatarInitial(name: string): string {
  const trimmed = name.trim();
  if (!trimmed) return "?";
  return Array.from(trimmed)[0].toUpperCase();
}

/** Visible `@…` token for a structured mention (body display; not the truth source). */
export function mentionAtToken(
  mention: ChatMention,
  resolveUserName: (userId: string) => string | undefined,
): string {
  if (mention.kind === "everyone") return `@${EVERYONE_MENTION_LABEL}`;
  const name = resolveUserName(mention.user_id)?.trim() || "成员";
  return `@${name}`;
}

/** Whether this message @-mentions `userId` or everyone. */
export function messageMentionsUser(
  message: Pick<ChatMessageDetail, "mentions">,
  userId: string | null | undefined,
): boolean {
  const mentions = message.mentions;
  if (!mentions || mentions.length === 0) return false;
  for (const m of mentions) {
    if (m.kind === "everyone") return true;
    if (userId && m.kind === "user" && m.user_id === userId) return true;
  }
  return false;
}

/**
 * Keep only mentions whose visible `@token` still appears in `content`
 * (composer may delete the inserted text without clearing the pending list).
 */
export function filterMentionsInContent(
  content: string,
  mentions: readonly ChatMention[],
  resolveUserName: (userId: string) => string | undefined,
): ChatMention[] {
  const seen = new Set<string>();
  const out: ChatMention[] = [];
  for (const m of mentions) {
    const key = m.kind === "everyone" ? "everyone" : `user:${m.user_id}`;
    if (seen.has(key)) continue;
    const token = mentionAtToken(m, resolveUserName);
    if (!content.includes(token)) continue;
    seen.add(key);
    out.push(m);
  }
  return out;
}

export type MentionContentSegment =
  | { type: "text"; text: string }
  | { type: "mention"; text: string; self: boolean };

/**
 * Light highlighter: wrap body `@token`s that match structured `mentions`.
 * Longest token first to avoid partial overlaps; no heavy parser.
 */
export function splitContentByMentions(
  content: string,
  mentions: readonly ChatMention[] | null | undefined,
  resolveUserName: (userId: string) => string | undefined,
  myUserId?: string | null,
): MentionContentSegment[] {
  if (!content) return [];
  if (!mentions || mentions.length === 0) {
    return [{ type: "text", text: content }];
  }

  const tokens: { token: string; self: boolean }[] = [];
  const seen = new Set<string>();
  for (const m of mentions) {
    const token = mentionAtToken(m, resolveUserName);
    if (seen.has(token)) continue;
    seen.add(token);
    const self =
      m.kind === "everyone" ||
      (m.kind === "user" && !!myUserId && m.user_id === myUserId);
    tokens.push({ token, self });
  }
  tokens.sort((a, b) => b.token.length - a.token.length);
  if (tokens.length === 0) return [{ type: "text", text: content }];

  const segments: MentionContentSegment[] = [];
  let i = 0;
  while (i < content.length) {
    let hit: { token: string; self: boolean } | null = null;
    let hitAt = -1;
    for (const t of tokens) {
      const at = content.indexOf(t.token, i);
      if (at === -1) continue;
      if (hitAt === -1 || at < hitAt) {
        hitAt = at;
        hit = t;
      }
    }
    if (!hit || hitAt === -1) {
      segments.push({ type: "text", text: content.slice(i) });
      break;
    }
    if (hitAt > i) {
      segments.push({ type: "text", text: content.slice(i, hitAt) });
    }
    segments.push({ type: "mention", text: hit.token, self: hit.self });
    i = hitAt + hit.token.length;
  }
  return segments;
}

/**
 * Active `@query` range ending at `caret` (after whitespace/start). Null when
 * not in an IM mention draft.
 */
export function findImMentionDraft(
  text: string,
  caret: number,
): { start: number; end: number; query: string } | null {
  if (caret < 0 || caret > text.length) return null;
  const before = text.slice(0, caret);
  const match = before.match(/(?:^|[\s\n])@([^\s@]*)$/);
  if (!match) return null;
  const query = match[1] ?? "";
  const start = before.length - query.length - 1;
  return { start, end: caret, query };
}
