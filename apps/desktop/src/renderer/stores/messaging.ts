import {
  chatDisplayName,
  messageMentionsUser,
} from "@/components/messages/chatDisplay";
import { notifyInfo } from "@/lib/toast";
import {
  type ChatMention,
  type ChatMessageDetail,
  type ChatParticipant,
  type ChatSummary,
  type MessageReplyTo,
  type SendContentType,
  type StoredAttachment,
  announce as apiAnnounce,
  kickMember as apiKickMember,
  leaveChat as apiLeaveChat,
  muteMember as apiMuteMember,
  sendMessage as apiSendMessage,
  isImageAttachment,
  listChats,
  listMembers,
  listMessages,
  markRead,
  messagingErrorMessage,
  updateMembership,
  uploadChatFile,
} from "@/services/messaging";
import { useAuthStore } from "@/stores/auth";
import { create } from "zustand";

/**
 * 消息 page (找人 IM) client state — deliberately separate from the AI
 * `conversation` store (消息IM.md §一: reuse UI + realtime, not the same data).
 *
 * Holds the chat list, per-chat message slices (loaded lazily on open — the
 * "离线补偿 on open" model), the active chat, and a transient send error. The
 * realtime firehose (services/realtime.ts, stage D) feeds new messages in via
 * {@link MessagingState.applyIncoming}; until it is wired, the store is fully
 * usable over REST alone.
 */

const EMPTY_MESSAGES: ChatMessageDetail[] = [];
const EMPTY_MEMBERS: ChatParticipant[] = [];
const PAGE_SIZE = 50;

/** Per-chat pagination cursor — tracks which page is the oldest loaded slice. */
interface ChatMessagesMeta {
  oldestPage: number;
  total: number;
  hasMoreOlder: boolean;
}

/** Dedupe by id + sort ascending by created_at — stable across overlapping pages. */
function mergeMessages(
  prev: ChatMessageDetail[],
  incoming: ChatMessageDetail[],
): ChatMessageDetail[] {
  const byId = new Map(prev.map((m) => [m.id, m]));
  for (const m of incoming) byId.set(m.id, m);
  return [...byId.values()].sort((a, b) =>
    a.created_at.localeCompare(b.created_at),
  );
}

/** A human-readable list-row preview for a message (non-text shows a kind tag). */
function previewOf(message: ChatMessageDetail): string {
  switch (message.content_type) {
    case "image":
      return "[图片]";
    case "file":
      return "[文件]";
    case "system_card": {
      // product_notice content is `title\nbody` — list row shows the title.
      if (message.payload?.kind === "product_notice") {
        const title = (message.content ?? "").split("\n")[0]?.trim();
        return title || "[公告]";
      }
      return "[通知]";
    }
    default:
      return message.content ?? "";
  }
}

/**
 * Apply a message to the chat list: refresh the row's preview/time, optionally
 * bump its unread count, and move it to the front (recent-first). A chat not in
 * the list is left untouched (the caller refetches to pull in a new request).
 */
function bumpChat(
  chats: ChatSummary[],
  chatId: string,
  preview: string,
  at: string,
  incUnread: number,
): ChatSummary[] {
  const idx = chats.findIndex((c) => c.id === chatId);
  if (idx === -1) return chats;
  const chat = chats[idx];
  const updated: ChatSummary = {
    ...chat,
    last_message_preview: preview,
    last_message_at: at,
    unread: chat.unread + incUnread,
  };
  return [updated, ...chats.filter((_, i) => i !== idx)];
}

interface MessagingState {
  chats: ChatSummary[];
  chatsLoaded: boolean;
  loadingChats: boolean;
  /** Loaded message slices keyed by chat id (oldest first); absent until opened. */
  messagesByChat: Record<string, ChatMessageDetail[]>;
  /** Pagination cursors for loaded slices (oldest page + whether earlier pages exist). */
  messagesMetaByChat: Record<string, ChatMessagesMeta>;
  loadingMessages: Record<string, boolean>;
  loadingOlderMessages: Record<string, boolean>;
  /** Group rosters keyed by chat id — resolves per-message sender names + the
   * member panel. Loaded lazily when a group thread opens. */
  membersByChat: Record<string, ChatParticipant[]>;
  /**
   * Muted chats that still need a list unread badge because of an @ mention
   * (消息IM.md §8.1 静音 × 被 @). Cleared when the chat is marked read.
   */
  mentionAlertByChat: Record<string, boolean>;
  activeChatId: string | null;
  /** Transient zh error for the last failed send, or null. */
  sendError: string | null;

