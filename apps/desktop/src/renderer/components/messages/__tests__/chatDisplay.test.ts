import type { ChatMessageDetail, ChatSummary } from "@/services/messaging";
import { describe, expect, it } from "vitest";
import {
  EVERYONE_MENTION_LABEL,
  OFFICIAL_CHAT_DISPLAY_NAME,
  buildReplySnapshot,
  canOfferEdit,
  canOfferRecall,
  chatDisplayName,
  filterMentionsInContent,
  findImMentionDraft,
  findOfficialChatId,
  mentionAtToken,
  messageMentionsUser,
  replyBodyPreview,
  splitContentByMentions,
  truncateReplyPreview,
} from "../chatDisplay";

function chat(
  partial: Partial<ChatSummary> & Pick<ChatSummary, "id" | "type">,
): ChatSummary {
  return {
    muted: false,
    pinned: false,
    state: "accepted",
    unread: 0,
    ...partial,
  };
}

function msg(
  partial: Partial<ChatMessageDetail> & Pick<ChatMessageDetail, "id">,
): ChatMessageDetail {
  return {
    chat_id: "c1",
    sender_user_id: "u1",
    sender_type: "user",
    content: null,
    content_type: "text",
    attachments: [],
    payload: null,
    reply_to_message_id: null,
    reply_to: null,
    mentions: [],
    recalled_at: null,
    recalled_by_user_id: null,
    edited_at: null,
    created_at: "2026-01-01T00:00:00Z",
    ...partial,
  };
}

describe("chatDisplayName", () => {
  it("brands the official broadcast chat", () => {
    expect(
      chatDisplayName(chat({ id: "o1", type: "official", title: "官方号" })),
    ).toBe(OFFICIAL_CHAT_DISPLAY_NAME);
  });

  it("uses peer name for dms", () => {
    expect(
      chatDisplayName(
        chat({
          id: "d1",
          type: "dm",
          peer: {
            id: "u1",
            username: "alice",
            display_name: "Alice",
            online: false,
            is_admin: false,
            muted_by_admin: false,
          },
        }),
      ),
    ).toBe("Alice");
  });
});

describe("findOfficialChatId", () => {
  it("returns the official chat id when present", () => {
    const chats = [
      chat({ id: "g1", type: "group", title: "内测群" }),
      chat({ id: "o1", type: "official", pinned: true }),
    ];
    expect(findOfficialChatId(chats)).toBe("o1");
  });

  it("returns null when absent", () => {
    expect(findOfficialChatId([chat({ id: "g1", type: "group" })])).toBeNull();
  });
});

describe("reply preview helpers", () => {
  it("truncates long text with an ellipsis", () => {
    const long = "a".repeat(100);
    expect(truncateReplyPreview(long).endsWith("…")).toBe(true);
    expect(truncateReplyPreview(long).length).toBe(81);
  });

  it("uses attachment labels when content is empty", () => {
    expect(
      replyBodyPreview(
        msg({
          id: "m1",
          content_type: "image",
          attachments: [
            {
              name: "a.png",
              path: "a.png",
              kind: "file",
              binary: true,
              truncated: false,
              workspace_path: "attachments/a.png",
            },
          ],
        }),
      ),
    ).toBe("[图片]");
    expect(
      replyBodyPreview(
        msg({
          id: "m2",
          content_type: "file",
          attachments: [
            {
              name: "doc.pdf",
              path: "doc.pdf",
              kind: "file",
              binary: true,
              truncated: false,
              workspace_path: "attachments/doc.pdf",
            },
          ],
        }),
      ),
    ).toBe("[文件]");
  });

  it("builds a local reply snapshot from the target message", () => {
    expect(
      buildReplySnapshot(
        msg({ id: "m3", content: "hello world", sender_user_id: "u2" }),
        "Bob",
      ),
    ).toEqual({
      sender_user_id: "u2",
      sender_display_name: "Bob",
      body_preview: "hello world",
    });
  });

  it("uses withdrawn label for recalled targets", () => {
    expect(
      replyBodyPreview(
        msg({
          id: "m-r",
          content: null,
          recalled_at: "2026-01-01T00:01:00Z",
        }),
      ),
    ).toBe("[已撤回]");
  });
});

