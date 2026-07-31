import { ChatView } from "@/components/chat/ChatView";
import {
  ConversationHydrateOverlay,
  type ConversationHydratePhase,
} from "@/components/chat/ConversationHydrateOverlay";
import { ConversationCanvas } from "@/components/graph/ConversationCanvas";
import { SidePanel } from "@/components/layout/SidePanel";
import { SidePanelToggle } from "@/components/layout/SidePanelToggle";
import { Button } from "@/components/ui";
import { getConversations } from "@/hooks/useConversations";
import { logEvent } from "@/lib/log";
import { reconcileExternalGrants } from "@/lib/reconcileExternalGrants";
import {
  fetchMessageWindow,
  jumpToMessage,
  shouldSetGeneratingOnHydrate,
} from "@/services/messages";
import {
  cacheOpenedConversation,
  loadCachedConversation,
} from "@/services/offlineCache";
import { loadRecovery } from "@/services/resume";
import { runHydrateAttachSettle } from "@/services/turns";
import { useBookmarkStore } from "@/stores/bookmarks";
import {
  type MemoryUpdate,
  type Message,
  getRuntime,
  useConversationStore,
} from "@/stores/conversation";
import { WORKSPACE_TAB_ID, useSidePanelStore } from "@/stores/sidePanel";
import { useUIStore } from "@/stores/ui";
import { MessageSquare, Network } from "lucide-react";
import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";

/** Read the `msg` query of the current hash route (#/conversations/:id?msg=<id>).
 * Parsed off window.location so the load effect need not depend on router search state. */
function readMsgAnchor(): string | null {
  const hash = window.location.hash;
  const q = hash.indexOf("?");
  if (q === -1) return null;
  return new URLSearchParams(hash.slice(q + 1)).get("msg");
}

function adoptMessageWindow(
  id: string,
  messages: Message[],
  flags: { hasMoreBefore: boolean; hasMoreAfter: boolean },
  memoryUpdates: MemoryUpdate[],
): boolean {
  const s = useConversationStore.getState();
  if (s.currentConversationId !== id) return false;
  const rt = getRuntime(id);
  if (rt.isGenerating || rt.messages.length > 0) return false;
  s.setMessageWindow(messages, flags, id);
  s.setMemoryUpdates(memoryUpdates, id);
  if (shouldSetGeneratingOnHydrate(messages)) {
    s.setGenerating(true, id);
  }
  return true;
}

async function persistOpenedCache(
  id: string,
  messages: Message[],
  memoryUpdates: MemoryUpdate[],
  flags: { hasMoreBefore: boolean; hasMoreAfter: boolean },
): Promise<void> {
  const listed = getConversations().find((c) => c.id === id);
  const conversation = listed ?? {
    id,
    title: "对话",
    updatedAt: new Date().toISOString(),
    messageCount: messages.length,
    lastMessagePreview: messages.at(-1)?.content?.slice(0, 80) ?? null,
  };
  await cacheOpenedConversation({
    conversation,
    messages,
    memoryUpdates,
    hasMoreBefore: flags.hasMoreBefore,
    hasMoreAfter: flags.hasMoreAfter,
  });
}

