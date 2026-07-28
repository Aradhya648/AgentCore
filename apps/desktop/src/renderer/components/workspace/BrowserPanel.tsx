/**
 * 右坞唯一浏览器壳——页签条 + 可编辑地址栏 + 新页；内容区：
 * - 有 serverSessionId 且非 preferLocalHost → {@link BrowserLivePanel}（SSE jpeg）；
 * - Local + 有 browserApi → 本机 WebContents 真画面（screencast 只服务远程观众）；
 * - Local 有 serverSessionId 时挂 {@link BrowserLocalTakeoverBar}（无 sid 隐藏接管）。
 *
 * 有 conversationId 时 mount / 聚焦 hydrate（list sessions）；空白页不 POST create。
 * 关闭带 serverSessionId 的页 → DELETE + browserApi.close(裸 sid) 再本地移除；
 * 本机空白页 → browserApi.close(React page id)。
 *
 * Local+serverSession 时 browserApi 一律用裸 serverSessionId（与 Bridge/Registry 同轨）；
 * React 页签 id 仍可为 `browser-server:${sid}`。
 *
 * 地址栏回车：
 * - 有 browserApi → store + browserApi.navigate（Local 真画面）；
 * - 无 browserApi（Web）→ sandbox create（若无 sid）+ POST navigate；拒 localhost。
 */