  fetchChats: () => Promise<void>;
  /** Make a chat active, load its history, then advance its read cursor. */
  openChat: (chatId: string) => Promise<void>;
  setActiveChat: (chatId: string | null) => void;
  loadMessages: (chatId: string) => Promise<void>;
  /** Fetch the next older page and prepend it (deduped, scroll position preserved by caller). */
  loadOlderMessages: (chatId: string) => Promise<void>;
  /** Load (or refresh) a chat's member roster — used by group threads. */
  loadMembers: (chatId: string) => Promise<void>;
  /** Send a text and/or attachment message. Files are uploaded to the chat's
   * space first, then referenced; optimistic with rollback on failure.
   * Optional `replyTo` carries the S1 reply target id + local quote snapshot.
   * Optional `mentions` is the S2 structured @ list (body still has `@显示名`). */
  sendMessage: (
    chatId: string,
    content: string,
    files?: File[],
    replyTo?: { messageId: string; snapshot: MessageReplyTo } | null,
    mentions?: ChatMention[],
  ) => Promise<void>;
  markChatRead: (chatId: string) => Promise<void>;
  /** Toggle this user's per-chat flags (mute / pin); optimistic with rollback. */
  setMembershipFlags: (
    chatId: string,
    flags: { muted?: boolean; pinned?: boolean },
  ) => Promise<void>;
  /** Leave a group; on success drops it from the list. Returns success. */
  leaveChat: (chatId: string) => Promise<boolean>;
  /** Admin 踢人: remove a member, then drop them from the local roster. Throws on
   * failure so the caller can surface the precise zh refusal. */
  kickMember: (chatId: string, userId: string) => Promise<void>;
  /** Admin 禁言: mute/unmute a member, reflecting the flag in the local roster. */
  setAdminMute: (
    chatId: string,
    userId: string,
    muted: boolean,
  ) => Promise<void>;
  /** Admin 公告: post a system_card; mirror it locally (the firehose also delivers). */
  announce: (chatId: string, content: string) => Promise<void>;
  /** Merge or prepend a chat the client just learned about (e.g. a new dm). */
  upsertChat: (chat: ChatSummary) => void;
  /** Ingest a realtime message (from the firehose): merge + unread + reorder. */
  applyIncoming: (chatId: string, message: ChatMessageDetail) => void;
  /** Apply a firehose ``presence`` event: flip ``online`` on dm peers + rosters. */
  applyPresence: (userId: string, online: boolean) => void;
  clearSendError: () => void;
}

