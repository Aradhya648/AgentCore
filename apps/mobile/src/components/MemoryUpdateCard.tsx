// Memory-write notices (two-layer memory). Episodic = light tip; semantic = diff list.
// Mobile has no per-user firehose; ChatPage polls after message_end.
import type { MemoryUpdate } from "@/api/conversations";
import { Brain, ChevronRight, NotebookPen } from "lucide-react";
import { useNavigate } from "react-router-dom";

const ACTION_META: Record<string, { label: string; cls: string }> = {
  add: { label: "新增", cls: "mem-add" },
  update: { label: "更新", cls: "mem-update-on" },
  remove: { label: "移除", cls: "mem-remove" },
};

function scopeLabel(scope: string): string {
  return scope === "project" ? "本项目" : "全局";
}

function formatWhen(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(
    d.getHours(),
  )}:${pad(d.getMinutes())}`;
}

export function MemoryUpdateCard({ updates }: { updates: MemoryUpdate[] }) {
  const navigate = useNavigate();
  const visible = updates.filter((u) =>
    u.kind === "episodic"
      ? Boolean((u.summary ?? "").trim())
      : u.items.length > 0 || Boolean((u.summary ?? "").trim()),
  );
  if (visible.length === 0) return null;

  return (
    <div className="mem-updates">
      {visible.map((u) =>
        u.kind === "episodic" ? (
          <div key={u.id} className="mem-update mem-update-episodic">
            <div className="mem-update-head">
              <NotebookPen size={15} className="mem-update-icon" aria-hidden />
              <span className="mem-update-title">已记下本场摘要</span>
              <span className="mem-update-when">{formatWhen(u.createdAt)}</span>
            </div>
            <p className="mem-episodic-summary">{(u.summary ?? "").trim()}</p>
          </div>
        ) : (
          <div key={u.id} className="mem-update">
            <div className="mem-update-head">
              <Brain size={15} className="mem-update-icon" aria-hidden />
              <span className="mem-update-title">
                {u.items.length > 0
                  ? "记忆已更新"
                  : (u.summary ?? "记忆已整理")}
              </span>
              {u.items.length > 0 && (
                <span className="mem-update-count">{u.items.length} 项</span>
              )}
              <span className="mem-update-when">{formatWhen(u.createdAt)}</span>
            </div>
            {u.items.length > 0 && (
              <ul className="mem-update-list">
                {u.items.map((it) => {
                  const meta = ACTION_META[it.action] ?? {
                    label: it.action,
                    cls: "mem-update-other",
                  };
                  const leaf = it.section
                    ? `${it.file} · ${it.section}`
                    : it.file;
                  const removed = it.action === "remove";
                  return (
                    <li
                      key={`${it.action}:${it.file}:${it.section}:${it.content}`}
                      className="mem-item"
                    >
                      <span className={`mem-action ${meta.cls}`}>
                        {meta.label}
                      </span>
                      <div className="mem-item-body">
                        <div className="mem-item-meta">
                          <span className="mem-item-leaf">{leaf}</span>
                          <span className="mem-item-scope">
                            {scopeLabel(it.scope)}
                          </span>
                        </div>
                        {it.content && (
                          <p
                            className={`mem-item-text${
                              removed ? " mem-item-removed" : ""
                            }`}
                          >
                            {it.content}
                          </p>
                        )}
                      </div>
                    </li>
                  );
                })}
              </ul>
            )}
            <button
              type="button"
              className="mem-update-link"
              onClick={() => navigate("/memory#updates")}
            >
              在「AI 记忆」中查看
              <ChevronRight size={14} aria-hidden />
            </button>
          </div>
        ),
      )}
    </div>
  );
}
