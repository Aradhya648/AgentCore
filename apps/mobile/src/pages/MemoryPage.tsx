import { getTokens } from "@/api/client";
import {
  type MemoryKind,
  type MemoryUpdateFeedEntry,
  getMemory,
  getMemoryFile,
  getMemoryTopic,
  isFeatureUnavailable,
  listMemoryTopics,
  listMemoryUpdates,
  setMemoryEnabled,
  writeMemoryFile,
  writeMemoryTopic,
} from "@/api/memory";
// AI 记忆 (/memory) — the mobile 查看 + 改 + 删 lens on long-term memory (Agent记忆与知识系统
// §一). The desktop splits this across the 文件 page (content) + 设置 (switch); the phone's
// lite版 folds both into one page reached from the 文件 tab: a master switch, cross-
// conversation「最近更新」feed, the two always-injected GLOBAL core leaves (偏好 / 画像) as
// editable text, and the on-demand 主题 notes as a view/edit/delete list. GLOBAL scope
// only — per-project memory stays a desktop task (减法 boundary). Each section self-loads
// (mobile has no global store), and edits are CAS-guarded: a stale baseline reloads the
// live copy rather than clobbering it.
import { type ReactNode, useCallback, useEffect, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import "@/pages/more/more.css";

export function MemoryPage() {
  const navigate = useNavigate();
  const location = useLocation();

  // A 401 anywhere on the page (after apiFetch's refresh attempt) means the session is
  // gone — bounce to login, mirroring the other mobile pages' guard.
  const onAuthError = useCallback(
    (e: unknown) => {
      if (!getTokens()) navigate("/login", { replace: true });
      return e;
    },
    [navigate],
  );

  // Deep-link from the chat「记忆已更新」卡 (`/memory#updates`) — scroll the feed into view
  // once the page chrome is up (section mounts immediately; list may still be loading).
  useEffect(() => {
    if (location.hash !== "#updates") return;
    const el = document.getElementById("memory-updates");
    if (el) el.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [location.hash]);

  return (
    <div className="screen">
      <header className="bar">
        <button
          type="button"
          className="link"
          onClick={() => navigate("/files")}
        >
          ← 文件
        </button>
        <span>AI 记忆</span>
        <span style={{ width: 44 }} />
      </header>

      <div className="settings-body">
        <p className="settings-desc">
          AI
          会从对话里记下关于你的长期偏好与事实，并在后续对话中参考。你可以在这里查看、编辑或清空。
        </p>
        <EnableToggle onAuthError={onAuthError} />
        <RecentUpdates onAuthError={onAuthError} />
        <LeafEditor
          kind="preferences"
          title="偏好"
          note="你的长期偏好（全局）。留空并保存即清空。"
          onAuthError={onAuthError}
        />
        <LeafEditor
          kind="profile"
          title="画像"
          note="AI 对你的画像（全局）。留空并保存即清空。"
          onAuthError={onAuthError}
        />
        <TopicList onAuthError={onAuthError} />
      </div>
    </div>
  );
}

function Section({
  title,
  note,
  children,
}: {
  title: string;
  note?: string;
  children: ReactNode;
}) {
  return (
    <section className="section">
      <h2 className="section-title">{title}</h2>
      {note && <p className="section-note">{note}</p>}
      <div className="section-card">{children}</div>
    </section>
  );
}

/** Master switch — enable/disable long-term memory (content is kept when off). */
function EnableToggle({
  onAuthError,
}: { onAuthError: (e: unknown) => unknown }) {
  const [enabled, setEnabled] = useState<boolean | null>(null);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    getMemory()
      .then((d) => alive && setEnabled(d.enabled))
      .catch((e) => {
        onAuthError(e);
        if (alive) setError("加载记忆设置失败");
      });
    return () => {
      alive = false;
    };
  }, [onAuthError]);

  async function toggle() {
    if (enabled === null) return;
    setPending(true);
    setError(null);
    try {
      const d = await setMemoryEnabled(!enabled);
      setEnabled(d.enabled);
    } catch (e) {
      onAuthError(e);
      setError("设置失败，请重试");
    } finally {
      setPending(false);
    }
  }

  return (
    <Section
      title="启用 AI 记忆"
      note="停用后，AI 不再把记忆注入对话，也不会从新对话里自动更新记忆；已记住的内容会保留。"
    >
      <div className="mem-toggle-row">
        <span className="mem-toggle-state">
          {enabled === null ? "加载中…" : enabled ? "已启用" : "已停用"}
        </span>
        <button
          type="button"
          className={enabled ? "btn-outline" : ""}
          disabled={enabled === null || pending}
          onClick={() => void toggle()}
        >
          {pending ? "处理中…" : enabled ? "停用" : "启用"}
        </button>
      </div>
      {error && <p className="error">{error}</p>}
    </Section>
  );
}

