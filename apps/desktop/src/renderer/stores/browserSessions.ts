/**
 * 右坞浏览器壳页签状态（BrowserPanel）——本地空白页 + 服务端 session 投影。
 *
 * 本地空白页无 `serverSessionId`，`ensureBlankPage` / `createPage` **不** POST create
 *（避免每建空白页就开真 gVisor）。服务端页由 {@link hydrateConversation} 从
 * list（Local=sidecar Registry / 云=GET）合并，或由 `tool_use_end.display` 经
 * {@link upsertServerSession} 推送绑页。
 *
 * 生命周期跟对话走（hide≠destroy）。P1 冷恢复：每对话页签列表经
 * {@link conversationUiSet} 落盘；进入对话时再 hydrate（禁启动批量建 WebContents）。
 */
import {
  conversationUiGet,
  conversationUiRemove,
  conversationUiSet,
} from "@/lib/uiStorage";
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

/** A 推送绑页：display / list 条目里够 upsert 的最小字段。 */
export type BrowserServerSessionUpsert = Pick<
  BrowserSessionInfo,
  "sessionId" | "hostKind" | "control"
> & {
  url?: string | null;
  title?: string | null;
};

/** uiStorage leaf：`agentcore:c:{cid}:browserTabs`。 */
export const BROWSER_TABS_STORAGE_LEAF = "browserTabs";

export interface PersistedBrowserTab {
  id: string;
  url: string;
  title: string;
  serverSessionId?: string | null;
  hostKind?: BrowserHostKind;
  control?: BrowserControl;
}

export interface PersistedBrowserTabs {
  pages: PersistedBrowserTab[];
  activePageId: string | null;
}

interface BrowserSessionsState {
  pages: BrowserPage[];
  activePageId: string | null;
  /** 每对话记住激活页（切对话保活后切回恢复）。 */
  activePageIdByConversation: Record<string, string>;

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
  /** 本地改 url/title（不驱动真浏览器）。 */
  navigatePage: (id: string, url: string) => void;
  /**
   * 宿主导航写回：页内跳转 / 挂回时用真实 URL（及可选 title）更新 store，
   * 不因 hostname 覆盖已有有意义标题。
   */
  syncPageFromHost: (id: string, url: string, title?: string | null) => void;
  /**
   * 把已创建的服务端 session 写回本地页（Web 地址栏 create 后），
   * 便于随后 hydrate 合并时保留同页 id/url。
   */
  attachServerSession: (
    pageId: string,
    info: Pick<BrowserSessionInfo, "sessionId" | "hostKind" | "control">,
  ) => void;
  /**
   * 按 `serverSessionId` 创建或更新 url/title/hostKind/control；
   * 若当前无页或当前是同会话本地空白则激活该页。
   */
  upsertServerSession: (
    conversationId: string,
    info: BrowserServerSessionUpsert,
  ) => void;
  setPageTitle: (id: string, title: string) => void;
  /** 清掉某会话的全部页 + 持久记录。 */
  clearConversation: (conversationId: string) => void;
  /**
   * 进入对话时：无内存页则从 uiStorage 冷恢复 → list 合并。
   * 禁启动时给所有对话批量建页。
   */
  hydrateConversation: (conversationId: string) => Promise<void>;
}

const EMPTY_PAGES: BrowserPage[] = [];

/** per-conversation hydrate inflight（登记最新 promise；不复用旧 list 结果）。 */
const hydrateInflight = new Map<string, Promise<void>>();

/** per-conversation hydrate 代际：upsert / 新 hydrate 均 bump，过期 apply 丢弃。 */
const hydrateEpoch = new Map<string, number>();

/** 已对该 cid 做过磁盘冷恢复（本进程内只做一次，避免空 list 覆盖后反复读盘）。 */
const coldRestored = new Set<string>();

function bumpHydrateEpoch(conversationId: string): number {
  const next = (hydrateEpoch.get(conversationId) ?? 0) + 1;
  hydrateEpoch.set(conversationId, next);
  return next;
}

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

