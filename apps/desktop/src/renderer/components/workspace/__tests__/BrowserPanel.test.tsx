// @vitest-environment jsdom
/**
 * M1 BrowserPanel：页签 / 地址栏 / 本机 browserApi 真导航；hydrate；关 server 页 DELETE；
 * live 仅当当前页带 serverSessionId。
 */

import type { BrowserApi, BrowserNavState } from "@shared/browser-contract";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/components/workspace/BrowserLivePanel", () => ({
  BrowserLivePanel: ({
    conversationId,
    sessionId,
  }: {
    conversationId: string;
    sessionId?: string;
  }) => (
    <div data-testid="browser-live">
      {conversationId}:{sessionId ?? ""}
    </div>
  ),
}));

vi.mock("@/services/browserSessions", () => ({
  listBrowserSessions: vi.fn().mockResolvedValue({
    sessions: [],
    activeSessionId: null,
  }),
  closeBrowserSession: vi.fn().mockResolvedValue(undefined),
  createBrowserSession: vi.fn(),
  navigateBrowserSession: vi.fn(),
  patchBrowserSessionNav: vi.fn().mockResolvedValue(undefined),
}));

vi.mock("@/lib/toast", () => ({
  notifyError: vi.fn(),
}));

import { notifyError } from "@/lib/toast";
import {
  closeBrowserSession,
  createBrowserSession,
  listBrowserSessions,
  navigateBrowserSession,
} from "@/services/browserSessions";
import { useBrowserSessionsStore } from "@/stores/browserSessions";
import { BrowserPanel, isLocalhostBrowserUrl } from "../BrowserPanel";

const listMock = vi.mocked(listBrowserSessions);
const closeMock = vi.mocked(closeBrowserSession);
const createMock = vi.mocked(createBrowserSession);
const navigateMock = vi.mocked(navigateBrowserSession);
const notifyMock = vi.mocked(notifyError);

function mockBrowserApi(overrides: Partial<BrowserApi> = {}): BrowserApi {
  return {
    show: vi.fn().mockResolvedValue({ ok: true }),
    setBounds: vi.fn(),
    hide: vi.fn(),
    navigate: vi.fn().mockResolvedValue({ ok: true }),
    openWorkspaceHtml: vi.fn().mockResolvedValue({ ok: true }),
    reload: vi.fn(),
    back: vi.fn(),
    close: vi.fn(),
    onNavState: vi.fn().mockReturnValue(() => {}),
    ...overrides,
  };
}

function submitAddressBar(input: HTMLElement) {
  const form = input.closest("form");
  expect(form).not.toBeNull();
  if (!form) throw new Error("expected address form");
  fireEvent.submit(form);
}

function firstPage(conversationId: string) {
  const page = useBrowserSessionsStore.getState().pagesFor(conversationId)[0];
  expect(page).toBeDefined();
  if (!page) throw new Error("expected browser page");
  return page;
}

beforeEach(() => {
  useBrowserSessionsStore.setState({ pages: [], activePageId: null });
  listMock.mockReset();
  closeMock.mockReset();
  createMock.mockReset();
  navigateMock.mockReset();
  notifyMock.mockReset();
  listMock.mockResolvedValue({ sessions: [], activeSessionId: null });
  closeMock.mockResolvedValue(undefined);
  createMock.mockResolvedValue({
    sessionId: "sess-created",
    conversationId: "conv-1",
    hostKind: "sandbox",
    control: "agent",
    runId: null,
    createdAt: 1,
    lastUsed: 1,
  });
  navigateMock.mockResolvedValue({
    sessionId: "sess-created",
    conversationId: "conv-1",
    hostKind: "sandbox",
    control: "agent",
    runId: null,
    createdAt: 1,
    lastUsed: 2,
    url: "https://example.com",
  });
  window.browserApi = undefined;
  // jsdom 无 ResizeObserver；本机 Host 路径会挂观察器。
  globalThis.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver;
});

