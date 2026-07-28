/**
 * 右坞唯一浏览器壳——页签条 + 可编辑地址栏 + 新页；内容区：
 * - 有 serverSessionId 且非 preferLocalHost → {@link BrowserLivePanel}（SSE jpeg）；
 * - Local + 有 browserApi → 本机 WebContents 真画面（screencast 只服务远程观众）；
 * - Local 有 serverSessionId 时挂 {@link BrowserLocalTakeoverBar}（无 sid 隐藏接管）。
 *
 * 有 conversationId 时 mount / 聚焦 hydrate（list sessions）；空白页不 POST create。
 * 关闭带 serverSessionId 的页 → DELETE 再本地移除；本机页 → browserApi.close。
 *
 * 地址栏回车：
 * - 有 browserApi → store + browserApi.navigate（Local 真画面）；
 * - 无 browserApi（Web）→ sandbox create（若无 sid）+ POST navigate；拒 localhost。
 */
import { Button, IconButton, Input } from "@/components/ui";
import { BrowserLivePanel } from "@/components/workspace/BrowserLivePanel";
import { BrowserLocalTakeoverBar } from "@/components/workspace/BrowserLocalTakeoverBar";
import { notifyError } from "@/lib/toast";
import {
  createBrowserSession,
  navigateBrowserSession,
  patchBrowserSessionNav,
} from "@/services/browserSessions";
import {
  normalizeBrowserUrl,
  useBrowserSessionsStore,
} from "@/stores/browserSessions";
import { useOverlayStore } from "@/stores/overlay";
import type { BrowserBounds, BrowserNavState } from "@shared/browser-contract";
import { ArrowLeft, Globe, Plus, RotateCw, X } from "lucide-react";
import {
  type FormEvent,
  type KeyboardEvent,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

const HYDRATE_DEBOUNCE_MS = 120;

/** 云端 Sandbox 无法打开用户本机环回地址。 */
export function isLocalhostBrowserUrl(url: string): boolean {
  try {
    const host = new URL(url).hostname.toLowerCase();
    return (
      host === "localhost" ||
      host === "127.0.0.1" ||
      host === "[::1]" ||
      host === "::1"
    );
  } catch {
    return false;
  }
}

export function BrowserPanel({
  conversationId,
  liveAvailable: _liveAvailable,
}: {
  conversationId: string | null;
  /** 本会话曾有 browser_* 活动（tab 条件常驻）；直播挂载以 serverSessionId 为准。 */
  liveAvailable: boolean;
}) {
  const allPages = useBrowserSessionsStore((s) => s.pages);
  const activePageId = useBrowserSessionsStore((s) => s.activePageId);
  const createPage = useBrowserSessionsStore((s) => s.createPage);
  const closePage = useBrowserSessionsStore((s) => s.closePage);
  const closeServerPage = useBrowserSessionsStore((s) => s.closeServerPage);
  const setActivePage = useBrowserSessionsStore((s) => s.setActivePage);
  const navigatePage = useBrowserSessionsStore((s) => s.navigatePage);
  const attachServerSession = useBrowserSessionsStore(
    (s) => s.attachServerSession,
  );
  const ensureBlankPage = useBrowserSessionsStore((s) => s.ensureBlankPage);
  const hydrateConversation = useBrowserSessionsStore(
    (s) => s.hydrateConversation,
  );

  const pages = useMemo(
    () => allPages.filter((p) => p.conversationId === conversationId),
    [allPages, conversationId],
  );
  const activePage =
    pages.find((p) => p.id === activePageId) ?? pages[pages.length - 1] ?? null;

  // 打开壳时保证至少一页（`+` / 自动补 tab 共用）——本地空白，不 POST。
  useEffect(() => {
    ensureBlankPage(conversationId);
  }, [conversationId, ensureBlankPage]);

  // mount / conversation 切换 → debounce hydrate（inflight 在 store 内合并）。
  const hydrateTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const scheduleHydrate = useCallback(() => {
    if (!conversationId) return;
    if (hydrateTimer.current) clearTimeout(hydrateTimer.current);
    hydrateTimer.current = setTimeout(() => {
      hydrateTimer.current = null;
      void hydrateConversation(conversationId).catch((err) => {
        notifyError(err, "同步浏览器页签失败");
      });
    }, HYDRATE_DEBOUNCE_MS);
  }, [conversationId, hydrateConversation]);

  useEffect(() => {
    scheduleHydrate();
    return () => {
      if (hydrateTimer.current) clearTimeout(hydrateTimer.current);
    };
  }, [scheduleHydrate]);

  // 窗口重新聚焦时再拉一次（会话可能已被 Agent 新建/关掉）。
  useEffect(() => {
    if (!conversationId) return;
    const onFocus = () => scheduleHydrate();
    window.addEventListener("focus", onFocus);
    return () => window.removeEventListener("focus", onFocus);
  }, [conversationId, scheduleHydrate]);

  const [draftUrl, setDraftUrl] = useState("");
  const [nav, setNav] = useState<BrowserNavState | null>(null);

  useEffect(() => {
    setDraftUrl(activePage?.url ?? "");
    setNav(null);
  }, [activePage?.id, activePage?.url]);

  const browserApi =
    typeof window !== "undefined" ? window.browserApi : undefined;
  const obstructed = useOverlayStore((s) => s.count > 0);
  /**
   * SSE 直播：当前激活页是 server session，且非「本机真画面优先」。
   * Local + browserApi 仍走 WebContents；无 browserApi（含 Web / 远程观众）走 LivePanel。
   */
  const preferLocalHost =
    activePage?.hostKind === "local" && Boolean(browserApi);
  const showLive =
    Boolean(activePage?.serverSessionId) &&
    Boolean(conversationId) &&
    !preferLocalHost;
  /** 本机真画面：非 live 页，且有 browserApi。 */
  const useLocalHost = !showLive && Boolean(browserApi);
  const localVisible = useLocalHost && !obstructed;

  const hostRef = useRef<HTMLDivElement>(null);

  const measure = useCallback((): BrowserBounds | null => {
    const el = hostRef.current;
    if (!el) return null;
    const r = el.getBoundingClientRect();
    if (r.width <= 0 || r.height <= 0) return null;
    return { x: r.left, y: r.top, width: r.width, height: r.height };
  }, []);

  // 本机视图显隐 + bounds；激活页变 → 重新 show（url 变更由 onSubmit 导航，不重挂）。
  useEffect(() => {
    if (!browserApi || !useLocalHost) {
      browserApi?.hide();
      return;
    }
    if (!localVisible || !activePage) {
      browserApi.hide();
      return;
    }
    const pageId = activePage.id;
    const pageUrl = activePage.url;
    let raf = 0;
    let shown = false;
    const sync = () => {
      cancelAnimationFrame(raf);
      raf = requestAnimationFrame(() => {
        const b = measure();
        if (!b) return;
        if (shown) {
          browserApi.setBounds(b);
        } else {
          shown = true;
          void browserApi.show({ pageId, bounds: b }).then((r) => {
            if (r.ok && pageUrl) {
              void browserApi.navigate({ pageId, url: pageUrl });
            }
          });
        }
      });
    };
    sync();
    const ro = new ResizeObserver(sync);
    const el = hostRef.current;
    if (el) ro.observe(el);
    window.addEventListener("resize", sync);
    return () => {
      cancelAnimationFrame(raf);
      ro.disconnect();
      window.removeEventListener("resize", sync);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- 仅 pageId 切换时重挂；url 由地址栏驱动
  }, [browserApi, useLocalHost, localVisible, activePage?.id, measure]);

  // 卸载 → hide 保活（关页才 close）。
  useEffect(() => {
    return () => {
      window.browserApi?.hide();
    };
  }, []);

  useEffect(() => {
    if (!browserApi) return;
    return browserApi.onNavState((state) => {
      setNav(state);
      if (state.pageId === activePageId && state.url && state.url !== "about:blank") {
        setDraftUrl(state.url);
      }
    });
  }, [browserApi, activePageId]);

  const onSubmitUrl = (e: FormEvent) => {
    e.preventDefault();
    if (!activePage) return;
    navigatePage(activePage.id, draftUrl);
    const normalized = normalizeBrowserUrl(draftUrl);
    if (!normalized) return;

    // 桌面 Local 真画面路径（有 browserApi）。
    if (browserApi && useLocalHost) {
      const pageId = activePage.id;
      void (async () => {
        const b = measure();
        if (b) {
          const shown = await browserApi.show({ pageId, bounds: b });
          if (!shown.ok) {
            notifyError(new Error(shown.reason), "无法打开本机浏览器");
            return;
          }
        }
        const r = await browserApi.navigate({ pageId, url: normalized });
        if (!r.ok) {
          notifyError(new Error(r.reason), "无法打开该地址");
          return;
        }
        const sid = activePage.serverSessionId;
        const cid = activePage.conversationId;
        if (sid && cid) {
          void patchBrowserSessionNav(cid, sid, {
            url: normalized,
            title: activePage.title || null,
          }).catch(() => {});
        }
      })();
      return;
    }

    // Web / 无 browserApi：Sandbox create + navigate。
    if (!conversationId) return;
    if (isLocalhostBrowserUrl(normalized)) {
      notifyError(
        new Error("当前为云端浏览器，无法打开本机 localhost"),
        "无法打开该地址",
      );
      return;
    }
    const pageId = activePage.id;
    void (async () => {
      try {
        let sid = activePage.serverSessionId ?? null;
        if (!sid) {
          const created = await createBrowserSession(conversationId, {
            hostKind: "sandbox",
            activate: true,
          });
          sid = created.sessionId;
          attachServerSession(pageId, {
            sessionId: created.sessionId,
            hostKind: created.hostKind,
            control: created.control,
          });
          await hydrateConversation(conversationId);
        }
        await navigateBrowserSession(conversationId, sid, normalized);
        navigatePage(pageId, normalized);
      } catch (err) {
        notifyError(err, "无法打开云端浏览器");
      }
    })();
  };

  const onUrlKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Escape") {
      setDraftUrl(activePage?.url ?? "");
      (e.target as HTMLInputElement).blur();
    }
  };

  const onNewPage = () => {
    // 本地空白页——不 POST …/browser/sessions（避免开真 gVisor）。
    createPage({ conversationId, url: "", title: "新标签页" });
  };

  const onClosePage = (pageId: string) => {
    const page = pages.find((p) => p.id === pageId);
    if (page?.serverSessionId && page.conversationId) {
      void closeServerPage(pageId).catch((err) => {
        notifyError(err, "关闭浏览器会话失败");
      });
      return;
    }
    browserApi?.close(pageId);
    closePage(pageId);
  };

  const canGoBack =
    Boolean(nav && nav.pageId === activePage?.id && nav.canGoBack);
  const canReload = Boolean(
    useLocalHost &&
      activePage &&
      (activePage.url || (nav && nav.pageId === activePage.id && nav.url && nav.url !== "about:blank")),
  );

  const showPlaceholder = !showLive && !useLocalHost;

  return (
    <div className="flex h-full flex-col bg-card">
      {/* 页签条 */}
      <div className="flex h-9 shrink-0 items-center gap-0.5 border-b border-border bg-muted/30 px-1">
        <div className="flex min-w-0 flex-1 items-center gap-0.5 overflow-x-auto">
          {pages.map((page) => {
            const active = page.id === activePage?.id;
            return (
              <div
                key={page.id}
                className={`group/btab flex max-w-[140px] shrink-0 items-center rounded-md ${
                  active
                    ? "bg-background text-foreground shadow-sm"
                    : "text-muted-foreground hover:bg-accent/50"
                }`}
              >
                <Button
                  variant="ghost"
                  onClick={() => setActivePage(page.id)}
                  className="h-7 max-w-[110px] truncate rounded-none px-2 py-0 text-xs font-normal"
                  icon={<Globe size={12} className="shrink-0 opacity-60" />}
                >
                  {page.title || "新标签页"}
                </Button>
                <IconButton
                  size="sm"
                  onClick={() => onClosePage(page.id)}
                  aria-label={`关闭 ${page.title || "新标签页"}`}
                  className="mr-0.5 size-5 opacity-0 group-hover/btab:opacity-100"
                >
                  <X size={11} />
                </IconButton>
              </div>
            );
          })}
        </div>
        <IconButton
          size="sm"
          onClick={onNewPage}
          aria-label="新标签页"
          title="新标签页"
        >
          <Plus size={14} />
        </IconButton>
      </div>

      {/* 导航条：后退 / 刷新 / 地址栏 */}
      <form
        onSubmit={onSubmitUrl}
        className="flex h-9 shrink-0 items-center gap-1 border-b border-border px-1.5"
      >
        <IconButton
          size="sm"
          disabled={!canGoBack || !activePage}
          onClick={() => activePage && browserApi?.back(activePage.id)}
          aria-label="后退"
          title={canGoBack ? "后退" : "后退"}
        >
          <ArrowLeft size={14} />
        </IconButton>
        <IconButton
          size="sm"
          disabled={!canReload || !activePage}
          onClick={() => activePage && browserApi?.reload(activePage.id)}
          aria-label="刷新"
          title={canReload ? "刷新" : "刷新"}
        >
          <RotateCw size={14} />
        </IconButton>
        <Input
          value={draftUrl}
          onChange={(e) => setDraftUrl(e.target.value)}
          onKeyDown={onUrlKeyDown}
          placeholder="输入地址开始浏览"
          aria-label="地址栏"
          className="h-7 min-w-0 flex-1 rounded-full px-3 text-xs"
          spellCheck={false}
          autoComplete="off"
        />
      </form>

      {/* 内容区 */}
      <div className="relative min-h-0 flex-1">
        {showLive ? (
          <BrowserLivePanel
            key={activePage!.serverSessionId!}
            conversationId={conversationId!}
            sessionId={activePage!.serverSessionId!}
          />
        ) : useLocalHost ? (
          <div className="flex h-full min-h-0 flex-col">
            {/* 有 serverSessionId 才挂接管条（D8 随时）；无 sid = 纯本地预览 → 隐藏接管。 */}
            {activePage?.serverSessionId && conversationId ? (
              <BrowserLocalTakeoverBar
                conversationId={conversationId}
                sessionId={activePage.serverSessionId}
              />
            ) : null}
            <div ref={hostRef} className="relative min-h-0 flex-1 bg-muted/20">
              <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center gap-2 text-muted-foreground/50">
                <Globe size={22} />
                <span className="text-xs">
                  {activePage?.url ? "页面加载中…" : "输入地址开始浏览"}
                </span>
              </div>
            </div>
          </div>
        ) : showPlaceholder ? (
          <div className="flex h-full flex-col items-center justify-center gap-2 px-6 text-center">
            <Globe size={28} className="text-muted-foreground/40" />
            <p className="text-sm text-muted-foreground">输入地址开始浏览</p>
            <p className="text-xs text-muted-foreground/70">
              在上方地址栏输入网址并回车；AI 使用浏览器时，画面会出现在这里。
            </p>
          </div>
        ) : null}
      </div>
    </div>
  );
}
