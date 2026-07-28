/**
 * M0.5 右坞浏览器壳页签状态（BrowserPanel）——本地空白页 + 服务端 session 投影。
 *
 * 本地空白页无 `serverSessionId`，`ensureBlankPage` / `createPage` **不** POST create
 *（避免每建空白页就开真 gVisor）。服务端页由 {@link hydrateConversation} 从
 * `GET …/browser/sessions` 合并进来。
 */
import {
  type BrowserControl,
  type BrowserHostKind,
  type BrowserSessionInfo,
  closeBrowserSession,
  listBrowserSessions,
} from "@/services/browserSessions";
import { create } from "zustand";

export interface BrowserPage {
  id: string;
  /** 空串 = 空白新页（未导航）。 */
  url: string;
  title: string;
  /** 所属会话；无当前会话时为 null。 */
  conversationId: string | null;
  /** 有值 = 对应云端 / 宿主 BrowserSession；本地空白页为 null/undefined。 */
  serverSessionId?: string | null;
  hostKind?: BrowserHostKind;
  control?: BrowserControl;
}

interface BrowserSessionsState {
  pages: BrowserPage[];
  activePageId: string | null;

  pagesFor: (conversationId: string | null) => BrowserPage[];
  activePage: (conversationId: string | null) => BrowserPage | null;
  /**
   * 新建页并激活。默认空白「新标签页」（本地壳，不 POST）。
   * @returns 新页 id
   */
  createPage: (opts?: {
    conversationId?: string | null;
    url?: string;
    title?: string;
    activate?: boolean;
    serverSessionId?: string | null;
    hostKind?: BrowserHostKind;
    control?: BrowserControl;
  }) => string;
  /** 无页时建空白页并激活；已有页则确保有 active。不 POST。 */
  ensureBlankPage: (conversationId: string | null) => string;
  closePage: (id: string) => void;
  /**
   * 关带 `serverSessionId` 的页：先 DELETE 再本地移除。
   * 失败抛错（调用方 toast）；成功才调 {@link closePage}。
   */
  closeServerPage: (id: string) => Promise<void>;
  setActivePage: (id: string) => void;
  /** 本地改 url/title（M0 stub；不驱动真浏览器）。 */
  navigatePage: (id: string, url: string) => void;
  /**
   * 把已创建的服务端 session 写回本地页（Web 地址栏 create 后），
   * 便于随后 hydrate 合并时保留同页 id/url。
   */
  attachServerSession: (
    pageId: string,
    info: Pick<BrowserSessionInfo, "sessionId" | "hostKind" | "control">,
  ) => void;
  setPageTitle: (id: string, title: string) => void;
  /** 清掉某会话的全部页（切会话可选调用）。 */
  clearConversation: (conversationId: string) => void;
  /**
   * GET list → 投影服务端 session 为页签；保留本地空白；去掉已不在服务端的旧 server 页。
   * active 优先 `active_session_id`。同 conversation 并发复用 inflight。
   */
  hydrateConversation: (conversationId: string) => Promise<void>;
}

const EMPTY_PAGES: BrowserPage[] = [];

/** per-conversation hydrate inflight（防抖外的并发合并）。 */
const hydrateInflight = new Map<string, Promise<void>>();

function titleFromUrl(url: string): string {
  if (!url) return "新标签页";
  try {
    const u = new URL(url);
    return u.hostname || url;
  } catch {
    return url;
  }
}

/** 用户地址栏回车：补协议；空输入保持空白。 */
export function normalizeBrowserUrl(raw: string): string {
  const t = raw.trim();
  if (!t) return "";
  if (/^[a-zA-Z][a-zA-Z0-9+.-]*:/.test(t)) return t;
  if (t.startsWith("//")) return `https:${t}`;
  return `https://${t}`;
}

let pageSeq = 0;
function nextPageId(): string {
  pageSeq += 1;
  return `browser-page:${pageSeq}:${crypto.randomUUID()}`;
}

/** 服务端 session → 稳定本地页 id（再 hydrate 不抖）。 */
export function serverPageId(sessionId: string): string {
  return `browser-server:${sessionId}`;
}

/**
 * Local Bridge / WebContents 键：有 `serverSessionId` 用裸 session id
 *（与 Registry / Bridge 一致）；本地空白页用 React page id。
 */
export function hostBrowserPageId(
  page: Pick<BrowserPage, "id" | "serverSessionId">,
): string {
  return page.serverSessionId || page.id;
}

export function titleForServerSession(s: BrowserSessionInfo): string {
  const short = s.sessionId.length > 8 ? s.sessionId.slice(0, 8) : s.sessionId;
  return `浏览器 · ${s.hostKind} · ${short}`;
}