afterEach(() => {
  cleanup();
  window.browserApi = undefined;
});

describe("BrowserPanel", () => {
  it("shows chrome + browse placeholder when there is no live session and no browserApi", async () => {
    render(<BrowserPanel conversationId="conv-1" liveAvailable={false} />);
    expect(screen.getByLabelText("地址栏")).toBeTruthy();
    expect(screen.getByLabelText("新标签页")).toBeTruthy();
    expect(screen.getByText("输入地址开始浏览")).toBeTruthy();
    expect(screen.queryByText("暂无浏览器活动")).toBeNull();
    expect(screen.queryByTestId("browser-live")).toBeNull();
    expect(useBrowserSessionsStore.getState().pagesFor("conv-1")).toHaveLength(
      1,
    );
    await waitFor(() => {
      expect(listMock).toHaveBeenCalledWith("conv-1");
    });
  });

  it("does not mount BrowserLivePanel for blank local page even when liveAvailable", () => {
    render(<BrowserPanel conversationId="conv-1" liveAvailable={true} />);
    expect(screen.queryByTestId("browser-live")).toBeNull();
  });

  it("mounts BrowserLivePanel when active page has serverSessionId (no liveAvailable gate)", () => {
    useBrowserSessionsStore.setState({
      pages: [
        {
          id: "browser-server:sess-live",
          url: "",
          title: "浏览器 · sandbox · sess-live",
          conversationId: "conv-1",
          serverSessionId: "sess-live",
          hostKind: "sandbox",
          control: "agent",
        },
      ],
      activePageId: "browser-server:sess-live",
    });
    render(<BrowserPanel conversationId="conv-1" liveAvailable={false} />);
    expect(screen.getByTestId("browser-live").textContent).toBe(
      "conv-1:sess-live",
    );
  });

  it("prefers WebContents over Live for local hostKind when browserApi exists", () => {
    const api = mockBrowserApi();
    window.browserApi = api;
    useBrowserSessionsStore.setState({
      pages: [
        {
          id: "browser-server:sess-local",
          url: "https://example.com",
          title: "浏览器 · local · sess-local",
          conversationId: "conv-1",
          serverSessionId: "sess-local",
          hostKind: "local",
          control: "agent",
        },
      ],
      activePageId: "browser-server:sess-local",
    });
    render(<BrowserPanel conversationId="conv-1" liveAvailable={true} />);
    expect(screen.queryByTestId("browser-live")).toBeNull();
    expect(screen.getByText("接管")).toBeTruthy();
  });

  it("mounts BrowserLivePanel for local hostKind when browserApi is absent (remote viewer)", () => {
    window.browserApi = undefined;
    useBrowserSessionsStore.setState({
      pages: [
        {
          id: "browser-server:sess-local-remote",
          url: "https://example.com",
          title: "浏览器 · local · sess-local-remote",
          conversationId: "conv-1",
          serverSessionId: "sess-local-remote",
          hostKind: "local",
          control: "agent",
        },
      ],
      activePageId: "browser-server:sess-local-remote",
    });
    render(<BrowserPanel conversationId="conv-1" liveAvailable={true} />);
    expect(screen.getByTestId("browser-live").textContent).toBe(
      "conv-1:sess-local-remote",
    );
  });

  it("creates another local blank page via the new-tab button (no POST create)", async () => {
    render(<BrowserPanel conversationId="conv-1" liveAvailable={false} />);
    fireEvent.click(screen.getByLabelText("新标签页"));
    expect(useBrowserSessionsStore.getState().pagesFor("conv-1")).toHaveLength(
      2,
    );
    expect(
      useBrowserSessionsStore
        .getState()
        .pagesFor("conv-1")
        .every((p) => !p.serverSessionId),
    ).toBe(true);
    await waitFor(() => expect(listMock).toHaveBeenCalled());
    expect(closeMock).not.toHaveBeenCalled();
  });

  it("hydrates server sessions into tabs", async () => {
    listMock.mockResolvedValue({
      sessions: [
        {
          sessionId: "sess-abc",
          conversationId: "conv-1",
          hostKind: "sandbox",
          control: "agent",
          runId: null,
          createdAt: 1,
          lastUsed: 1,
        },
      ],
      activeSessionId: "sess-abc",
    });
    render(<BrowserPanel conversationId="conv-1" liveAvailable={false} />);
    await waitFor(() => {
      const pages = useBrowserSessionsStore.getState().pagesFor("conv-1");
      expect(pages.some((p) => p.serverSessionId === "sess-abc")).toBe(true);
    });
  });

  it("closes a server page with DELETE then removes it", async () => {
    const api = mockBrowserApi();
    window.browserApi = api;
    listMock.mockResolvedValue({ sessions: [], activeSessionId: null });
    render(<BrowserPanel conversationId="conv-1" liveAvailable={false} />);
    useBrowserSessionsStore.setState((s) => ({
      pages: [
        ...s.pages,
        {
          id: "browser-server:sess-1",
          url: "",
          title: "浏览器 · sandbox · sess-1",
          conversationId: "conv-1",
          serverSessionId: "sess-1",
          hostKind: "sandbox",
          control: "agent",
        },
      ],
      activePageId: "browser-server:sess-1",
    }));

    const closeBtn = await screen.findByLabelText(
      /关闭 浏览器 · sandbox · sess-1/,
    );
    fireEvent.click(closeBtn);

    expect(api.close).toHaveBeenCalledWith("sess-1");
    await waitFor(() => {
      expect(closeMock).toHaveBeenCalledWith("conv-1", "sess-1");
    });
    await waitFor(() => {
      expect(
        useBrowserSessionsStore
          .getState()
          .pagesFor("conv-1")
          .some((p) => p.serverSessionId === "sess-1"),
      ).toBe(false);
    });
  });

  it("keeps server page locally when DELETE fails", async () => {
    closeMock.mockRejectedValue(new Error("nope"));
    render(<BrowserPanel conversationId="conv-1" liveAvailable={false} />);
    useBrowserSessionsStore.setState((s) => ({
      pages: [
        ...s.pages,
        {
          id: "browser-server:sess-2",
          url: "",
          title: "浏览器 · sandbox · sess-2",
          conversationId: "conv-1",
          serverSessionId: "sess-2",
          hostKind: "sandbox",
          control: "agent",
        },
      ],
      activePageId: "browser-server:sess-2",
    }));

    fireEvent.click(
      await screen.findByLabelText(/关闭 浏览器 · sandbox · sess-2/),
    );

    await waitFor(() => {
      expect(closeMock).toHaveBeenCalledWith("conv-1", "sess-2");
    });
    expect(
      useBrowserSessionsStore
        .getState()
        .pagesFor("conv-1")
        .some((p) => p.serverSessionId === "sess-2"),
    ).toBe(true);
  });

  it("navigates the active page from the address bar (store)", async () => {
    render(<BrowserPanel conversationId="conv-1" liveAvailable={false} />);
    const input = screen.getByLabelText("地址栏");
    fireEvent.change(input, { target: { value: "example.com" } });
    submitAddressBar(input);
    const page = firstPage("conv-1");
    expect(page.url).toBe("https://example.com");
    expect(page.title).toBe("example.com");
    await waitFor(() => {
      expect(createMock).toHaveBeenCalledWith("conv-1", {
        hostKind: "sandbox",
        activate: true,
      });
    });
  });

  it("Web address bar: create sandbox + navigate when no browserApi", async () => {
    window.browserApi = undefined;
    listMock.mockResolvedValue({
      sessions: [
        {
          sessionId: "sess-created",
          conversationId: "conv-1",
          hostKind: "sandbox",
          control: "agent",
          runId: null,
          createdAt: 1,
          lastUsed: 1,
        },
      ],
      activeSessionId: "sess-created",
    });
    render(<BrowserPanel conversationId="conv-1" liveAvailable={false} />);
    const input = screen.getByLabelText("地址栏");
    fireEvent.change(input, { target: { value: "https://example.com" } });
    submitAddressBar(input);

    await waitFor(() => {
      expect(createMock).toHaveBeenCalledWith("conv-1", {
        hostKind: "sandbox",
        activate: true,
      });
      expect(navigateMock).toHaveBeenCalledWith(
        "conv-1",
        "sess-created",
        "https://example.com",
      );
    });
    await waitFor(() => {
      expect(screen.getByTestId("browser-live").textContent).toBe(
        "conv-1:sess-created",
      );
    });
  });

  it("Web address bar: rejects localhost without create", async () => {
    window.browserApi = undefined;
    render(<BrowserPanel conversationId="conv-1" liveAvailable={false} />);
    const input = screen.getByLabelText("地址栏");
    fireEvent.change(input, { target: { value: "http://127.0.0.1:3000" } });
    submitAddressBar(input);

    await waitFor(() => {
      expect(notifyMock).toHaveBeenCalled();
    });
    expect(createMock).not.toHaveBeenCalled();
    expect(navigateMock).not.toHaveBeenCalled();
    expect(isLocalhostBrowserUrl("http://localhost/")).toBe(true);
  });

  it("calls browserApi.navigate on address submit when Local host is active", async () => {
    const api = mockBrowserApi();
    window.browserApi = api;
    render(<BrowserPanel conversationId="conv-1" liveAvailable={false} />);
    const page = firstPage("conv-1");
    const input = screen.getByLabelText("地址栏");
    fireEvent.change(input, { target: { value: "https://example.com" } });
    submitAddressBar(input);
    await waitFor(() => {
      expect(api.navigate).toHaveBeenCalledWith({
        pageId: page.id,
        url: "https://example.com",
      });
    });
    expect(createMock).not.toHaveBeenCalled();
  });

  it("Local host show/navigate uses bare serverSessionId when present", async () => {
    const api = mockBrowserApi();
    window.browserApi = api;
    const rectSpy = vi
      .spyOn(HTMLElement.prototype, "getBoundingClientRect")
      .mockReturnValue({
        x: 10,
        y: 20,
        top: 20,
        left: 10,
        bottom: 420,
        right: 810,
        width: 800,
        height: 400,
        toJSON: () => ({}),
      } as DOMRect);
    useBrowserSessionsStore.setState({
      pages: [
        {
          id: "browser-server:sess-local",
          url: "https://example.com/agent",
          title: "Agent Page",
          conversationId: "conv-1",
          serverSessionId: "sess-local",
          hostKind: "local",
          control: "agent",
        },
      ],
      activePageId: "browser-server:sess-local",
    });
    render(<BrowserPanel conversationId="conv-1" liveAvailable={false} />);
    await waitFor(() => {
      expect(api.show).toHaveBeenCalledWith(
        expect.objectContaining({ pageId: "sess-local" }),
      );
    });
    const input = screen.getByLabelText("地址栏");
    fireEvent.change(input, { target: { value: "https://example.com/next" } });
    submitAddressBar(input);
    await waitFor(() => {
      expect(api.navigate).toHaveBeenCalledWith({
        pageId: "sess-local",
        url: "https://example.com/next",
      });
    });
    expect(api.navigate).not.toHaveBeenCalledWith(
      expect.objectContaining({ pageId: "browser-server:sess-local" }),
    );
    expect(api.show).not.toHaveBeenCalledWith(
      expect.objectContaining({ pageId: "browser-server:sess-local" }),
    );
    rectSpy.mockRestore();
  });

  it("calls browserApi.close when closing a local page", () => {
    const api = mockBrowserApi();
    window.browserApi = api;
    render(<BrowserPanel conversationId="conv-1" liveAvailable={false} />);
    const page = firstPage("conv-1");
    fireEvent.click(screen.getByLabelText(`关闭 ${page.title || "新标签页"}`));
    expect(api.close).toHaveBeenCalledWith(page.id);
  });

  it("enables back when navState reports canGoBack", async () => {
    const nav = {
      cb: null as ((s: BrowserNavState) => void) | null,
    };
    const api = mockBrowserApi({
      onNavState: (cb) => {
        nav.cb = cb;
        return () => {};
      },
    });
    window.browserApi = api;
    render(<BrowserPanel conversationId="conv-1" liveAvailable={false} />);
    const page = firstPage("conv-1");
    expect((screen.getByLabelText("后退") as HTMLButtonElement).disabled).toBe(
      true,
    );
    nav.cb?.({
      pageId: page.id,
      url: "https://example.com/b",
      canGoBack: true,
    });
    await waitFor(() => {
      expect(
        (screen.getByLabelText("后退") as HTMLButtonElement).disabled,
      ).toBe(false);
    });
    fireEvent.click(screen.getByLabelText("后退"));
    expect(api.back).toHaveBeenCalledWith(page.id);
  });

  it("back/reload for serverSession page use bare session id", async () => {
    const nav = {
      cb: null as ((s: BrowserNavState) => void) | null,
    };
    const api = mockBrowserApi({
      onNavState: (cb) => {
        nav.cb = cb;
        return () => {};
      },
    });
    window.browserApi = api;
    useBrowserSessionsStore.setState({
      pages: [
        {
          id: "browser-server:sess-nav",
          url: "https://example.com",
          title: "Ex",
          conversationId: "conv-1",
          serverSessionId: "sess-nav",
          hostKind: "local",
          control: "user",
        },
      ],
      activePageId: "browser-server:sess-nav",
    });
    render(<BrowserPanel conversationId="conv-1" liveAvailable={false} />);
    nav.cb?.({
      pageId: "sess-nav",
      url: "https://example.com/b",
      canGoBack: true,
    });
    await waitFor(() => {
      expect(
        (screen.getByLabelText("后退") as HTMLButtonElement).disabled,
      ).toBe(false);
    });
    fireEvent.click(screen.getByLabelText("后退"));
    expect(api.back).toHaveBeenCalledWith("sess-nav");
    fireEvent.click(screen.getByLabelText("刷新"));
    expect(api.reload).toHaveBeenCalledWith("sess-nav");
  });

  it("disables back and refresh without browserApi", () => {
    render(<BrowserPanel conversationId="conv-1" liveAvailable={false} />);
    expect((screen.getByLabelText("后退") as HTMLButtonElement).disabled).toBe(
      true,
    );
    expect((screen.getByLabelText("刷新") as HTMLButtonElement).disabled).toBe(
      true,
    );
  });

  it("hides Local takeover when the page has no serverSessionId", () => {
    const api = mockBrowserApi();
    window.browserApi = api;
    render(<BrowserPanel conversationId="conv-1" liveAvailable={false} />);
    expect(screen.queryByText("接管")).toBeNull();
    expect(screen.queryByText("归还控制")).toBeNull();
  });

  it("shows Local takeover when active page has serverSessionId (non-live)", () => {
    const api = mockBrowserApi();
    window.browserApi = api;
    useBrowserSessionsStore.setState({
      pages: [
        {
          id: "browser-server:sess-local",
          url: "https://example.com",
          title: "浏览器 · local · sess-local",
          conversationId: "conv-1",
          serverSessionId: "sess-local",
          hostKind: "local",
          control: "agent",
        },
      ],
      activePageId: "browser-server:sess-local",
    });
    render(<BrowserPanel conversationId="conv-1" liveAvailable={false} />);
    expect(screen.getByText("接管")).toBeTruthy();
    expect(screen.queryByTestId("browser-live")).toBeNull();
  });
});
