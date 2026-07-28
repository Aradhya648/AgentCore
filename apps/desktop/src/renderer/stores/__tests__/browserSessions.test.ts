import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/services/browserSessions", () => ({
  listBrowserSessions: vi.fn(),
  closeBrowserSession: vi.fn(),
}));

import {
  closeBrowserSession,
  listBrowserSessions,
} from "@/services/browserSessions";
import {
  mergeHydratedPages,
  normalizeBrowserUrl,
  serverPageId,
  useBrowserSessionsStore,
} from "../browserSessions";

const store = () => useBrowserSessionsStore.getState();
const listMock = vi.mocked(listBrowserSessions);
const closeMock = vi.mocked(closeBrowserSession);

beforeEach(() => {
  useBrowserSessionsStore.setState({ pages: [], activePageId: null });
  listMock.mockReset();
  closeMock.mockReset();
});

describe("normalizeBrowserUrl", () => {
  it("keeps absolute URLs", () => {
    expect(normalizeBrowserUrl("https://example.com/a")).toBe(
      "https://example.com/a",
    );
  });

  it("adds https for bare hosts", () => {
    expect(normalizeBrowserUrl("example.com")).toBe("https://example.com");
  });

  it("returns empty for blank input", () => {
    expect(normalizeBrowserUrl("  ")).toBe("");
  });
});

describe("browserSessions store", () => {
  it("createPage adds a blank page and activates it (no serverSessionId)", () => {
    const id = store().createPage({ conversationId: "c1" });
    expect(store().pages).toHaveLength(1);
    expect(store().pages[0]).toMatchObject({
      id,
      url: "",
      title: "新标签页",
      conversationId: "c1",
      serverSessionId: null,
    });
    expect(store().activePageId).toBe(id);
  });

  it("ensureBlankPage is a no-op when pages already exist", () => {
    const id = store().createPage({ conversationId: "c1" });
    expect(store().ensureBlankPage("c1")).toBe(id);
    expect(store().pages).toHaveLength(1);
  });

  it("ensureBlankPage creates when empty", () => {
    const id = store().ensureBlankPage("c1");
    expect(store().pages).toHaveLength(1);
    expect(store().activePageId).toBe(id);
  });

  it("scopes pages by conversationId", () => {
    store().createPage({ conversationId: "c1", title: "A" });
    store().createPage({ conversationId: "c2", title: "B" });
    expect(store().pagesFor("c1")).toHaveLength(1);
    expect(store().pagesFor("c2")).toHaveLength(1);
    expect(store().pagesFor(null)).toHaveLength(0);
  });

  it("navigatePage updates url and title", () => {
    const id = store().createPage({ conversationId: "c1" });
    store().navigatePage(id, "example.com/x");
    expect(store().pages[0]).toMatchObject({
      url: "https://example.com/x",
      title: "example.com",
    });
  });

  it("closePage recreates a blank page when closing the last one", () => {
    const id = store().createPage({ conversationId: "c1" });
    store().closePage(id);
    expect(store().pagesFor("c1")).toHaveLength(1);
    expect(store().pagesFor("c1")[0]!.url).toBe("");
    expect(store().pagesFor("c1")[0]!.id).not.toBe(id);
  });

  it("closePage activates a sibling", () => {
    const a = store().createPage({ conversationId: "c1", title: "A" });
    const b = store().createPage({ conversationId: "c1", title: "B" });
    expect(store().activePageId).toBe(b);
    store().closePage(b);
    expect(store().activePageId).toBe(a);
    expect(store().pagesFor("c1")).toHaveLength(1);
  });
});

