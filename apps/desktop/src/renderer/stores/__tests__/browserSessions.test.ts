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
  hostBrowserPageId,
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

describe("hostBrowserPageId", () => {
  it("uses bare serverSessionId when present", () => {
    expect(
      hostBrowserPageId({
        id: "browser-server:sess-1",
        serverSessionId: "sess-1",
      }),
    ).toBe("sess-1");
  });

  it("falls back to React page id for local blanks", () => {
    expect(
      hostBrowserPageId({ id: "browser-page:1:uuid", serverSessionId: null }),
    ).toBe("browser-page:1:uuid");
  });
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
    expect(store().pagesFor("c1")[0]?.url).toBe("");
    expect(store().pagesFor("c1")[0]?.id).not.toBe(id);
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
          url: "https://alive.example/",
          title: "Alive Title",
        },
        {
          sessionId: "newone",
          conversationId: "c1",
          hostKind: "local",
          control: "agent",
          runId: null,
          createdAt: 3,
          lastUsed: 4,
          url: "https://new.example/",
          title: "New Page",
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
    expect(c1.find((p) => p.serverSessionId === "alive")?.url).toBe(
      "https://alive.example/",
    );
    expect(c1.find((p) => p.serverSessionId === "alive")?.title).toBe(
      "Alive Title",
    );
    expect(c1.find((p) => p.serverSessionId === "newone")?.url).toBe(
      "https://new.example/",
    );
    expect(c1.find((p) => p.serverSessionId === "newone")?.title).toBe(
      "New Page",
    );
    expect(pages.find((p) => p.id === "other-conv")).toBeTruthy();
    expect(activePageId).toBe(serverPageId("newone"));
  });

  it("prefers server url/title over empty prev when hydrating", () => {
    const sid = "agent-nav";
    const { pages } = mergeHydratedPages(
      [
        {
          id: serverPageId(sid),
          url: "",
          title: "浏览器 · local · agent-na",
          conversationId: "c1",
          serverSessionId: sid,
          hostKind: "local",
          control: "agent",
        },
      ],
      "c1",
      [
        {
          sessionId: sid,
          conversationId: "c1",
          hostKind: "local",
          control: "agent",
          runId: null,
          createdAt: 1,
          lastUsed: 2,
          url: "https://example.com/from-agent",
          title: "From Agent",
        },
      ],
      sid,
      serverPageId(sid),
    );
    const page = pages.find((p) => p.serverSessionId === sid);
    expect(page).toBeDefined();
    if (!page) throw new Error("expected page");
    expect(page.url).toBe("https://example.com/from-agent");
    expect(page.title).toBe("From Agent");
  });

  it("switches off local blank when sessions exist even without activeSessionId", () => {
    const blankId = "local-blank";
    const { activePageId, pages } = mergeHydratedPages(
      [
        {
          id: blankId,
          url: "",
          title: "新标签页",
          conversationId: "c1",
          serverSessionId: null,
        },
      ],
      "c1",
      [
        {
          sessionId: "only",
          conversationId: "c1",
          hostKind: "local",
          control: "agent",
          runId: null,
          createdAt: 1,
          lastUsed: 2,
          url: "https://only.example/",
          title: "Only",
        },
      ],
      null,
      blankId,
    );
    expect(pages.some((p) => p.id === blankId)).toBe(true);
    expect(activePageId).toBe(serverPageId("only"));
  });

  it("with multiple sessions and null activeSessionId, picks the last server page over blank", () => {
    const blankId = "local-blank";
    const { activePageId } = mergeHydratedPages(
      [
        {
          id: blankId,
          url: "",
          title: "新标签页",
          conversationId: "c1",
          serverSessionId: null,
        },
      ],
      "c1",
      [
        {
          sessionId: "a",
          conversationId: "c1",
          hostKind: "local",
          control: "agent",
          runId: null,
          createdAt: 1,
          lastUsed: 1,
        },
        {
          sessionId: "b",
          conversationId: "c1",
          hostKind: "local",
          control: "agent",
          runId: null,
          createdAt: 2,
          lastUsed: 2,
        },
      ],
      null,
      blankId,
    );
    expect(activePageId).toBe(serverPageId("b"));
  });

  it("keeps a non-blank prevActive when activeSessionId is null", () => {
    const serverA = serverPageId("a");
    const { activePageId } = mergeHydratedPages(
      [
        {
          id: serverA,
          url: "https://a.example/",
          title: "A",
          conversationId: "c1",
          serverSessionId: "a",
          hostKind: "local",
          control: "agent",
        },
      ],
      "c1",
      [
        {
          sessionId: "a",
          conversationId: "c1",
          hostKind: "local",
          control: "agent",
          runId: null,
          createdAt: 1,
          lastUsed: 1,
        },
        {
          sessionId: "b",
          conversationId: "c1",
          hostKind: "local",
          control: "agent",
          runId: null,
          createdAt: 2,
          lastUsed: 2,
        },
      ],
      null,
      serverA,
    );
    expect(activePageId).toBe(serverA);
  });

  it("empty list keeps local server pages with blanks", () => {
    const blankId = "local-blank";
    const localSid = serverPageId("local-1");
    const { pages, activePageId } = mergeHydratedPages(
      [
        {
          id: blankId,
          url: "",
          title: "新标签页",
          conversationId: "c1",
          serverSessionId: null,
        },
        {
          id: localSid,
          url: "https://www.baidu.com/",
          title: "百度",
          conversationId: "c1",
          serverSessionId: "local-1",
          hostKind: "local",
          control: "agent",
        },
      ],
      "c1",
      [],
      null,
      localSid,
    );
    const c1 = pages.filter((p) => p.conversationId === "c1");
    expect(c1.map((p) => p.serverSessionId)).toEqual([null, "local-1"]);
    expect(c1.find((p) => p.serverSessionId === "local-1")?.url).toBe(
      "https://www.baidu.com/",
    );
    expect(activePageId).toBe(localSid);
  });

  it("empty list drops sandbox server pages", () => {
    const sandId = serverPageId("sand-1");
    const { pages } = mergeHydratedPages(
      [
        {
          id: sandId,
          url: "https://sand.example/",
          title: "Sand",
          conversationId: "c1",
          serverSessionId: "sand-1",
          hostKind: "sandbox",
          control: "agent",
        },
      ],
      "c1",
      [],
      null,
      sandId,
    );
    expect(
      pages.some(
        (p) => p.conversationId === "c1" && p.serverSessionId === "sand-1",
      ),
    ).toBe(false);
  });

  it("non-empty list still drops stale local server pages", () => {
    const stale = serverPageId("stale-local");
    const { pages } = mergeHydratedPages(
      [
        {
          id: stale,
          url: "https://stale.example/",
          title: "Stale",
          conversationId: "c1",
          serverSessionId: "stale-local",
          hostKind: "local",
          control: "agent",
        },
      ],
      "c1",
      [
        {
          sessionId: "alive",
          conversationId: "c1",
          hostKind: "local",
          control: "agent",
          runId: null,
          createdAt: 1,
          lastUsed: 1,
          url: "https://alive.example/",
        },
      ],
      "alive",
      stale,
    );
    expect(
      pages.find((p) => p.serverSessionId === "stale-local"),
    ).toBeUndefined();
    expect(pages.find((p) => p.serverSessionId === "alive")).toBeTruthy();
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
          url: "https://hydrated.example/",
          title: "Hydrated",
        },
      ],
      activeSessionId: "s1",
    });

    await store().hydrateConversation("c1");

    expect(listMock).toHaveBeenCalledWith("c1");
    const c1 = store().pagesFor("c1");
    expect(c1).toHaveLength(2); // blank + server
    expect(c1.some((p) => !p.serverSessionId)).toBe(true);
    const server = c1.find((p) => p.serverSessionId === "s1");
    expect(server).toMatchObject({
      url: "https://hydrated.example/",
      title: "Hydrated",
    });
    expect(store().activePageId).toBe(serverPageId("s1"));
  });

  it("activates server page over pre-existing local blank when activeSessionId is null", async () => {
    const blankId = store().createPage({
      conversationId: "c1",
      title: "新标签页",
    });
    expect(store().activePageId).toBe(blankId);
    listMock.mockResolvedValue({
      sessions: [
        {
          sessionId: "s-agent",
          conversationId: "c1",
          hostKind: "local",
          control: "agent",
          runId: null,
          createdAt: 1,
          lastUsed: 1,
          url: "https://agent.example/",
        },
      ],
      activeSessionId: null,
    });

    await store().hydrateConversation("c1");

    expect(store().activePageId).toBe(serverPageId("s-agent"));
    expect(
      store()
        .pagesFor("c1")
        .some((p) => p.serverSessionId === "s-agent"),
    ).toBe(true);
  });

  it("expired hydrate after upsert does not wipe server page", async () => {
    let resolveList!: (v: {
      sessions: Array<{
        sessionId: string;
        conversationId: string;
        hostKind: "sandbox" | "local";
        control: "agent" | "user";
        runId: string | null;
        createdAt: number;
        lastUsed: number;
        url?: string;
        title?: string;
      }>;
      activeSessionId: string | null;
    }) => void;
    listMock.mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveList = resolve;
        }),
    );

    const hydrateP = store().hydrateConversation("c1");
    await Promise.resolve();

    // sandbox：空 list merge 会清掉；仅靠 epoch 才能保住 upsert
    store().upsertServerSession("c1", {
      sessionId: "s-sand",
      hostKind: "sandbox",
      control: "agent",
      url: "https://example.com/",
      title: "Example",
    });
    expect(store().pages.some((p) => p.serverSessionId === "s-sand")).toBe(
      true,
    );

    resolveList({ sessions: [], activeSessionId: null });
    await hydrateP;

    expect(store().pages.some((p) => p.serverSessionId === "s-sand")).toBe(
      true,
    );
    expect(store().pages.find((p) => p.serverSessionId === "s-sand")?.url).toBe(
      "https://example.com/",
    );
  });

  it("second hydrate does not reuse first inflight empty result", async () => {
    const resolvers: Array<
      (v: {
        sessions: Array<{
          sessionId: string;
          conversationId: string;
          hostKind: "sandbox" | "local";
          control: "agent" | "user";
          runId: string | null;
          createdAt: number;
          lastUsed: number;
          url?: string;
        }>;
        activeSessionId: string | null;
      }) => void
    > = [];
    listMock.mockImplementation(
      () =>
        new Promise((resolve) => {
          resolvers.push(resolve);
        }),
    );

    const h1 = store().hydrateConversation("c1");
    await Promise.resolve();
    const h2 = store().hydrateConversation("c1");
    await Promise.resolve();

    expect(listMock).toHaveBeenCalledTimes(1);
    expect(resolvers).toHaveLength(1);

    resolvers[0]?.({ sessions: [], activeSessionId: null });
    await h1;
    await Promise.resolve();
    await Promise.resolve();

    expect(listMock).toHaveBeenCalledTimes(2);
    expect(resolvers).toHaveLength(2);

    resolvers[1]?.({
      sessions: [
        {
          sessionId: "s1",
          conversationId: "c1",
          hostKind: "local",
          control: "agent",
          runId: null,
          createdAt: 1,
          lastUsed: 1,
          url: "https://alive.example/",
        },
      ],
      activeSessionId: "s1",
    });
    await h2;

    expect(store().pages.some((p) => p.serverSessionId === "s1")).toBe(true);
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
    expect(
      store()
        .pagesFor("c1")
        .some((p) => p.id === id),
    ).toBe(false);
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

describe("upsertServerSession", () => {
  it("creates a server page with url and activates over local blank", () => {
    const blankId = store().ensureBlankPage("c1");
    expect(store().activePageId).toBe(blankId);

    store().upsertServerSession("c1", {
      sessionId: "sess-nav",
      hostKind: "local",
      control: "agent",
      url: "https://example.com/",
      title: "Example",
    });

    const page = store().pages.find((p) => p.serverSessionId === "sess-nav");
    expect(page).toMatchObject({
      url: "https://example.com/",
      title: "Example",
      hostKind: "local",
      serverSessionId: "sess-nav",
    });
    expect(page).toBeDefined();
    if (!page) throw new Error("expected server page");
    expect(hostBrowserPageId(page)).toBe("sess-nav");
    expect(store().activePageId).toBe(page.id);
  });

  it("updates url/title on existing serverSessionId without duplicating", () => {
    store().upsertServerSession("c1", {
      sessionId: "s1",
      hostKind: "sandbox",
      control: "agent",
      url: "https://a.example/",
    });
    store().upsertServerSession("c1", {
      sessionId: "s1",
      hostKind: "sandbox",
      control: "agent",
      url: "https://b.example/",
      title: "B",
    });
    const pages = store()
      .pagesFor("c1")
      .filter((p) => p.serverSessionId === "s1");
    expect(pages).toHaveLength(1);
    expect(pages[0]).toMatchObject({
      url: "https://b.example/",
      title: "B",
    });
  });

  it("does not steal activation from another server tab", () => {
    store().upsertServerSession("c1", {
      sessionId: "keep",
      hostKind: "local",
      control: "agent",
      url: "https://keep.example/",
    });
    const keepId = store().activePageId;
    store().upsertServerSession("c1", {
      sessionId: "other",
      hostKind: "local",
      control: "agent",
      url: "https://other.example/",
    });
    expect(store().activePageId).toBe(keepId);
    expect(store().pagesFor("c1")).toHaveLength(2);
  });
});