const ACTION_META: Record<string, { label: string; cls: string }> = {
  add: { label: "新增", cls: "mem-add" },
  update: { label: "更新", cls: "mem-update-on" },
  remove: { label: "移除", cls: "mem-remove" },
};

function formatWhen(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(
    d.getHours(),
  )}:${pad(d.getMinutes())}`;
}

/**
 * Cross-conversation「最近更新」feed (§1.6) — answers「AI 最近都学了什么」. The chat-tail
 * card only covers the open thread; this is the write-side home on mobile (desktop's
 * MemoryUpdatesView lite). Deep-linked as `/memory#updates`.
 */
function RecentUpdates({
  onAuthError,
}: {
  onAuthError: (e: unknown) => unknown;
}) {
  const navigate = useNavigate();
  const [entries, setEntries] = useState<MemoryUpdateFeedEntry[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [unavailable, setUnavailable] = useState(false);

  const load = useCallback(() => {
    setError(null);
    setUnavailable(false);
    listMemoryUpdates(30)
      .then((rows) => setEntries(rows.filter((u) => u.items.length > 0)))
      .catch((e) => {
        onAuthError(e);
        if (isFeatureUnavailable(e)) {
          setUnavailable(true);
          setEntries([]);
        } else {
          setError("加载失败");
          setEntries([]);
        }
      });
  }, [onAuthError]);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <section className="section" id="memory-updates">
      <h2 className="section-title">最近更新</h2>
      <p className="section-note">
        AI
        最近从各处对话里记下的内容。整理在后台异步进行，刚聊完可能稍晚才出现。
      </p>
      <div className="section-card mem-feed">
        {entries === null ? (
          <p className="section-note">加载中…</p>
        ) : unavailable ? (
          <p className="section-note">暂不可用（后端尚未部署此接口）</p>
        ) : error ? (
          <>
            <p className="error">{error}</p>
            <button type="button" className="btn-outline" onClick={load}>
              重试
            </button>
          </>
        ) : entries.length === 0 ? (
          <p className="section-note">
            还没有记忆更新。AI
            会在对话后台整理长期记忆；记下新内容时，这里会按时间列出。
          </p>
        ) : (
          <div className="mem-updates">
            {entries.map((entry) => (
              <div key={entry.id} className="mem-update">
                <div className="mem-update-head">
                  <span className="mem-update-when mem-feed-when">
                    {formatWhen(entry.createdAt)}
                  </span>
                  <button
                    type="button"
                    className="mem-update-link mem-feed-source"
                    onClick={() => navigate(`/c/${entry.conversationId}`)}
                  >
                    查看来源对话
                  </button>
                </div>
                <ul className="mem-update-list">
                  {entry.items.map((it, i) => {
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
                        key={`${it.action}:${it.file}:${it.section}:${i}`}
                        className="mem-item"
                      >
                        <span className={`mem-action ${meta.cls}`}>
                          {meta.label}
                        </span>
                        <div className="mem-item-body">
                          <div className="mem-item-meta">
                            <span className="mem-item-leaf">{leaf}</span>
                            <span className="mem-item-scope">
                              {it.scope === "project" ? "本项目" : "全局"}
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
              </div>
            ))}
          </div>
        )}
      </div>
    </section>
  );
}

/** An editable always-injected core leaf (偏好 / 画像), CAS-guarded full-text edit. */
function LeafEditor({
  kind,
  title,
  note,
  onAuthError,
}: {
  kind: MemoryKind;
  title: string;
  note: string;
  onAuthError: (e: unknown) => unknown;
}) {
  const [loading, setLoading] = useState(true);
  const [content, setContent] = useState("");
  const [saved, setSaved] = useState("");
  const [version, setVersion] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    getMemoryFile(kind)
      .then((d) => {
        if (!alive) return;
        setContent(d.content);
        setSaved(d.content);
        setVersion(d.version);
      })
      .catch((e) => {
        onAuthError(e);
        if (alive) setError("加载失败");
      })
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
  }, [kind, onAuthError]);

  const dirty = content !== saved;

  async function save() {
    setSaving(true);
    setError(null);
    try {
      const r = await writeMemoryFile(kind, content, version);
      if (r.conflict) {
        // Someone (another device / the AI) wrote since we loaded — pull the live copy
        // so the user re-edits against it rather than clobbering it.
        const live = await getMemoryFile(kind);
        setContent(live.content);
        setSaved(live.content);
        setVersion(live.version);
        setError("内容已在别处更新，已为你刷新，请重新编辑后保存。");
        return;
      }
      setSaved(content);
      setVersion(r.version);
    } catch (e) {
      onAuthError(e);
      setError("保存失败，请重试");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Section title={title} note={note}>
      {loading ? (
        <p className="section-note">加载中…</p>
      ) : (
        <>
          <textarea
            className="mem-textarea"
            value={content}
            placeholder="（空）"
            rows={5}
            onChange={(e) => setContent(e.target.value)}
          />
          {error && <p className="error">{error}</p>}
          <div className="field-actions">
            <button
              type="button"
              disabled={!dirty || saving}
              onClick={() => void save()}
            >
              {saving ? "保存中…" : "保存"}
            </button>
          </div>
        </>
      )}
    </Section>
  );
}

/** The on-demand 主题 notes (view / edit / delete), GLOBAL layer. */
function TopicList({ onAuthError }: { onAuthError: (e: unknown) => unknown }) {
  const [slugs, setSlugs] = useState<string[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  // A 404/501 = this deployed backend predates the 主题 endpoint (前后端版本漂移). Held
  // apart from `error` so it shows as a calm note (服务端待升级), not a red failure.
  const [unavailable, setUnavailable] = useState(false);

  useEffect(() => {
    let alive = true;
    listMemoryTopics()
      .then((s) => alive && setSlugs(s))
      .catch((e) => {
        onAuthError(e);
        if (!alive) return;
        if (isFeatureUnavailable(e)) setUnavailable(true);
        else setError("加载主题失败");
        setSlugs([]);
      });
    return () => {
      alive = false;
    };
  }, [onAuthError]);

  return (
    <Section
      title="主题记忆"
      note="AI 按需查阅的主题笔记。可查看、编辑或删除。"
    >
      {slugs === null && !error && !unavailable && (
        <p className="section-note">加载中…</p>
      )}
      {unavailable && (
        <p className="section-note">主题记忆暂不可用（服务端待升级）。</p>
      )}
      {error && <p className="error">{error}</p>}
      {slugs !== null && slugs.length === 0 && !error && !unavailable && (
        <p className="section-note">还没有主题记忆。</p>
      )}
      {slugs?.map((slug) => (
        <TopicItem
          key={slug}
          slug={slug}
          onDeleted={() =>
            setSlugs((prev) => (prev ?? []).filter((s) => s !== slug))
          }
          onAuthError={onAuthError}
        />
      ))}
    </Section>
  );
}

/** One 主题 note — collapsed to a row, expands to a CAS-guarded editor + delete. */
function TopicItem({
  slug,
  onDeleted,
  onAuthError,
}: {
  slug: string;
  onDeleted: () => void;
  onAuthError: (e: unknown) => unknown;
}) {
  const [open, setOpen] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [content, setContent] = useState("");
  const [saved, setSaved] = useState("");
  const [version, setVersion] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function expand() {
    const next = !open;
    setOpen(next);
    if (!next || loaded) return;
    setError(null);
    try {
      const d = await getMemoryTopic(slug);
      setContent(d.content);
      setSaved(d.content);
      setVersion(d.version);
      setLoaded(true);
    } catch (e) {
      onAuthError(e);
      setError("加载失败");
    }
  }

  async function save() {
    setBusy(true);
    setError(null);
    try {
      const r = await writeMemoryTopic(slug, content, version);
      if (r.conflict) {
        const live = await getMemoryTopic(slug);
        setContent(live.content);
        setSaved(live.content);
        setVersion(live.version);
        setError("内容已在别处更新，已为你刷新，请重新编辑后保存。");
        return;
      }
      setSaved(content);
      setVersion(r.version);
    } catch (e) {
      onAuthError(e);
      setError("保存失败，请重试");
    } finally {
      setBusy(false);
    }
  }

  async function remove() {
    if (!window.confirm(`确定删除记忆主题「${slug}」？此操作不可撤销。`))
      return;
    setBusy(true);
    setError(null);
    try {
      const r = await writeMemoryTopic(slug, "", null);
      if (!r.ok) throw new Error("写入冲突");
      onDeleted();
    } catch (e) {
      onAuthError(e);
      setError("删除失败，请重试");
      setBusy(false);
    }
  }

  const dirty = loaded && content !== saved;

  return (
    <div className="mem-topic">
      <button
        type="button"
        className="mem-topic-head"
        aria-expanded={open}
        onClick={() => void expand()}
      >
        <span className="mem-topic-name">{slug}.md</span>
        <span className="mem-topic-chevron" aria-hidden>
          {open ? "▾" : "›"}
        </span>
      </button>
      {open && (
        <div className="mem-topic-body">
          {!loaded && !error ? (
            <p className="section-note">加载中…</p>
          ) : (
            <>
              <textarea
                className="mem-textarea"
                value={content}
                rows={5}
                onChange={(e) => setContent(e.target.value)}
              />
              {error && <p className="error">{error}</p>}
              <div className="field-actions">
                <button
                  type="button"
                  className="btn-danger-outline"
                  disabled={busy}
                  onClick={() => void remove()}
                >
                  删除
                </button>
                <button
                  type="button"
                  disabled={!dirty || busy}
                  onClick={() => void save()}
                >
                  {busy ? "处理中…" : "保存"}
                </button>
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
}