/** 纯合并（单测 / hydrate 共用）：本地无 serverSessionId 的页保留，server 页按 list 重建。 */
export function mergeHydratedPages(
  allPages: BrowserPage[],
  conversationId: string,
  sessions: BrowserSessionInfo[],
  activeSessionId: string | null,
  prevActivePageId: string | null,
): { pages: BrowserPage[]; activePageId: string | null } {
  const others = allPages.filter((p) => p.conversationId !== conversationId);
  const localBlanks = allPages.filter(
    (p) =>
      p.conversationId === conversationId &&
      (p.serverSessionId == null || p.serverSessionId === ""),
  );

  const serverPages: BrowserPage[] = sessions.map((s) => {
    const id = serverPageId(s.sessionId);
    const prev = allPages.find(
      (p) =>
        p.conversationId === conversationId &&
        p.serverSessionId === s.sessionId,
    );
    const serverUrl = typeof s.url === "string" ? s.url.trim() : "";
    const serverTitle = typeof s.title === "string" ? s.title.trim() : "";
    const prevTitle =
      prev?.title && prev.serverSessionId === s.sessionId ? prev.title : "";
    return {
      id: prev?.id ?? id,
      // 优先服务端 url（Agent 导航后 list 带回）；勿因 prev 空串锁死丢弃。
      url: serverUrl || prev?.url || "",
      title: serverTitle || prevTitle || titleForServerSession(s),
      conversationId,
      serverSessionId: s.sessionId,
      hostKind: s.hostKind,
      control: s.control,
    };
  });

  const pages = [...others, ...localBlanks, ...serverPages];

  let activePageId = prevActivePageId;
  if (activeSessionId) {
    const match = serverPages.find(
      (p) => p.serverSessionId === activeSessionId,
    );
    if (match) activePageId = match.id;
  } else if (!activePageId || !pages.some((p) => p.id === activePageId)) {
    const scoped = [...localBlanks, ...serverPages];
    activePageId = scoped[scoped.length - 1]?.id ?? null;
  }

  return { pages, activePageId };
}

export const useBrowserSessionsStore = create<BrowserSessionsState>(
  (set, get) => ({
    pages: [],
    activePageId: null,

    pagesFor: (conversationId) => {
      const list = get().pages.filter(
        (p) => p.conversationId === conversationId,
      );
      return list.length === 0 ? EMPTY_PAGES : list;
    },

    activePage: (conversationId) => {
      const list = get().pagesFor(conversationId);
      if (list.length === 0) return null;
      const active = get().activePageId;
      return list.find((p) => p.id === active) ?? list[list.length - 1] ?? null;
    },

    createPage: (opts) => {
      const id = nextPageId();
      const url = opts?.url ?? "";
      const page: BrowserPage = {
        id,
        url,
        title: opts?.title ?? titleFromUrl(url),
        conversationId: opts?.conversationId ?? null,
        serverSessionId: opts?.serverSessionId ?? null,
        hostKind: opts?.hostKind,
        control: opts?.control,
      };
      const activate = opts?.activate !== false;
      set((s) => ({
        pages: [...s.pages, page],
        activePageId: activate ? id : s.activePageId,
      }));
      return id;
    },

    ensureBlankPage: (conversationId) => {
      const existing = get().pagesFor(conversationId);
      if (existing.length > 0) {
        const active = get().activePageId;
        if (!existing.some((p) => p.id === active)) {
          set({ activePageId: existing[existing.length - 1]?.id });
        }
        return get().activePageId ?? existing[0]?.id;
      }
      return get().createPage({ conversationId, url: "", title: "新标签页" });
    },

    closePage: (id) => {
      set((s) => {
        const target = s.pages.find((p) => p.id === id);
        if (!target) return s;
        const pages = s.pages.filter((p) => p.id !== id);
        const siblings = pages.filter(
          (p) => p.conversationId === target.conversationId,
        );
        let activePageId = s.activePageId;
        if (s.activePageId === id) {
          activePageId = siblings[siblings.length - 1]?.id ?? null;
        }
        // 关掉该会话最后一页 → 立刻补空白页，壳始终有可编辑页签。
        if (siblings.length === 0) {
          const blankId = nextPageId();
          pages.push({
            id: blankId,
            url: "",
            title: "新标签页",
            conversationId: target.conversationId,
            serverSessionId: null,
          });
          activePageId = blankId;
        }
        return { pages, activePageId };
      });
    },

    closeServerPage: async (id) => {
      const page = get().pages.find((p) => p.id === id);
      if (!page) return;
      const sessionId = page.serverSessionId;
      const convId = page.conversationId;
      if (sessionId && convId) {
        await closeBrowserSession(convId, sessionId);
      }
      get().closePage(id);
    },

    setActivePage: (id) => set({ activePageId: id }),

    navigatePage: (id, url) => {
      const normalized = normalizeBrowserUrl(url);
      set((s) => ({
        pages: s.pages.map((p) =>
          p.id === id
            ? {
                ...p,
                url: normalized,
                title: titleFromUrl(normalized),
              }
            : p,
        ),
      }));
    },

    attachServerSession: (pageId, info) => {
      set((s) => ({
        pages: s.pages.map((p) =>
          p.id === pageId
            ? {
                ...p,
                serverSessionId: info.sessionId,
                hostKind: info.hostKind,
                control: info.control,
              }
            : p,
        ),
      }));
    },

    setPageTitle: (id, title) => {
      set((s) => ({
        pages: s.pages.map((p) => (p.id === id ? { ...p, title } : p)),
      }));
    },

    clearConversation: (conversationId) => {
      set((s) => {
        const pages = s.pages.filter(
          (p) => p.conversationId !== conversationId,
        );
        const activeStill = pages.some((p) => p.id === s.activePageId);
        return {
          pages,
          activePageId: activeStill ? s.activePageId : null,
        };
      });
    },

    hydrateConversation: (conversationId) => {
      const existing = hydrateInflight.get(conversationId);
      if (existing) return existing;

      const p = (async () => {
        try {
          const { sessions, activeSessionId } =
            await listBrowserSessions(conversationId);
          const s = get();
          const merged = mergeHydratedPages(
            s.pages,
            conversationId,
            sessions,
            activeSessionId,
            s.activePageId,
          );
          set(merged);
        } finally {
          hydrateInflight.delete(conversationId);
        }
      })();

      hydrateInflight.set(conversationId, p);
      return p;
    },
  }),
);
