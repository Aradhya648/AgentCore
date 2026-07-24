import {
  type CollaborationTimelineItem,
  fetchCollaborationTimeline,
  formatActChain,
} from "@/api/collaborationTimeline";
// 项目协作时间线 · 手机降级：文字摘要列表（会话 + 幕序列），无可缩放大图。
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

function folderIdFromWs(wsId: string): string | null {
  const id = (wsId || "").trim();
  if (id.startsWith("folder:")) return id.slice("folder:".length) || null;
  return null;
}

export function CollaborationSummaryList({ wsId }: { wsId: string }) {
  const folderId = folderIdFromWs(wsId);
  const navigate = useNavigate();
  const [items, setItems] = useState<CollaborationTimelineItem[] | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!folderId) {
      setItems([]);
      return;
    }
    let cancelled = false;
    setItems(null);
    setError(null);
    fetchCollaborationTimeline(folderId, { limit: 20 })
      .then((res) => {
        if (cancelled) return;
        setItems(res.items ?? []);
        setNote(res.dossier_refs_note ?? null);
      })
      .catch((e) => {
        if (cancelled) return;
        setError(e instanceof Error ? e.message : "加载协作摘要失败");
        setItems([]);
      });
    return () => {
      cancelled = true;
    };
  }, [folderId]);

  if (!folderId) return null;

  return (
    <section
      className="collab-summary"
      data-testid="collaboration-summary-list"
      aria-label="项目协作摘要"
    >
      <header className="collab-summary-head">
        <span>协作摘要</span>
        {items != null && <span className="muted tabular">{items.length}</span>}
      </header>
      {items === null && !error && <p className="muted hint">加载中…</p>}
      {error && <p className="error hint">{error}</p>}
      {items != null && items.length === 0 && !error && (
        <p className="muted hint">此项目尚无带协作图的会话</p>
      )}
      <ul className="collab-summary-list">
        {items?.map((it) => {
          const chain = formatActChain(it.acts);
          const refs = (it.dossier_refs ?? [])
            .map((r) => r.path.replace(/^research\//, ""))
            .join("、");
          return (
            <li key={it.conversation_id}>
              <button
                type="button"
                className="collab-summary-row"
                onClick={() => navigate(`/c/${it.conversation_id}`)}
              >
                <span className="collab-summary-title">
                  {it.title?.trim() || "未命名对话"}
                </span>
                {chain && (
                  <span className="collab-summary-acts muted">{chain}</span>
                )}
                {refs && (
                  <span className="collab-summary-refs muted">
                    读过案卷：{refs}
                  </span>
                )}
              </button>
            </li>
          );
        })}
      </ul>
      {note &&
        items != null &&
        items.some((i) => (i.dossier_refs?.length ?? 0) > 0) && (
          <p className="muted hint collab-summary-note">{note}</p>
        )}
    </section>
  );
}