/** 宿主 / about:blank 占位 → 视为无真实页 URL。 */
export function isBlankBrowserUrl(url: string | null | undefined): boolean {
  if (url == null) return true;
  const t = url.trim();
  return !t || t === "about:blank" || t.startsWith("about:blank");
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

function rememberActive(
  map: Record<string, string>,
  conversationId: string | null,
  pageId: string | null,
): Record<string, string> {
  if (!conversationId) return map;
  if (!pageId) {
    if (!(conversationId in map)) return map;
    const next = { ...map };
    delete next[conversationId];
    return next;
  }
  if (map[conversationId] === pageId) return map;
  return { ...map, [conversationId]: pageId };
}

function toPersisted(pages: BrowserPage[]): PersistedBrowserTab[] {
  return pages.map((p) => ({
    id: p.id,
    url: p.url,
    title: p.title,
    serverSessionId: p.serverSessionId ?? null,
    hostKind: p.hostKind,
    control: p.control,
  }));
}

/** 将当前对话页签写回 uiStorage；无页则删键。 */
export function persistBrowserTabsForConversation(
  conversationId: string | null,
  allPages: BrowserPage[],
  activePageId: string | null,
): void {
  if (!conversationId) return;
  const pages = allPages.filter((p) => p.conversationId === conversationId);
  if (pages.length === 0) {
    conversationUiRemove(conversationId, BROWSER_TABS_STORAGE_LEAF);
    return;
  }
  const activeInScope =
    activePageId && pages.some((p) => p.id === activePageId)
      ? activePageId
      : (pages[pages.length - 1]?.id ?? null);
  const payload: PersistedBrowserTabs = {
    pages: toPersisted(pages),
    activePageId: activeInScope,
  };
  conversationUiSet(conversationId, BROWSER_TABS_STORAGE_LEAF, payload);
}

/** 读盘；损坏 / 空 → null。 */
export function loadPersistedBrowserTabs(
  conversationId: string,
): PersistedBrowserTabs | null {
  const raw = conversationUiGet<PersistedBrowserTabs>(
    conversationId,
    BROWSER_TABS_STORAGE_LEAF,
  );
  if (!raw || !Array.isArray(raw.pages) || raw.pages.length === 0) return null;
  const pages: PersistedBrowserTab[] = [];
  for (const p of raw.pages) {
    if (!p || typeof p.id !== "string" || typeof p.url !== "string") continue;
    pages.push({
      id: p.id,
      url: p.url,
      title: typeof p.title === "string" ? p.title : titleFromUrl(p.url),
      serverSessionId:
        typeof p.serverSessionId === "string" ? p.serverSessionId : null,
      hostKind:
        p.hostKind === "local" || p.hostKind === "sandbox"
          ? p.hostKind
          : undefined,
      control:
        p.control === "agent" || p.control === "user" ? p.control : undefined,
    });
  }
  if (pages.length === 0) return null;
  const activePageId =
    typeof raw.activePageId === "string" &&
    pages.some((p) => p.id === raw.activePageId)
      ? raw.activePageId
      : (pages[pages.length - 1]?.id ?? null);
  return { pages, activePageId };
}

/**
 * 纯合并（单测 / hydrate 共用）：本地无 serverSessionId 的页保留，server 页按 list 重建。
 * 空 list：保留已有 `hostKind==="local"` 且带 `serverSessionId` 的页（勿抹 upsert/Bridge）；
 * sandbox server 页仍清（云空 list=权威）。非空 list：以 list 为准可丢 stale（含 local）。
 */
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

  if (sessions.length === 0) {
    const keptLocalServer = allPages.filter(
      (p) =>
        p.conversationId === conversationId &&
        !!p.serverSessionId &&
        p.hostKind === "local",
    );
    const pages = [...others, ...localBlanks, ...keptLocalServer];
    let activePageId = prevActivePageId;
    if (!activePageId || !pages.some((p) => p.id === activePageId)) {
      const scoped = [...localBlanks, ...keptLocalServer];
      activePageId = scoped[scoped.length - 1]?.id ?? null;
    }
    return { pages, activePageId };
  }

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

  const prevIsLocalBlank =
    prevActivePageId != null &&
    localBlanks.some((p) => p.id === prevActivePageId);

  let activePageId = prevActivePageId;
  if (activeSessionId) {
    const match = serverPages.find(
      (p) => p.serverSessionId === activeSessionId,
    );
    if (match) activePageId = match.id;
  } else if (serverPages.length > 0 && prevIsLocalBlank) {
    // 有服务端页时勿钉死本地空白（Agent 已在裸 session 上导航，UI 却停在无 sid 壳）。
    activePageId =
      serverPages.length === 1
        ? (serverPages[0]?.id ?? null)
        : (serverPages[serverPages.length - 1]?.id ?? null);
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
    activePageIdByConversation: {},

    pagesFor: (conversationId) => {
      const list = get().pages.filter(
        (p) => p.conversationId === conversationId,
      );
      return list.length === 0 ? EMPTY_PAGES : list;
    },

    activePage: (conversationId) => {
      const list = get().pagesFor(conversationId);
      if (list.length === 0) return null;
      const remembered =
        conversationId != null
          ? get().activePageIdByConversation[conversationId]
          : undefined;
      const active = get().activePageId;
      return (
        list.find((p) => p.id === active) ??
        (remembered ? list.find((p) => p.id === remembered) : undefined) ??
        list[list.length - 1] ??
        null
      );
    },

    createPage: (opts) => {
      const id = nextPageId();
      const url = opts?.url ?? "";
      const conversationId = opts?.conversationId ?? null;
      const page: BrowserPage = {
        id,
        url,
        title: opts?.title ?? titleFromUrl(url),
        conversationId,
        serverSessionId: opts?.serverSessionId ?? null,
        hostKind: opts?.hostKind,
        control: opts?.control,
      };
      const activate = opts?.activate !== false;
      set((s) => {
        const activePageId = activate ? id : s.activePageId;
        const activePageIdByConversation = activate
          ? rememberActive(s.activePageIdByConversation, conversationId, id)
          : s.activePageIdByConversation;
        const pages = [...s.pages, page];
        persistBrowserTabsForConversation(conversationId, pages, activePageId);
        return { pages, activePageId, activePageIdByConversation };
      });
      return id;
    },

    ensureBlankPage: (conversationId) => {
      const existing = get().pagesFor(conversationId);
      if (existing.length > 0) {
        const active = get().activePageId;
        if (!existing.some((p) => p.id === active)) {
          const fallback = existing[existing.length - 1]?.id;
          if (fallback) {
            set((s) => ({
              activePageId: fallback,
              activePageIdByConversation: rememberActive(
                s.activePageIdByConversation,
                conversationId,
                fallback,
              ),
            }));
          }
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
        const activePageIdByConversation = rememberActive(
          s.activePageIdByConversation,
          target.conversationId,
          activePageId,
        );
        persistBrowserTabsForConversation(
          target.conversationId,
          pages,
          activePageId,
        );
        return { pages, activePageId, activePageIdByConversation };
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

    setActivePage: (id) =>
      set((s) => {
        const page = s.pages.find((p) => p.id === id);
        if (!page) return { activePageId: id };
        const activePageIdByConversation = rememberActive(
          s.activePageIdByConversation,
          page.conversationId,
          id,
        );
        persistBrowserTabsForConversation(page.conversationId, s.pages, id);
        return { activePageId: id, activePageIdByConversation };
      }),

    navigatePage: (id, url) => {
      const normalized = normalizeBrowserUrl(url);
      set((s) => {
        const pages = s.pages.map((p) =>
          p.id === id
            ? {
                ...p,
                url: normalized,
                title: titleFromUrl(normalized),
              }
            : p,
        );
        const page = pages.find((p) => p.id === id);
        persistBrowserTabsForConversation(
          page?.conversationId ?? null,
          pages,
          s.activePageId,
        );
        return { pages };
      });
    },

    syncPageFromHost: (id, url, title) => {
      if (isBlankBrowserUrl(url)) return;
      set((s) => {
        const prev = s.pages.find((p) => p.id === id);
        if (!prev) return s;
        const nextTitle =
          typeof title === "string" && title.trim()
            ? title.trim()
            : prev.title && prev.title !== "新标签页"
              ? prev.title
              : titleFromUrl(url);
        if (prev.url === url && prev.title === nextTitle) return s;
        const pages = s.pages.map((p) =>
          p.id === id ? { ...p, url, title: nextTitle } : p,
        );
        persistBrowserTabsForConversation(
          prev.conversationId,
          pages,
          s.activePageId,
        );
        return { pages };
      });
    },

    attachServerSession: (pageId, info) => {
      set((s) => {
        const pages = s.pages.map((p) =>
          p.id === pageId
            ? {
                ...p,
                serverSessionId: info.sessionId,
                hostKind: info.hostKind,
                control: info.control,
              }
            : p,
        );
        const page = pages.find((p) => p.id === pageId);
        persistBrowserTabsForConversation(
          page?.conversationId ?? null,
          pages,
          s.activePageId,
        );
        return { pages };
      });
    },

    upsertServerSession: (conversationId, info) => {
      const sid = info.sessionId.trim();
      if (!sid) return;
      // 使在飞的过期 hydrate（常为空 list）不落地抹掉本页。
      bumpHydrateEpoch(conversationId);
      const url =
        typeof info.url === "string" && info.url.trim() ? info.url.trim() : "";
      const titleRaw =
        typeof info.title === "string" && info.title.trim()
          ? info.title.trim()
          : "";
      const hostKind = info.hostKind;
      const control = info.control ?? "agent";

      set((s) => {
        const existing = s.pages.find(
          (p) =>
            p.conversationId === conversationId && p.serverSessionId === sid,
        );
        const pageId = existing?.id ?? serverPageId(sid);
        const nextUrl = url || existing?.url || "";
        const nextTitle =
          titleRaw ||
          existing?.title ||
          (nextUrl
            ? titleFromUrl(nextUrl)
            : titleForServerSession({
                sessionId: sid,
                conversationId,
                hostKind: hostKind ?? "sandbox",
                control,
                runId: null,
                createdAt: 0,
                lastUsed: 0,
              }));

        const page: BrowserPage = {
          id: pageId,
          url: nextUrl,
          title: nextTitle,
          conversationId,
          serverSessionId: sid,
          hostKind: hostKind ?? existing?.hostKind,
          control,
        };

        const pages = existing
          ? s.pages.map((p) => (p.id === pageId ? page : p))
          : [...s.pages, page];

        const active = s.activePageId
          ? pages.find((p) => p.id === s.activePageId)
          : null;
        const activeIsLocalBlank =
          active != null &&
          active.conversationId === conversationId &&
          (active.serverSessionId == null || active.serverSessionId === "");
        const shouldActivate =
          !s.activePageId ||
          !pages.some((p) => p.id === s.activePageId) ||
          activeIsLocalBlank;

        const activePageId = shouldActivate ? pageId : s.activePageId;
        const activePageIdByConversation = rememberActive(
          s.activePageIdByConversation,
          conversationId,
          activePageId,
        );
        persistBrowserTabsForConversation(conversationId, pages, activePageId);
        return {
          pages,
          activePageId,
          activePageIdByConversation,
        };
      });
    },

    setPageTitle: (id, title) => {
      set((s) => {
        const pages = s.pages.map((p) => (p.id === id ? { ...p, title } : p));
        const page = pages.find((p) => p.id === id);
        persistBrowserTabsForConversation(
          page?.conversationId ?? null,
          pages,
          s.activePageId,
        );
        return { pages };
      });
    },

    clearConversation: (conversationId) => {
      coldRestored.delete(conversationId);
      conversationUiRemove(conversationId, BROWSER_TABS_STORAGE_LEAF);
      set((s) => {
        const pages = s.pages.filter(
          (p) => p.conversationId !== conversationId,
        );
        const activeStill = pages.some((p) => p.id === s.activePageId);
        const activePageIdByConversation = {
          ...s.activePageIdByConversation,
        };
        delete activePageIdByConversation[conversationId];
        return {
          pages,
          activePageId: activeStill ? s.activePageId : null,
          activePageIdByConversation,
        };
      });
    },

    hydrateConversation: (conversationId) => {
      const epoch = bumpHydrateEpoch(conversationId);
      const prior = hydrateInflight.get(conversationId);

      // Self-ref Promise：finally 比对 inflight 身份（消 TS2454）。
      const pRef: { current: Promise<void> | null } = { current: null };
      const p = (async () => {
        try {
          if (prior) await prior.catch(() => undefined);

          // P1 冷恢复：本进程对该 cid 尚无内存页时读盘一次（禁启动批量）。
          if (get().pagesFor(conversationId).length === 0) {
            if (!coldRestored.has(conversationId)) {
              coldRestored.add(conversationId);
              const persisted = loadPersistedBrowserTabs(conversationId);
              if (persisted) {
                const restored: BrowserPage[] = persisted.pages.map((t) => ({
                  id: t.id,
                  url: t.url,
                  title: t.title,
                  conversationId,
                  serverSessionId: t.serverSessionId ?? null,
                  hostKind: t.hostKind,
                  control: t.control,
                }));
                set((s) => {
                  const others = s.pages.filter(
                    (pg) => pg.conversationId !== conversationId,
                  );
                  const activePageId = persisted.activePageId;
                  return {
                    pages: [...others, ...restored],
                    activePageId,
                    activePageIdByConversation: rememberActive(
                      s.activePageIdByConversation,
                      conversationId,
                      activePageId,
                    ),
                  };
                });
              }
            }
          } else {
            // 同进程切回：恢复该对话记住的激活页。
            const remembered = get().activePageIdByConversation[conversationId];
            if (
              remembered &&
              get().pages.some(
                (pg) =>
                  pg.id === remembered && pg.conversationId === conversationId,
              )
            ) {
              set({ activePageId: remembered });
            }
          }

          const { sessions, activeSessionId } =
            await listBrowserSessions(conversationId);
          if (hydrateEpoch.get(conversationId) !== epoch) return;
          const s = get();
          const preferredActive =
            s.activePageIdByConversation[conversationId] ?? s.activePageId;
          const merged = mergeHydratedPages(
            s.pages,
            conversationId,
            sessions,
            activeSessionId,
            preferredActive,
          );
          set((prev) => {
            persistBrowserTabsForConversation(
              conversationId,
              merged.pages,
              merged.activePageId,
            );
            return {
              ...merged,
              activePageIdByConversation: rememberActive(
                prev.activePageIdByConversation,
                conversationId,
                merged.activePageId,
              ),
            };
          });
        } finally {
          if (hydrateInflight.get(conversationId) === pRef.current) {
            hydrateInflight.delete(conversationId);
          }
        }
      })();
      pRef.current = p;

      hydrateInflight.set(conversationId, p);
      return p;
    },
  }),
);

/** @internal vitest — 重置冷恢复标记。 */
export function __resetBrowserTabsColdRestoreForTests(): void {
  coldRestored.clear();
}
