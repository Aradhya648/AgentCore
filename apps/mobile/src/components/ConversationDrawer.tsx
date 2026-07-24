import { getTokens } from "@/api/client";
import {
  type ConversationSummary,
  deleteConversation,
  listConversations,
  renameConversation,
  setConversationArchived,
} from "@/api/conversations";
import { type SearchSection, search } from "@/api/search";
import {
  ActionSheet,
  ConfirmDialog,
  RenameDialog,
  SearchResults,
  timeLabel,
} from "@/components/conversations";
import { SquarePen } from "lucide-react";
// 历史对话抽屉 (手机端对话页重设计 · 抽屉式直聊).
//
// The chat page is now「开盖即聊」(a fresh draft on the 对话 tab); the conversation history
// that used to be the landing list lives here, as a left slide-in drawer opened from the chat
// header's ☰. Mirrors the desktop sidebar's recent-conversations + the industry pattern
// (ChatGPT/Claude 左抽屉历史). Hosts the same management surface the old list page had —
// 搜索 / 已归档 / 行内 重命名·归档·删除 — reusing the shared primitives in conversations.tsx.
//
// Data is fetched lazily on open (and refetched when the archived view toggles), so a closed
// drawer costs nothing. Picking a conversation routes to /c/:id and closes; ✎ starts a new
// draft (routes to /, the draft home) and closes.
import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

