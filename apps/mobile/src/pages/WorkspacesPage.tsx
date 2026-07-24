import { getTokens } from "@/api/client";
import { type WorkspaceSummary, listWorkspaces } from "@/api/workspaces";
import { Brain } from "lucide-react";
// 文件 tab home — the cross-workspace file overview (手机端布局重构 · 跨工作区文件总览).
//
// Lists the user's CLOUD workspaces (= folders); tapping one drills into its file tree
// (/files/:wsId). The mobile counterpart of the desktop 文件 hub, minus the desktop-only
// halves: LOCAL workspaces live on the user's machine (reached over desktop IPC; the server
// refuses file ops with 409), so the phone hides them — a 减法 boundary, surfaced as a note
// when the user has local-only workspaces. Folder lifecycle (新建/重命名/删除/绑定本地) stays a
// desktop task; the phone is a read/browse + upload lens. Re-fetches on each visit (the tab
// remounts), so files just produced in a chat appear without a manual refresh.
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

export function WorkspacesPage() {
  const navigate = useNavigate();
  const [items, setItems] = useState<WorkspaceSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setItems(null);
    setError(null);
    listWorkspaces()
      .then((ws) => {
        if (!cancelled) setItems(ws);
      })
      .catch((e) => {
        if (cancelled) return;
        if (!getTokens()) {
          navigate("/login", { replace: true });
          return;
        }
        setError(e instanceof Error ? e.message : "加载工作区失败");
        setItems([]);
      });
    return () => {
      cancelled = true;
    };
  }, [navigate]);

  const clouds = items?.filter((w) => w.location === "cloud") ?? [];
  const hasLocalOnly =
    items !== null &&
    clouds.length === 0 &&
    items.some((w) => w.location === "local");

  return (
    <div className="screen">
      <header className="bar">
        <span>文件</span>
      </header>

      <div className="list">
        <button
          type="button"
          className="file-row"
          onClick={() => navigate("/memory")}
        >
          <span className="file-icon" aria-hidden>
            <Brain size={16} />
          </span>
          <span className="file-name">AI 记忆</span>
          <span className="file-chevron" aria-hidden>
            ›
          </span>
        </button>

        {items === null && !error && <p className="muted hint">加载中…</p>}
        {error && <p className="error hint">{error}</p>}
        {items !== null && clouds.length === 0 && !error && (
          <p className="muted hint">
            {hasLocalOnly
              ? "云端工作区为空。本地工作区请在桌面端查看。"
              : "还没有工作区。开始对话并产出文件后，工作区会出现在这里。"}
          </p>
        )}
        {clouds.map((ws) => (
          <button
            key={ws.wsId}
            type="button"
            className="file-row"
            onClick={() =>
              navigate(`/files/${encodeURIComponent(ws.wsId)}`, {
                state: { name: ws.name },
              })
            }
          >
            <span className="file-icon" aria-hidden>
              ▸
            </span>
            <span className="file-name">{ws.name}</span>
            {!ws.hasFiles && <span className="file-tag">空</span>}
            <span className="file-chevron" aria-hidden>
              ›
            </span>
          </button>
        ))}
      </div>
    </div>
  );
}