import { Button, IconButton, Input } from "@/components/ui";
import { BrowserLivePanel } from "@/components/workspace/BrowserLivePanel";
import { BrowserLocalTakeoverBar } from "@/components/workspace/BrowserLocalTakeoverBar";
import { isBrowserTool } from "@/lib/browserActivity";
import { notifyError } from "@/lib/toast";
import {
  createBrowserSession,
  navigateBrowserSession,
  patchBrowserSessionNav,
} from "@/services/browserSessions";
import {
  hostBrowserPageId,
  normalizeBrowserUrl,
  useBrowserSessionsStore,
} from "@/stores/browserSessions";
import { useConversationStore } from "@/stores/conversation";
import {
  assistantProjectionId,
  runtimeOf,
} from "@/stores/conversation/runtime";
import { projectRuntime, useExecutionStore } from "@/stores/execution";
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
  liveAvailable,
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

  // browser_* 步进指纹：工具进行中/结束后触发重 hydrate（对齐裸 session 真 view）。
  const browserToolSig = useExecutionStore((s) => {
    if (!conversationId) return "";
    const messages = runtimeOf(
      useConversationStore.getState(),
      conversationId,
    ).messages;
    const parts: string[] = [];
    for (const msg of messages) {
      if (msg.role !== "assistant") continue;
      const rt = s.byId[assistantProjectionId(msg)];
      if (!rt) continue;
      const exec = projectRuntime(rt);
      if (!exec) continue;
      for (const agent of exec.agents) {
        for (const tc of agent.toolCalls) {
          if (isBrowserTool(tc.toolName)) {
            parts.push(`${tc.id}:${tc.status}`);
          }
        }
      }
    }
    return parts.join("|");
  });

  // mount / conversation 切换 → debounce hydrate（inflight 在 store 内合并）；
  // 完成后若仍无页才 ensureBlank（勿在 hydrate 前用本地空白抢激活）。
  const hydrateTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const scheduleHydrate = useCallback(() => {
    if (!conversationId) {
      ensureBlankPage(null);
      return;
    }
    if (hydrateTimer.current) clearTimeout(hydrateTimer.current);
    hydrateTimer.current = setTimeout(() => {
      hydrateTimer.current = null;
      void hydrateConversation(conversationId)
        .catch((err) => {
          notifyError(err, "同步浏览器页签失败");
        })
        .finally(() => {
          const scoped = useBrowserSessionsStore
            .getState()
            .pagesFor(conversationId);
          if (scoped.length === 0) {
            ensureBlankPage(conversationId);
          }
        });
    }, HYDRATE_DEBOUNCE_MS);
  }, [conversationId, hydrateConversation, ensureBlankPage]);

  useEffect(() => {
    scheduleHydrate();
    return () => {
      if (hydrateTimer.current) clearTimeout(hydrateTimer.current);
    };
  }, [scheduleHydrate]);

  // 有 browser 活动 / 工具步进变化 → 再 hydrate（Agent 已建 session 时对齐激活页）。
  useEffect(() => {
    if (!conversationId) return;
    if (!liveAvailable && !browserToolSig) return;
    scheduleHydrate();
  }, [conversationId, liveAvailable, browserToolSig, scheduleHydrate]);

  // 窗口重新聚焦时再拉一次（会话可能已被 Agent 新建/关掉）。
  useEffect(() => {
    if (!conversationId) return;
    const onFocus = () => scheduleHydrate();
    window.addEventListener("focus", onFocus);
    return () => window.removeEventListener("focus", onFocus);
  }, [conversationId, scheduleHydrate]);

  const [draftUrl, setDraftUrl] = useState("");
  const [nav, setNav] = useState<BrowserNavState | null>(null);

  // biome-ignore lint/correctness/useExhaustiveDependencies: activePage?.id is an intentional re-run key when switching tabs with same url
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

  const hostPageId = activePage ? hostBrowserPageId(activePage) : null;
  const pageUrlRef = useRef(activePage?.url ?? "");
  pageUrlRef.current = activePage?.url ?? "";

  // 本机视图显隐 + bounds；激活页变 → 重新 show（url 变更由 onSubmit 导航，不重挂）。
  // Attachment：仅本 panel 可 show；cleanup / 不可见路径必须 detach（awaitable hide）。
  useEffect(() => {
    if (!browserApi || !useLocalHost) {
      void browserApi?.hide();
      return;
    }
    const cid = activePage?.conversationId ?? conversationId;
    if (!localVisible || !hostPageId || !cid) {
      void browserApi.hide();
      return;
    }
    const pageId = hostPageId;
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
          void browserApi
            .show({ pageId, bounds: b, conversationId: cid })
            .then((r) => {
              const pageUrl = pageUrlRef.current;
              if (r.ok && pageUrl) {
                void browserApi.navigate({
                  pageId,
                  url: pageUrl,
                  conversationId: cid,
                });
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
      // 依赖变 / 卸载：脱离附着（与 show 串行；过期 in-flight show 拒）。
      void browserApi.hide();
    };
  }, [
    browserApi,
    useLocalHost,
    localVisible,
    hostPageId,
    measure,
    activePage?.conversationId,
    conversationId,
  ]);

  // 卸载 → hide 保活（关页才 close）。
  useEffect(() => {
    return () => {
      void window.browserApi?.hide();
    };
  }, []);

  useEffect(() => {
    if (!browserApi) return;
    const hostId = activePage ? hostBrowserPageId(activePage) : activePageId;
    return browserApi.onNavState((state) => {
      setNav(state);
      if (
        hostId &&
        state.pageId === hostId &&
        state.url &&
        state.url !== "about:blank"
      ) {
        setDraftUrl(state.url);
      }
    });
  }, [browserApi, activePageId, activePage]);

  const onSubmitUrl = (e: FormEvent) => {
    e.preventDefault();
    if (!activePage) return;
    navigatePage(activePage.id, draftUrl);
    const normalized = normalizeBrowserUrl(draftUrl);
    if (!normalized) return;

    // 桌面 Local 真画面路径（有 browserApi）。
    if (browserApi && useLocalHost) {
      const pageId = hostBrowserPageId(activePage);
      const cid = activePage.conversationId ?? conversationId;
      if (!cid) {
        notifyError(new Error("缺少 conversationId"), "无法打开本机浏览器");
        return;
      }
      void (async () => {
        const b = measure();
        if (b) {
          const shown = await browserApi.show({
            pageId,
            bounds: b,
            conversationId: cid,
          });
          if (!shown.ok) {
            notifyError(new Error(shown.reason), "无法打开本机浏览器");
            return;
          }
        }
        const r = await browserApi.navigate({
          pageId,
          url: normalized,
          conversationId: cid,
        });
        if (!r.ok) {
          notifyError(new Error(r.reason), "无法打开该地址");
          return;
        }
        const sid = activePage.serverSessionId;
        if (sid) {
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
      // DELETE 之外须销毁本机 WebContents（裸 sid = Bridge 同轨）；失败仅降级日志。
      try {
        browserApi?.close(page.serverSessionId);
      } catch (err) {
        console.warn(
          "[browser] close local host after server DELETE failed",
          err,
        );
      }
      void closeServerPage(pageId).catch((err) => {
        notifyError(err, "关闭浏览器会话失败");
      });
      return;
    }
    if (page) browserApi?.close(hostBrowserPageId(page));
    else browserApi?.close(pageId);
    closePage(pageId);
  };

  const hostId = activePage ? hostBrowserPageId(activePage) : null;
  const canGoBack = Boolean(
    nav && hostId && nav.pageId === hostId && nav.canGoBack,
  );
  const canReload = Boolean(
    useLocalHost &&
      activePage &&
      (activePage.url ||
        (nav &&
          hostId &&
          nav.pageId === hostId &&
          nav.url &&
          nav.url !== "about:blank")),
  );

  const showPlaceholder = !showLive && !useLocalHost;

  return (
    <div className="flex h-full flex-col bg-card">
      {/* 页签条 */}
      <div className="flex h-10 shrink-0 items-center gap-0.5 border-b border-border bg-muted/30 px-1.5 py-1">
        <div className="flex min-w-0 flex-1 items-center gap-0.5 overflow-x-auto">
          {pages.map((page) => {
            const active = page.id === activePage?.id;
            return (
              <div
                key={page.id}
                className={`group/btab flex max-w-[140px] shrink-0 items-center rounded-lg ${
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
        className="flex h-10 shrink-0 items-center gap-1 border-b border-border px-2 py-1"
      >
        <IconButton
          size="sm"
          disabled={!canGoBack || !activePage}
          onClick={() =>
            activePage && browserApi?.back(hostBrowserPageId(activePage))
          }
          aria-label="后退"
          title={canGoBack ? "后退" : "后退"}
        >
          <ArrowLeft size={14} />
        </IconButton>
        <IconButton
          size="sm"
          disabled={!canReload || !activePage}
          onClick={() =>
            activePage && browserApi?.reload(hostBrowserPageId(activePage))
          }
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
        {showLive && conversationId && activePage?.serverSessionId ? (
          <BrowserLivePanel
            key={activePage.serverSessionId}
            conversationId={conversationId}
            sessionId={activePage.serverSessionId}
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