export function ConversationDrawer({
  open,
  onClose,
  onOpen,
  activeId,
}: {
  open: boolean;
  onClose: () => void;
  onOpen: () => void;
  /** The conversation open in the chat behind the drawer — highlighted in the list. */
  activeId?: string;
}) {
  const navigate = useNavigate();
  const [items, setItems] = useState<ConversationSummary[] | null>(null);
  const [archivedView, setArchivedView] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  // Search (跨会话搜索) — independent of the archived view; an empty query shows the list.
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SearchSection[] | null>(null);
  const [searching, setSearching] = useState(false);
  // Per-row management surfaces.
  const [menuFor, setMenuFor] = useState<ConversationSummary | null>(null);
  const [renaming, setRenaming] = useState<ConversationSummary | null>(null);
  const [deleting, setDeleting] = useState<ConversationSummary | null>(null);
  // Drag gestures: left-edge swipe opens, leftward swipe on the open panel closes. The panel
  // follows the finger (`drag.x` = live translateX), then CSS settles on release. `open` and
  // the callbacks are read via refs so the touch listeners can attach exactly once.
  const edgeRef = useRef<HTMLDivElement>(null);
  const panelRef = useRef<HTMLElement>(null);
  const [drag, setDrag] = useState<{ x: number; frac: number } | null>(null);
  const dragXRef = useRef(0);
  const openRef = useRef(open);
  openRef.current = open;
  const onOpenRef = useRef(onOpen);
  onOpenRef.current = onOpen;
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;

  // Lazy fetch: only when open (a closed drawer costs nothing), and refetch when the
  // archived view toggles. A cleared token routes to login (mirrors the chat page gate).
  useEffect(() => {
    if (!open) return;
    setItems(null);
    setError(null);
    listConversations(archivedView)
      .then(setItems)
      .catch((e) => {
        if (!getTokens()) {
          navigate("/login", { replace: true });
          return;
        }
        setError(e instanceof Error ? e.message : "加载会话列表失败");
        setItems([]);
      });
  }, [open, archivedView, navigate]);

  // Reset transient surfaces when the drawer closes, so reopening is clean.
  useEffect(() => {
    if (open) return;
    setQuery("");
    setMenuFor(null);
    setRenaming(null);
    setDeleting(null);
  }, [open]);

  // Touch-drag open/close (attached once; reads state via refs). A drag from the left-edge
  // strip pulls the panel in; a leftward drag on the open panel pushes it out. Direction-
  // locked after 8px so a vertical list scroll or a row tap is never hijacked. touchmove is
  // non-passive so we can preventDefault once we've claimed a horizontal drag.
  useEffect(() => {
    const edge = edgeRef.current;
    const panel = panelRef.current;
    if (!edge || !panel) return;
    type Gesture = {
      startX: number;
      startY: number;
      w: number;
      mode: "pending" | "h" | "v";
      opening: boolean;
    };
    let g: Gesture | null = null;

    const begin = (opening: boolean, x: number, y: number) => {
      const w = panel.offsetWidth || Math.min(window.innerWidth * 0.84, 360);
      g = { startX: x, startY: y, w, mode: "pending", opening };
    };
    const onEdgeStart = (e: TouchEvent) => {
      if (openRef.current) return;
      const t = e.touches[0];
      if (t) begin(true, t.clientX, t.clientY);
    };
    const onPanelStart = (e: TouchEvent) => {
      if (!openRef.current) return;
      const t = e.touches[0];
      if (t) begin(false, t.clientX, t.clientY);
    };
    const onMove = (e: TouchEvent) => {
      if (!g) return;
      const t = e.touches[0];
      if (!t) return;
      const dx = t.clientX - g.startX;
      const dy = t.clientY - g.startY;
      if (g.mode === "pending") {
        if (Math.abs(dx) < 8 && Math.abs(dy) < 8) return;
        g.mode = Math.abs(dx) > Math.abs(dy) ? "h" : "v";
      }
      if (g.mode !== "h") return;
      if (g.opening && dx <= 0) return; // open needs a rightward pull
      if (!g.opening && dx >= 0) return; // close needs a leftward pull
      e.preventDefault(); // we own this gesture now — suppress scroll / text selection
      const x = g.opening
        ? Math.max(-g.w, Math.min(0, -g.w + dx))
        : Math.max(-g.w, Math.min(0, dx));
      dragXRef.current = x;
      setDrag({ x, frac: (x + g.w) / g.w });
    };
    const onEnd = () => {
      if (!g) return;
      const done = g;
      g = null;
      if (done.mode !== "h") return;
      const x = dragXRef.current;
      setDrag(null);
      // Past the halfway line wins; otherwise CSS snaps back to the controlled state.
      const revealed = x > -done.w / 2;
      if (done.opening && revealed) onOpenRef.current();
      else if (!done.opening && !revealed) onCloseRef.current();
    };

    edge.addEventListener("touchstart", onEdgeStart, { passive: true });
    panel.addEventListener("touchstart", onPanelStart, { passive: true });
    window.addEventListener("touchmove", onMove, { passive: false });
    window.addEventListener("touchend", onEnd, { passive: true });
    window.addEventListener("touchcancel", onEnd, { passive: true });
    return () => {
      edge.removeEventListener("touchstart", onEdgeStart);
      panel.removeEventListener("touchstart", onPanelStart);
      window.removeEventListener("touchmove", onMove);
      window.removeEventListener("touchend", onEnd);
      window.removeEventListener("touchcancel", onEnd);
    };
  }, []);

  // Debounced keyword search; `active` drops a stale response if the query moved on.
  useEffect(() => {
    if (!open) return;
    const q = query.trim();
    if (!q) {
      setResults(null);
      setSearching(false);
      return;
    }
    setSearching(true);
    let active = true;
    const handle = setTimeout(() => {
      search(q)
        .then((s) => active && setResults(s))
        .catch(() => active && setResults([]))
        .finally(() => active && setSearching(false));
    }, 250);
    return () => {
      active = false;
      clearTimeout(handle);
    };
  }, [query, open]);

  function openConversation(id: string | null) {
    if (!id) return;
    navigate(`/c/${id}`);
    onClose();
  }

  function newChat() {
    navigate("/");
    onClose();
  }

  async function doRename(conv: ConversationSummary, title: string) {
    setBusy(true);
    setError(null);
    try {
      const updated = await renameConversation(conv.id, title);
      setItems(
        (xs) =>
          xs?.map((x) =>
            x.id === conv.id ? { ...x, title: updated.title } : x,
          ) ?? xs,
      );
      setRenaming(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "重命名失败");
    } finally {
      setBusy(false);
    }
  }

  async function doArchiveToggle(conv: ConversationSummary) {
    setBusy(true);
    setError(null);
    try {
      await setConversationArchived(conv.id, !conv.archived);
      setItems((xs) => xs?.filter((x) => x.id !== conv.id) ?? xs);
      setMenuFor(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "操作失败");
    } finally {
      setBusy(false);
    }
  }

  async function doDelete(conv: ConversationSummary) {
    setBusy(true);
    setError(null);
    try {
      await deleteConversation(conv.id);
      setItems((xs) => xs?.filter((x) => x.id !== conv.id) ?? xs);
      setDeleting(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "删除失败");
    } finally {
      setBusy(false);
    }
  }

  const searchMode = query.trim().length > 0;

  return (
    <div
      className={`drawer-root${open ? " open" : ""}${drag ? " dragging" : ""}`}
      aria-hidden={!open && !drag}
    >
      {/* biome-ignore lint/a11y/useKeyWithClickEvents: backdrop is a supplementary tap-to-close */}
      <div
        className="drawer-backdrop"
        style={drag ? { opacity: drag.frac } : undefined}
        onClick={onClose}
      />
      {/* Left-edge strip that captures a swipe-to-open while the drawer is closed. */}
      <div className="drawer-edge" ref={edgeRef} aria-hidden />
      <aside
        className="drawer"
        ref={panelRef}
        style={drag ? { transform: `translateX(${drag.x}px)` } : undefined}
        // biome-ignore lint/a11y/useSemanticElements: swipe/drag drawer panel; migrating to native <dialog> (showModal/::backdrop) is a separate a11y task
        role="dialog"
        aria-modal={open}
        aria-label="对话历史"
      >
        <header className="bar">
          {archivedView ? (
            <button
              type="button"
              className="link"
              onClick={() => setArchivedView(false)}
            >
              ← 对话
            </button>
          ) : (
            <span>对话历史</span>
          )}
          <div className="bar-right">
            {!archivedView && (
              <button
                type="button"
                className="link"
                onClick={() => setArchivedView(true)}
              >
                已归档
              </button>
            )}
            <button
              type="button"
              className="link icon-btn"
              aria-label="新对话"
              onClick={newChat}
            >
              <SquarePen size={20} />
            </button>
          </div>
        </header>

        <div className="search">
          <input
            className="search-input"
            placeholder="搜索对话和消息…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          {query && (
            <button
              type="button"
              className="search-clear"
              aria-label="清除"
              onClick={() => setQuery("")}
            >
              ✕
            </button>
          )}
        </div>

        {searchMode ? (
          <SearchResults
            sections={results}
            searching={searching}
            onOpen={openConversation}
          />
        ) : (
          <div className="list">
            {items === null && !error && <p className="muted hint">加载中…</p>}
            {items?.length === 0 && (
              <p className="muted hint">
                {archivedView
                  ? "没有已归档的对话。"
                  : "还没有对话，点 ✎ 开始。"}
              </p>
            )}
            {items?.map((c) => (
              <div key={c.id} className="conv-row">
                <button
                  type="button"
                  className={`conv${c.id === activeId ? " conv-active" : ""}`}
                  onClick={() => openConversation(c.id)}
                >
                  <span className="conv-title">{c.title || "新对话"}</span>
                  <span className="conv-meta">
                    {c.message_count} 条 · {timeLabel(c.updated_at)}
                  </span>
                </button>
                <button
                  type="button"
                  className="conv-actions"
                  aria-label="更多操作"
                  onClick={() => setMenuFor(c)}
                >
                  ⋯
                </button>
              </div>
            ))}
          </div>
        )}

        {error && <div className="error bar">{error}</div>}
      </aside>

      {menuFor && (
        <ActionSheet
          conv={menuFor}
          archivedView={archivedView}
          onClose={() => setMenuFor(null)}
          onRename={() => {
            const c = menuFor;
            setMenuFor(null);
            setRenaming(c);
          }}
          onArchive={() => void doArchiveToggle(menuFor)}
          onDelete={() => {
            const c = menuFor;
            setMenuFor(null);
            setDeleting(c);
          }}
        />
      )}

      {renaming && (
        <RenameDialog
          conv={renaming}
          busy={busy}
          onClose={() => setRenaming(null)}
          onSave={(title) => void doRename(renaming, title)}
        />
      )}

      {deleting && (
        <ConfirmDialog
          title="删除对话"
          message={`删除「${deleting.title || "新对话"}」？此操作不可撤销。`}
          confirmLabel="删除"
          busy={busy}
          onCancel={() => setDeleting(null)}
          onConfirm={() => void doDelete(deleting)}
        />
      )}
    </div>
  );
}