export function ConversationPage() {
  const { id } = useParams<{ id: string }>();
  const [hydratePhase, setHydratePhase] =
    useState<ConversationHydratePhase>("ready");
  const [hydrateRetry, setHydrateRetry] = useState(0);

  // 路由参数是 conversation 的真相来源（刷新/前进后退/直达链接时同步到 store），
  // 并从后端拉取最新一窗消息（含附件元信息）以恢复对话；更早的历史按需上滚加载。
  // biome-ignore lint/correctness/useExhaustiveDependencies: hydrateRetry is an intentional re-run key
  useEffect(() => {
    const store = useConversationStore.getState();
    // 索引路由 `/` = 新草稿：丢弃上一条已打开的会话，渲染空白对话。这样无论从哪个
    // 入口落到 `/`（导航「对话」、Ctrl/Cmd+N、刷新直达），看到的都是新对话，而不是
    // store 里残留的上次对话。draftWorkspaceIntent 不在这里碰——那是「新建对话」入口
    // 设置的落库目标（见 startNewConversation），清掉会破坏「全部对话」按项目新建。
    if (!id) {
      if (store.currentConversationId !== null) store.switchConversation(null);
      setHydratePhase("ready");
      return;
    }
    if (id !== store.currentConversationId) store.switchConversation(id);

    // Load this conversation's recovery snapshot on reopen (recovery 统一, 对称 §8.2):
    // ONE owner-gated read that both (a) surfaces any turn paused at a plan_review /
    // ask_user checkpoint then disconnected (结构化挂起 2b) as a resume card above the
    // composer, and (b) reports whether a detached run is still live to 续看. Best-effort
    // + independent of the history load, so it never blocks rendering the conversation.
    // Kept as a promise (not fire-and-forget) so the reattach decision below can gate on
    // its result — see the attach block. `loadRecovery` never rejects (it swallows its own
    // errors), so the handle is safe to leave unawaited on the paths that skip the gate.
    const recoveryLoaded = loadRecovery(id);

    const warm =
      getRuntime(id).messages.length > 0 || getRuntime(id).isGenerating;
    setHydratePhase(warm ? "ready" : "loading");

    let cancelled = false;
    let attachAbort: AbortController | null = null;
    void (async () => {
      try {
        const win = await fetchMessageWindow(id);
        if (cancelled) return;
        // Adopt only overwrites an empty cold slice; warm reopen (messages
        // already in memory) skips overwrite but still runs attach/settle.
        const adopted = adoptMessageWindow(
          id,
          win.messages,
          {
            hasMoreBefore: win.hasMoreBefore,
            hasMoreAfter: win.hasMoreAfter,
          },
          win.memoryUpdates,
        );
        if (adopted) {
          void persistOpenedCache(id, win.messages, win.memoryUpdates, {
            hasMoreBefore: win.hasMoreBefore,
            hasMoreAfter: win.hasMoreAfter,
          });
        }
        if (cancelled) return;
        if (useConversationStore.getState().currentConversationId !== id) {
          return;
        }
        // P4 unified hydrate: recovery + attach/settle independent of adopt.
        // Branch on main-process facts (D6 二次修订) — never resolveSidecarRoot
        // (routing intent / React Query cache; empty on refresh cold start).
        const recovery = await recoveryLoaded;
        if (cancelled) return;
        // Await + abort on leave: serialize hydrate attach; 切会话停旧泵
        // （claim 释放），避免 fire-and-forget 叠第二个 onEvent。
        attachAbort = new AbortController();
        await runHydrateAttachSettle(id, recovery, {
          signal: attachAbort.signal,
        });
        if (cancelled) return;
        if (!cancelled) setHydratePhase("ready");
      } catch {
        // N4-A: network / outage → fall back to local-store snapshot for this id.
        if (cancelled) return;
        const cached = await loadCachedConversation(id);
        if (cancelled) return;
        if (cached) {
          adoptMessageWindow(
            id,
            cached.messages as Message[],
            {
              hasMoreBefore: cached.hasMoreBefore,
              hasMoreAfter: cached.hasMoreAfter,
            },
            cached.memoryUpdates as MemoryUpdate[],
          );
          logEvent("info", "conversation.hydrate", {
            conversation_id: id,
            branch: "offline_cache",
          });
          setHydratePhase("ready");
        } else if (!warm) {
          // No cache + cold slice: explicit error (never silent blank like a draft).
          setHydratePhase("error");
          return;
        }
      }
      // Honor a search-hit jump that navigated in from elsewhere: now that this
      // conversation's window is loaded, land on the hit (in-window → scroll;
      // outside → load-around). Runs after the load so it sees real messages.
      if (cancelled) return;
      const jumpStore = useConversationStore.getState();
      const pending = jumpStore.pendingFocus;
      if (pending && pending.conversationId === id) {
        jumpStore.clearPendingFocus();
        void jumpToMessage(id, pending.messageId);
      } else {
        // 消息永久链接 (对话基础功能补齐): a #/conversations/:id?msg=<messageId> anchor
        // (from「复制消息链接」or the web build) lands on the exact turn. Read the hash
        // query imperatively so the load effect stays keyed on [id] alone — re-parsing
        // via useSearchParams would fold URL churn into the deps and re-fetch the window.
        const target = readMsgAnchor();
        if (target) void jumpToMessage(id, target);
      }
    })();
    return () => {
      cancelled = true;
      attachAbort?.abort();
    };
  }, [id, hydrateRetry]);

  // 消息收藏 star state (方向 4): load which of this conversation's messages are
  // bookmarked so their bubbles render a filled star. Best-effort + independent of
  // the history load (a failed fetch just leaves stars empty).
  useEffect(() => {
    if (!id) return;
    void useBookmarkStore.getState().hydrateForConversation(id);
  }, [id]);

  // W3: reconcile desktop session roots ↔ server external-grants on open
  // (补登记 / 清孤儿). Paths stay on desktop; best-effort, never blocks hydrate.
  useEffect(() => {
    if (!id) return;
    void reconcileExternalGrants(id);
  }, [id]);

  // Page-scoped shortcuts for the single side panel: Ctrl/Cmd+I shows / hides it
  // (keeping the active tab), Ctrl/Cmd+J reveals it straight on the 工作区 home
  // tab. Scoped here (not the global shell) as both are only meaningful on the
  // conversation page. (Ctrl/Cmd+B is reserved by the shell for the left sidebar
  // collapse, so the panel takes I to avoid the double-fire.)
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (!(e.ctrlKey || e.metaKey)) return;
      if (e.key === "i" || e.key === "I") {
        e.preventDefault();
        useSidePanelStore.getState().togglePanel();
      } else if (e.key === "j" || e.key === "J") {
        e.preventDefault();
        // Smart toggle: reveal the 工作区 home tab, or dismiss the panel if it's
        // already there (press again to close, like the old dedicated dock).
        const s = useSidePanelStore.getState();
        if (s.open && s.activeTabId === WORKSPACE_TAB_ID) s.closePanel();
        else s.showWorkspace();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  // 聊天 ⇄ 画布双视图（前端UX设计.md §六）。默认聊天；用户在顶栏切到画布（按对话记忆、
  // 持久化）。画布已毕业、入口恒显示；草稿（无 id）恒为聊天。
  // 右坞：打开后头栏 PanelRight 关闭；关闭时主区右上浮层打开（Ctrl/Cmd+I 始终可用）。
  const panelOpen = useSidePanelStore((s) => s.open);
  const conversationView = useUIStore((s) =>
    id ? (s.conversationViews[id] ?? "chat") : "chat",
  );
  const setConversationView = useUIStore((s) => s.setConversationView);
  const canvasMode = !!id && conversationView === "canvas";

  return (
    <>
      {canvasMode ? <ConversationCanvas /> : <ChatView />}
      {id && (
        <ConversationHydrateOverlay
          phase={hydratePhase}
          onRetry={() => setHydrateRetry((n) => n + 1)}
        />
      )}
      {/* 视图切换段控件（聊天 ⇄ 画布），置于左上。 */}
      {id && (
        <div className="absolute left-3 top-2 z-20 flex items-center gap-0.5 rounded-lg border border-border bg-card/80 p-0.5 backdrop-blur">
          <Button
            variant="ghost"
            onClick={() => setConversationView(id, "chat")}
            aria-pressed={!canvasMode}
            icon={<MessageSquare size={14} />}
            className={
              !canvasMode
                ? "bg-accent text-foreground hover:bg-accent"
                : undefined
            }
          >
            聊天
          </Button>
          <Button
            variant="ghost"
            onClick={() => setConversationView(id, "canvas")}
            aria-pressed={canvasMode}
            icon={<Network size={14} />}
            className={
              canvasMode
                ? "bg-accent text-foreground hover:bg-accent"
                : undefined
            }
          >
            画布
          </Button>
        </div>
      )}
      {id && !panelOpen && (
        <div className="absolute right-3 top-2 z-20">
          <SidePanelToggle />
        </div>
      )}
      <SidePanel />
    </>
  );
}