export const useMessagingStore = create<MessagingState>((set, get) => ({
  chats: [],
  chatsLoaded: false,
  loadingChats: false,
  messagesByChat: {},
  messagesMetaByChat: {},
  loadingMessages: {},
  loadingOlderMessages: {},
  membersByChat: {},
  mentionAlertByChat: {},
  activeChatId: null,
  sendError: null,

  fetchChats: async () => {
    set({ loadingChats: true });
    try {
      const chats = await listChats();
      set({ chats, chatsLoaded: true, loadingChats: false });
    } catch {
      // Best-effort: keep whatever the list already had and stop the spinner.
      set({ loadingChats: false });
    }
  },

  openChat: async (chatId) => {
    set({ activeChatId: chatId });
    await get().loadMessages(chatId);
    await get().markChatRead(chatId);
  },

  setActiveChat: (chatId) => set({ activeChatId: chatId }),

  loadMessages: async (chatId) => {
    if (get().loadingMessages[chatId]) return;
    set((s) => ({
      loadingMessages: { ...s.loadingMessages, [chatId]: true },
    }));
    try {
      // Land on the most recent page: page 1 yields the total, then fetch the last page.
      const first = await listMessages(chatId, 1, PAGE_SIZE);
      const total = first.total;
      const lastPage = Math.max(1, Math.ceil(total / PAGE_SIZE));
      const messages =
        lastPage === 1
          ? first.messages
          : (await listMessages(chatId, lastPage, PAGE_SIZE)).messages;
      set((s) => ({
        messagesByChat: { ...s.messagesByChat, [chatId]: messages },
        messagesMetaByChat: {
          ...s.messagesMetaByChat,
          [chatId]: {
            oldestPage: lastPage,
            total,
            hasMoreOlder: lastPage > 1,
          },
        },
        loadingMessages: { ...s.loadingMessages, [chatId]: false },
      }));
    } catch {
      set((s) => ({
        loadingMessages: { ...s.loadingMessages, [chatId]: false },
      }));
    }
  },

  loadOlderMessages: async (chatId) => {
    const meta = get().messagesMetaByChat[chatId];
    if (!meta?.hasMoreOlder || get().loadingOlderMessages[chatId]) return;
    const targetPage = meta.oldestPage - 1;
    if (targetPage < 1) return;

    set((s) => ({
      loadingOlderMessages: { ...s.loadingOlderMessages, [chatId]: true },
    }));
    try {
      const page = await listMessages(chatId, targetPage, PAGE_SIZE);
      set((s) => ({
        messagesByChat: {
          ...s.messagesByChat,
          [chatId]: mergeMessages(
            s.messagesByChat[chatId] ?? [],
            page.messages,
          ),
        },
        messagesMetaByChat: {
          ...s.messagesMetaByChat,
          [chatId]: {
            oldestPage: targetPage,
            total: page.total,
            hasMoreOlder: targetPage > 1,
          },
        },
        loadingOlderMessages: { ...s.loadingOlderMessages, [chatId]: false },
      }));
    } catch {
      set((s) => ({
        loadingOlderMessages: { ...s.loadingOlderMessages, [chatId]: false },
      }));
    }
  },

  loadMembers: async (chatId) => {
    try {
      const members = await listMembers(chatId);
      set((s) => ({
        membersByChat: { ...s.membersByChat, [chatId]: members },
      }));
    } catch {
      /* best-effort — without a roster, group bubbles fall back to a label */
    }
  },

  sendMessage: async (chatId, content, files, replyTo, mentions) => {
    const text = content.trim();
    const pending = files ?? [];
    if (!text && pending.length === 0) return;

    const clientMsgId = crypto.randomUUID();
    const replyToMessageId = replyTo?.messageId ?? null;
    const replySnapshot = replyTo?.snapshot ?? null;
    const mentionList =
      mentions && mentions.length > 0 ? [...mentions] : undefined;

    // Upload attachments first, so the message references durable paths. A failed
    // upload aborts the send (nothing optimistic was added yet) and surfaces a zh
    // error — the composer keeps the draft + files so the user can retry.
    let attachments: StoredAttachment[] = [];
    if (pending.length > 0) {
      set({ sendError: null });
      try {
        attachments = await Promise.all(
          pending.map(async (file) => {
            const path = `attachments/${crypto.randomUUID()}/${file.name}`;
            const res = await uploadChatFile(chatId, path, file);
            return {
              name: file.name,
              path: file.name,
              kind: "file",
              // IM 上传路径只存 blob，不内联正文 —— 一律 binary（与 AI 对话驻留语义一致）。
              binary: true,
              truncated: false,
              workspace_path: res.path,
              size_bytes: res.size_bytes,
              thumb_path: res.thumb_path,
            } satisfies StoredAttachment;
          }),
        );
      } catch (err) {
        set({ sendError: messagingErrorMessage(err, "附件上传失败，请重试") });
        return;
      }
    }

    const contentType: SendContentType =
      attachments.length === 0
        ? "text"
        : attachments.every((a) => isImageAttachment(a.name))
          ? "image"
          : "file";

    const me = useAuthStore.getState().user;
    const optimistic: ChatMessageDetail = {
      id: `local:${clientMsgId}`,
      chat_id: chatId,
      sender_user_id: me?.id ?? null,
      sender_type: "user",
      content: text || null,
      content_type: contentType,
      attachments,
      payload: null,
      reply_to_message_id: replyToMessageId,
      reply_to: replySnapshot,
      mentions: mentionList ?? [],
      created_at: new Date().toISOString(),
    };

    set((s) => ({
      messagesByChat: {
        ...s.messagesByChat,
        [chatId]: [...(s.messagesByChat[chatId] ?? []), optimistic],
      },
      chats: bumpChat(
        s.chats,
        chatId,
        previewOf(optimistic),
        optimistic.created_at,
        0,
      ),
      sendError: null,
    }));

    try {
      const saved = await apiSendMessage(chatId, {
        content: text || undefined,
        contentType,
        attachments,
        clientMsgId,
        replyToMessageId: replyToMessageId ?? undefined,
        mentions: mentionList,
      });
      // Swap the optimistic twin for the stored message. The firehose also
      // delivers this same message (sender included, multi-device) — dedupe by
      // id keeps it from doubling up.
      set((s) => {
        const list = s.messagesByChat[chatId] ?? [];
        const withoutOptimistic = list.filter((m) => m.id !== optimistic.id);
        const exists = withoutOptimistic.some((m) => m.id === saved.id);
        return {
          messagesByChat: {
            ...s.messagesByChat,
            [chatId]: exists
              ? withoutOptimistic
              : [...withoutOptimistic, saved],
          },
        };
      });
    } catch (err) {
      // Roll back the optimistic message and surface a zh error for the composer.
      set((s) => ({
        messagesByChat: {
          ...s.messagesByChat,
          [chatId]: (s.messagesByChat[chatId] ?? []).filter(
            (m) => m.id !== optimistic.id,
          ),
        },
        sendError: messagingErrorMessage(err, "发送失败，请重试"),
      }));
    }
  },

  markChatRead: async (chatId) => {
    // Clear the local unread badge immediately (optimistic), then persist the
    // cursor to the newest known message. No messages yet → just clear the badge.
    set((s) => {
      const mentionAlertByChat = { ...s.mentionAlertByChat };
      delete mentionAlertByChat[chatId];
      return {
        chats: s.chats.map((c) => (c.id === chatId ? { ...c, unread: 0 } : c)),
        mentionAlertByChat,
      };
    });
    const list = get().messagesByChat[chatId];
    const last = list?.[list.length - 1];
    if (!last || last.id.startsWith("local:")) return;
    try {
      await markRead(chatId, last.id);
    } catch {
      /* best-effort — the badge already cleared locally */
    }
  },

  setMembershipFlags: async (chatId, flags) => {
    const prev = get().chats.find((c) => c.id === chatId);
    // Optimistic: reflect the toggle immediately (drives the list pin/mute icons).
    set((s) => ({
      chats: s.chats.map((c) => (c.id === chatId ? { ...c, ...flags } : c)),
    }));
    try {
      const updated = await updateMembership(chatId, flags);
      set((s) => ({
        chats: s.chats.map((c) => (c.id === chatId ? updated : c)),
      }));
    } catch {
      // Roll back to the pre-toggle row so the UI never lies about persisted state.
      if (prev) {
        set((s) => ({
          chats: s.chats.map((c) => (c.id === chatId ? prev : c)),
        }));
      }
    }
  },

  leaveChat: async (chatId) => {
    try {
      await apiLeaveChat(chatId);
    } catch (err) {
      set({ sendError: messagingErrorMessage(err, "退出失败，请重试") });
      return false;
    }
    set((s) => {
      const messagesByChat = { ...s.messagesByChat };
      delete messagesByChat[chatId];
      const messagesMetaByChat = { ...s.messagesMetaByChat };
      delete messagesMetaByChat[chatId];
      const membersByChat = { ...s.membersByChat };
      delete membersByChat[chatId];
      const mentionAlertByChat = { ...s.mentionAlertByChat };
      delete mentionAlertByChat[chatId];
      return {
        chats: s.chats.filter((c) => c.id !== chatId),
        messagesByChat,
        messagesMetaByChat,
        membersByChat,
        mentionAlertByChat,
        activeChatId: s.activeChatId === chatId ? null : s.activeChatId,
      };
    });
    return true;
  },

  kickMember: async (chatId, userId) => {
    await apiKickMember(chatId, userId);
    // Drop the removed member from the roster (the kick system_card arrives via
    // the firehose and lands in the thread on its own).
    set((s) => ({
      membersByChat: {
        ...s.membersByChat,
        [chatId]: (s.membersByChat[chatId] ?? []).filter(
          (m) => m.id !== userId,
        ),
      },
    }));
  },

  setAdminMute: async (chatId, userId, muted) => {
    await apiMuteMember(chatId, userId, muted);
    set((s) => ({
      membersByChat: {
        ...s.membersByChat,
        [chatId]: (s.membersByChat[chatId] ?? []).map((m) =>
          m.id === userId ? { ...m, muted_by_admin: muted } : m,
        ),
      },
    }));
  },

  announce: async (chatId, content) => {
    const message = await apiAnnounce(chatId, content);
    // Mirror it into the open thread immediately; applyIncoming dedupes by id so
    // the firehose copy (admin is a member, so it fans back) won't double up.
    get().applyIncoming(chatId, message);
  },

  upsertChat: (chat) =>
    set((s) => {
      const idx = s.chats.findIndex((c) => c.id === chat.id);
      if (idx === -1) return { chats: [chat, ...s.chats] };
      const next = [...s.chats];
      next[idx] = { ...next[idx], ...chat };
      return { chats: next };
    }),

  applyIncoming: (chatId, message) => {
    const known = get().chats.some((c) => c.id === chatId);
    const me = useAuthStore.getState().user?.id ?? null;
    const isMine =
      message.sender_user_id !== null && message.sender_user_id === me;
    const active = get().activeChatId === chatId;
    const chatBefore = get().chats.find((c) => c.id === chatId);
    const mentioned = !isMine && !active && messageMentionsUser(message, me);
    const mutedMention = mentioned && !!chatBefore?.muted;

    set((s) => {
      const list = s.messagesByChat[chatId];
      // Only merge into an already-loaded slice; an unopened chat re-syncs from
      // the server when the user opens it (离线补偿 on open). Dedupe by id.
      const messagesByChat =
        list && !list.some((m) => m.id === message.id)
          ? { ...s.messagesByChat, [chatId]: [...list, message] }
          : s.messagesByChat;

      const incUnread = active || isMine ? 0 : 1;
      const chats = bumpChat(
        s.chats,
        chatId,
        previewOf(message),
        message.created_at,
        incUnread,
      );
      const mentionAlertByChat =
        mutedMention && incUnread > 0
          ? { ...s.mentionAlertByChat, [chatId]: true }
          : s.mentionAlertByChat;
      return { messagesByChat, chats, mentionAlertByChat };
    });

    // 静音 × 被 @: weak desktop toast (可点进会话); no modal.
    if (mutedMention) {
      const label = chatBefore ? chatDisplayName(chatBefore) : "会话";
      notifyInfo(`${label} 有人提到了你`, {
        action: {
          label: "查看",
          onClick: () => {
            window.location.hash = `#/messages/${chatId}`;
          },
        },
      });
    }

    // A message for a chat we don't know yet (a new incoming request): pull the
    // list so the row appears. Done outside set() to avoid a nested update.
    if (!known) void get().fetchChats();
  },

  applyPresence: (userId, online) => {
    set((s) => {
      const chats = s.chats.map((c) => {
        if (c.peer?.id !== userId) return c;
        if (!!c.peer.online === online) return c;
        return { ...c, peer: { ...c.peer, online } };
      });
      const membersByChat: Record<string, ChatParticipant[]> = {};
      for (const [chatId, members] of Object.entries(s.membersByChat)) {
        let changed = false;
        const next = members.map((m) => {
          if (m.id !== userId || !!m.online === online) return m;
          changed = true;
          return { ...m, online };
        });
        membersByChat[chatId] = changed ? next : members;
      }
      return { chats, membersByChat };
    });
  },

  clearSendError: () => set({ sendError: null }),
}));

// --- Selectors ---

export const useChats = (): ChatSummary[] => useMessagingStore((s) => s.chats);

export function useActiveMessages(): ChatMessageDetail[] {
  return useMessagingStore((s) =>
    s.activeChatId
      ? (s.messagesByChat[s.activeChatId] ?? EMPTY_MESSAGES)
      : EMPTY_MESSAGES,
  );
}

export function useActiveChat(): ChatSummary | null {
  return useMessagingStore(
    (s) => s.chats.find((c) => c.id === s.activeChatId) ?? null,
  );
}

/** A chat's member roster (stable empty array until loaded). */
export function useChatMembers(chatId: string | null): ChatParticipant[] {
  return useMessagingStore((s) =>
    chatId ? (s.membersByChat[chatId] ?? EMPTY_MEMBERS) : EMPTY_MEMBERS,
  );
}

/** Total unread across non-muted chats — drives the sidebar 消息 badge. */
export function useUnreadTotal(): number {
  return useMessagingStore((s) =>
    s.chats.reduce((sum, c) => sum + (c.muted ? 0 : c.unread), 0),
  );
}
