import { useMessagingStore } from "@/stores/messaging";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/services/messaging", () => ({
  listMessages: vi.fn(),
}));

import { listMessages } from "@/services/messaging";

const listMessagesMock = vi.mocked(listMessages);

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