describe("canOfferRecall", () => {
  it("allows own message within the window", () => {
    const recent = msg({
      id: "m1",
      created_at: new Date().toISOString(),
    });
    expect(
      canOfferRecall(recent, { mine: true, isAdmin: false, chatType: "dm" }),
    ).toBe(true);
  });

  it("denies own message after the window", () => {
    const old = msg({
      id: "m2",
      created_at: "2020-01-01T00:00:00Z",
    });
    expect(
      canOfferRecall(old, { mine: true, isAdmin: false, chatType: "dm" }),
    ).toBe(false);
  });

  it("allows admin to recall group member messages", () => {
    const old = msg({
      id: "m3",
      created_at: "2020-01-01T00:00:00Z",
    });
    expect(
      canOfferRecall(old, { mine: false, isAdmin: true, chatType: "group" }),
    ).toBe(true);
  });

  it("restricts system_card to admin", () => {
    const card = msg({
      id: "m4",
      content_type: "system_card",
      created_at: new Date().toISOString(),
    });
    expect(
      canOfferRecall(card, { mine: true, isAdmin: false, chatType: "group" }),
    ).toBe(false);
    expect(
      canOfferRecall(card, { mine: false, isAdmin: true, chatType: "group" }),
    ).toBe(true);
  });
});

describe("canOfferEdit", () => {
  it("allows own recent plain-text message", () => {
    const m = msg({
      id: "e1",
      content: "hello",
      created_at: new Date().toISOString(),
    });
    expect(canOfferEdit(m, { mine: true, chatType: "dm" })).toBe(true);
  });

  it("refuses attachments, recalled, others, and timeout", () => {
    expect(
      canOfferEdit(
        msg({
          id: "e2",
          content: "x",
          attachments: [{ name: "a.png", path: "a.png" }],
          created_at: new Date().toISOString(),
        }),
        { mine: true, chatType: "dm" },
      ),
    ).toBe(false);
    expect(
      canOfferEdit(
        msg({
          id: "e3",
          content: "x",
          recalled_at: new Date().toISOString(),
          created_at: new Date().toISOString(),
        }),
        { mine: true, chatType: "dm" },
      ),
    ).toBe(false);
    expect(
      canOfferEdit(
        msg({
          id: "e4",
          content: "x",
          created_at: new Date().toISOString(),
        }),
        { mine: false, chatType: "dm" },
      ),
    ).toBe(false);
    expect(
      canOfferEdit(
        msg({
          id: "e5",
          content: "x",
          created_at: "2020-01-01T00:00:00Z",
        }),
        { mine: true, chatType: "dm" },
      ),
    ).toBe(false);
  });
});

describe("IM mention helpers", () => {
  const names = (id: string) => ({ u1: "Alice", u2: "Bob", me: "Me" })[id];

  it("detects user and everyone mentions", () => {
    expect(
      messageMentionsUser(
        { mentions: [{ kind: "user", user_id: "me" }] },
        "me",
      ),
    ).toBe(true);
    expect(
      messageMentionsUser(
        { mentions: [{ kind: "user", user_id: "u1" }] },
        "me",
      ),
    ).toBe(false);
    expect(
      messageMentionsUser({ mentions: [{ kind: "everyone" }] }, "me"),
    ).toBe(true);
    expect(messageMentionsUser({ mentions: undefined }, "me")).toBe(false);
  });

  it("builds @ tokens and filters deleted body tokens", () => {
    expect(mentionAtToken({ kind: "everyone" }, names)).toBe(
      `@${EVERYONE_MENTION_LABEL}`,
    );
    expect(mentionAtToken({ kind: "user", user_id: "u1" }, names)).toBe(
      "@Alice",
    );
    expect(
      filterMentionsInContent(
        "hi @Alice and more",
        [
          { kind: "user", user_id: "u1" },
          { kind: "user", user_id: "u2" },
          { kind: "everyone" },
        ],
        names,
      ),
    ).toEqual([{ kind: "user", user_id: "u1" }]);
  });

  it("splits content by structured mention tokens", () => {
    const segments = splitContentByMentions(
      "hey @Alice see @所有人",
      [{ kind: "user", user_id: "u1" }, { kind: "everyone" }],
      names,
      "me",
    );
    expect(segments).toEqual([
      { type: "text", text: "hey " },
      { type: "mention", text: "@Alice", self: false },
      { type: "text", text: " see " },
      { type: "mention", text: "@所有人", self: true },
    ]);
  });

  it("finds an active @ draft at the caret", () => {
    expect(findImMentionDraft("hello @Al", 9)).toEqual({
      start: 6,
      end: 9,
      query: "Al",
    });
    expect(findImMentionDraft("hello@Al", 8)).toBeNull();
    expect(findImMentionDraft("@", 1)).toEqual({
      start: 0,
      end: 1,
      query: "",
    });
  });
});
