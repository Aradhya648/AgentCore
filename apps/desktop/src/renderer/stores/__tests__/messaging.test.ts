import { useMessagingStore } from "@/stores/messaging";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/services/messaging", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/services/messaging")>();
  return {
    ...actual,
    listMessages: vi.fn(),
    sendMessage: vi.fn(),
  };
});

vi.mock("@/stores/auth", () => ({
  useAuthStore: {
    getState: () => ({
      user: { id: "me", displayName: "Me", username: "me", role: "user" },
    }),
  },
}));

vi.mock("@/lib/toast", () => ({
  notifyInfo: vi.fn(),
}));

import { notifyInfo } from "@/lib/toast";
import { listMessages, sendMessage } from "@/services/messaging";

const listMessagesMock = vi.mocked(listMessages);
const sendMessageMock = vi.mocked(sendMessage);

function msg(id: string, at: string) {
  return {
    id,
    chat_id: "c1",
    sender_user_id: "u1",
    sender_type: "user" as const,
    content: id,
    content_type: "text" as const,
    attachments: [],
    payload: null,
    reply_to_message_id: null,
    reply_to: null,
    mentions: [],
    created_at: at,
  };
}

describe("messaging store pagination", () => {
  beforeEach(() => {
    useMessagingStore.setState({
      messagesByChat: {},
      messagesMetaByChat: {},
      loadingMessages: {},
      loadingOlderMessages: {},
    });
    listMessagesMock.mockReset();
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it("loadMessages lands on the last page when history spans multiple pages", async () => {
    listMessagesMock
      .mockResolvedValueOnce({
        messages: [msg("m1", "2026-01-01T00:00:00Z")],
        total: 120,
        page: 1,
        pageSize: 50,
      })
      .mockResolvedValueOnce({
        messages: [
          msg("m101", "2026-01-02T00:00:00Z"),
          msg("m120", "2026-01-03T00:00:00Z"),
        ],
        total: 120,
        page: 3,
        pageSize: 50,
      });

    await useMessagingStore.getState().loadMessages("c1");

    const state = useMessagingStore.getState();
    expect(state.messagesByChat.c1?.map((m) => m.id)).toEqual(["m101", "m120"]);
    expect(state.messagesMetaByChat.c1).toEqual({
      oldestPage: 3,
      total: 120,
      hasMoreOlder: true,
    });
  });

  it("loadOlderMessages prepends the previous page and dedupes", async () => {
    useMessagingStore.setState({
      messagesByChat: {
        c1: [msg("m51", "2026-01-02T00:00:00Z")],
      },
      messagesMetaByChat: {
        c1: { oldestPage: 2, total: 80, hasMoreOlder: true },
      },
    });

    listMessagesMock.mockResolvedValueOnce({
      messages: [
        msg("m1", "2026-01-01T00:00:00Z"),
        msg("m51", "2026-01-02T00:00:00Z"),
      ],
      total: 80,
      page: 1,
      pageSize: 50,
    });

    await useMessagingStore.getState().loadOlderMessages("c1");

    const state = useMessagingStore.getState();
    expect(state.messagesByChat.c1?.map((m) => m.id)).toEqual(["m1", "m51"]);
    expect(state.messagesMetaByChat.c1).toEqual({
      oldestPage: 1,
      total: 80,
      hasMoreOlder: false,
    });
  });
});

describe("messaging store presence", () => {
  beforeEach(() => {
    useMessagingStore.setState({
      chats: [],
      membersByChat: {},
    });
  });

  it("applyPresence flips dm peer and roster online flags", () => {
    useMessagingStore.setState({
      chats: [
        {
          id: "dm1",
          type: "dm",
          title: null,
          avatar_url: null,
          peer: {
            id: "u2",
            username: "bob",
            display_name: "Bob",
            is_admin: false,
            muted_by_admin: false,
            online: false,
          },
          last_message_at: null,
          last_message_preview: null,
          unread: 0,
          pinned: false,
          muted: false,
          state: "accepted",
        },
      ],
      membersByChat: {
        g1: [
          {
            id: "u2",
            username: "bob",
            display_name: "Bob",
            is_admin: false,
            muted_by_admin: false,
            online: false,
          },
          {
            id: "u3",
            username: "carol",
            display_name: "Carol",
            is_admin: false,
            muted_by_admin: false,
            online: true,
          },
        ],
      },
    });

    useMessagingStore.getState().applyPresence("u2", true);

    const state = useMessagingStore.getState();
    expect(state.chats[0]?.peer?.online).toBe(true);
    expect(state.membersByChat.g1?.find((m) => m.id === "u2")?.online).toBe(
      true,
    );
    expect(state.membersByChat.g1?.find((m) => m.id === "u3")?.online).toBe(
      true,
    );

    useMessagingStore.getState().applyPresence("u2", false);
    expect(useMessagingStore.getState().chats[0]?.peer?.online).toBe(false);
  });
});

describe("messaging store send reply", () => {
  beforeEach(() => {
    useMessagingStore.setState({
      chats: [
        {
          id: "c1",
          type: "dm",
          title: null,
          avatar_url: null,
          peer: {
            id: "u2",
            username: "bob",
            display_name: "Bob",
            is_admin: false,
            muted_by_admin: false,
            online: false,
          },
          last_message_at: null,
          last_message_preview: null,
          unread: 0,
          pinned: false,
          muted: false,
          state: "accepted",
        },
      ],
      messagesByChat: { c1: [] },
      sendError: null,
    });
    sendMessageMock.mockReset();
  });

  it("passes replyToMessageId and keeps optimistic reply_to snapshot", async () => {
    const snapshot = {
      sender_user_id: "u2",
      sender_display_name: "Bob",
      body_preview: "earlier",
    };
    sendMessageMock.mockResolvedValueOnce({
      id: "server-1",
      chat_id: "c1",
      sender_user_id: "me",
      sender_type: "user",
      content: "reply body",
      content_type: "text",
      attachments: [],
      payload: null,
      reply_to_message_id: "m-target",
      reply_to: snapshot,
      created_at: "2026-01-01T01:00:00Z",
    });

    await useMessagingStore.getState().sendMessage("c1", "reply body", [], {
      messageId: "m-target",
      snapshot,
    });

    expect(sendMessageMock).toHaveBeenCalledWith("c1", {
      content: "reply body",
      contentType: "text",
      attachments: [],
      clientMsgId: expect.any(String),
      replyToMessageId: "m-target",
    });
    const list = useMessagingStore.getState().messagesByChat.c1 ?? [];
    expect(list).toHaveLength(1);
    expect(list[0]?.id).toBe("server-1");
    expect(list[0]?.reply_to_message_id).toBe("m-target");
    expect(list[0]?.reply_to).toEqual(snapshot);
  });

  it("passes mentions on send and keeps optimistic mentions", async () => {
    const mentions = [{ kind: "user" as const, user_id: "u2" }];
    sendMessageMock.mockResolvedValueOnce({
      id: "server-2",
      chat_id: "c1",
      sender_user_id: "me",
      sender_type: "user",
      content: "hi @Bob",
      content_type: "text",
      attachments: [],
      payload: null,
      reply_to_message_id: null,
      reply_to: null,
      mentions,
      created_at: "2026-01-01T02:00:00Z",
    });

    await useMessagingStore
      .getState()
      .sendMessage("c1", "hi @Bob", [], null, mentions);

    expect(sendMessageMock).toHaveBeenCalledWith("c1", {
      content: "hi @Bob",
      contentType: "text",
      attachments: [],
      clientMsgId: expect.any(String),
      replyToMessageId: undefined,
      mentions,
    });
    const list = useMessagingStore.getState().messagesByChat.c1 ?? [];
    expect(list[0]?.mentions).toEqual(mentions);
  });
});

describe("messaging store muted mention alert", () => {
  beforeEach(() => {
    useMessagingStore.setState({
      chats: [
        {
          id: "g1",
          type: "group",
          title: "内测群",
          avatar_url: null,
          peer: null,
          last_message_at: null,
          last_message_preview: null,
          unread: 0,
          pinned: false,
          muted: true,
          state: "accepted",
        },
      ],
      messagesByChat: { g1: [] },
      mentionAlertByChat: {},
      activeChatId: null,
    });
    vi.mocked(notifyInfo).mockReset();
  });

  it("flags mentionAlert and toasts when muted chat @mentions me", () => {
    useMessagingStore.getState().applyIncoming("g1", {
      id: "m-at",
      chat_id: "g1",
      sender_user_id: "u2",
      sender_type: "user",
      content: "hey @Me",
      content_type: "text",
      attachments: [],
      payload: null,
      reply_to_message_id: null,
      reply_to: null,
      mentions: [{ kind: "user", user_id: "me" }],
      created_at: "2026-01-01T03:00:00Z",
    });

    const state = useMessagingStore.getState();
    expect(state.mentionAlertByChat.g1).toBe(true);
    expect(state.chats[0]?.unread).toBe(1);
    expect(notifyInfo).toHaveBeenCalledWith(
      "内测群 有人提到了你",
      expect.objectContaining({
        action: expect.objectContaining({ label: "查看" }),
      }),
    );
  });

  it("does not toast for muted chat without mentions", () => {
    useMessagingStore.getState().applyIncoming("g1", {
      id: "m-plain",
      chat_id: "g1",
      sender_user_id: "u2",
      sender_type: "user",
      content: "plain",
      content_type: "text",
      attachments: [],
      payload: null,
      reply_to_message_id: null,
      reply_to: null,
      mentions: [],
      created_at: "2026-01-01T03:00:00Z",
    });

    expect(useMessagingStore.getState().mentionAlertByChat.g1).toBeUndefined();
    expect(notifyInfo).not.toHaveBeenCalled();
  });
});