describe("mergeHydratedPages", () => {
  it("keeps local blanks, projects server sessions, drops stale server pages", () => {
    const blankId = "local-blank";
    const staleServerId = serverPageId("gone");
    const keepServerId = serverPageId("alive");
    const all = [
      {
        id: blankId,
        url: "",
        title: "新标签页",
        conversationId: "c1",
        serverSessionId: null,
      },
      {
        id: staleServerId,
        url: "",
        title: "旧",
        conversationId: "c1",
        serverSessionId: "gone",
        hostKind: "sandbox" as const,
        control: "agent" as const,
      },
      {
        id: keepServerId,
        url: "",
        title: "旧标题",
        conversationId: "c1",
        serverSessionId: "alive",
        hostKind: "sandbox" as const,
        control: "agent" as const,
      },
      {
        id: "other-conv",
        url: "",
        title: "X",
        conversationId: "c2",
        serverSessionId: null,
      },
    ];

    const { pages, activePageId } = mergeHydratedPages(
      all,
      "c1",
      [
        {
          sessionId: "alive",
          conversationId: "c1",
          hostKind: "sandbox",
          control: "user",
          runId: null,
          createdAt: 1,
          lastUsed: 2,
        },
        {
          sessionId: "newone",
          conversationId: "c1",
          hostKind: "local",
          control: "agent",
          runId: null,
          createdAt: 3,
          lastUsed: 4,
        },
      ],
      "newone",
      blankId,
    );

    const c1 = pages.filter((p) => p.conversationId === "c1");
    expect(c1.map((p) => p.serverSessionId)).toEqual([null, "alive", "newone"]);
    expect(c1.find((p) => p.id === blankId)).toBeTruthy();
    expect(c1.find((p) => p.serverSessionId === "gone")).toBeUndefined();
    expect(c1.find((p) => p.serverSessionId === "alive")?.control).toBe("user");
    expect(pages.find((p) => p.id === "other-conv")).toBeTruthy();
    expect(activePageId).toBe(serverPageId("newone"));
  });
});

describe("hydrateConversation", () => {
  it("merges list into tabs and prefers active_session_id", async () => {
    store().createPage({ conversationId: "c1", title: "新标签页" });
    listMock.mockResolvedValue({
      sessions: [
        {
          sessionId: "s1",
          conversationId: "c1",
          hostKind: "sandbox",
          control: "agent",
          runId: null,
          createdAt: 1,
          lastUsed: 1,
        },
      ],
      activeSessionId: "s1",
    });

    await store().hydrateConversation("c1");

    expect(listMock).toHaveBeenCalledWith("c1");
    const c1 = store().pagesFor("c1");
    expect(c1).toHaveLength(2); // blank + server
    expect(c1.some((p) => !p.serverSessionId)).toBe(true);
    expect(c1.some((p) => p.serverSessionId === "s1")).toBe(true);
    expect(store().activePageId).toBe(serverPageId("s1"));
  });
});

describe("closeServerPage", () => {
  it("DELETE then removes locally", async () => {
    const id = store().createPage({
      conversationId: "c1",
      title: "云端",
      serverSessionId: "s1",
      hostKind: "sandbox",
      control: "agent",
    });
    // keep a sibling so close doesn't only leave the recreated blank
    store().createPage({ conversationId: "c1", title: "本地" });
    closeMock.mockResolvedValue(undefined);

    await store().closeServerPage(id);

    expect(closeMock).toHaveBeenCalledWith("c1", "s1");
    expect(store().pagesFor("c1").some((p) => p.id === id)).toBe(false);
  });

  it("does not remove locally when DELETE fails", async () => {
    const id = store().createPage({
      conversationId: "c1",
      title: "云端",
      serverSessionId: "s1",
      hostKind: "sandbox",
    });
    closeMock.mockRejectedValue(new Error("boom"));

    await expect(store().closeServerPage(id)).rejects.toThrow("boom");
    expect(store().pages.some((p) => p.id === id)).toBe(true);
  });
});

describe("blank pages never create server sessions", () => {
  it("createPage / ensureBlankPage do not call list or close APIs", () => {
    store().ensureBlankPage("c1");
    store().createPage({ conversationId: "c1" });
    expect(listMock).not.toHaveBeenCalled();
    expect(closeMock).not.toHaveBeenCalled();
    expect(
      store().pages.every(
        (p) => p.serverSessionId == null || p.serverSessionId === "",
      ),
    ).toBe(true);
  });
});
