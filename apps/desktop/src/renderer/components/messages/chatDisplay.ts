import { BASE_URL } from "@/services/api";
import type { ChatSummary } from "@/services/messaging";

/** Resolve a backend-relative avatar URL for `<img src>`. */
export function avatarSrc(url: string | null | undefined): string | null {
  if (!url) return null;
  return url.startsWith("/") ? `${BASE_URL}${url}` : url;
}

/** The list-row / thread-header name for a chat. */
export function chatDisplayName(chat: ChatSummary): string {
  if (chat.type === "dm") {
    return chat.peer?.display_name || chat.peer?.username || "未知用户";
  }
  return chat.title || (chat.type === "official" ? "官方号" : "群聊");
}

/** First character for a fallback avatar (CJK-safe; never splits a surrogate). */
export function avatarInitial(name: string): string {
  const trimmed = name.trim();
  if (!trimmed) return "?";
  return Array.from(trimmed)[0].toUpperCase();
}
