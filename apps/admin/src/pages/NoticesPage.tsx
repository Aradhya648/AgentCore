import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { Spinner } from "@/components/ui/Spinner";
import { cn, fmtTime } from "@/lib/utils";
import { errorMessage } from "@/services/api";
import {
  type CreateNoticeRequest,
  type Notice,
  type NoticeDismissPolicy,
  type NoticeSeverity,
  type NoticeStatus,
  type NoticeSurface,
  type UpdateNoticeRequest,
  archiveNotice,
  createNotice,
  listNotices,
  publishNotice,
  updateNotice,
} from "@/services/adminNotices";
import {
  Archive,
  Megaphone,
  Pencil,
  Plus,
  RefreshCw,
  Send,
  X,
} from "lucide-react";
import { type FormEvent, useCallback, useEffect, useState } from "react";
import { toast } from "sonner";

type Tone = "success" | "neutral" | "warning" | "destructive" | "primary";

const STATUS: Record<NoticeStatus, { label: string; tone: Tone }> = {
  draft: { label: "草稿", tone: "neutral" },
  published: { label: "已发布", tone: "success" },
  archived: { label: "已归档", tone: "warning" },
};

const SEVERITY: Record<NoticeSeverity, { label: string; tone: Tone }> = {
  critical: { label: "紧急", tone: "destructive" },
  high: { label: "重要", tone: "warning" },
  normal: { label: "普通", tone: "neutral" },
};

const SURFACE: Record<NoticeSurface, string> = {
  banner: "横幅",
  inbox: "IM 官方号",
  both: "横幅 + IM 官方号",
};

const DISMISS: Record<NoticeDismissPolicy, string> = {
  once: "可关闭（不回潮）",
  never: "横幅可关、官方号常驻",
};

const PAGE_SIZE = 50;

type StatusFilter = NoticeStatus | "all";

type FormState = {
  title: string;
  body: string;
  severity: NoticeSeverity;
  surface: NoticeSurface;
  dismiss_policy: NoticeDismissPolicy;
  cta_label: string;
  cta_url: string;
  start_at: string;
  end_at: string;
};

const EMPTY_FORM: FormState = {
  title: "",
  body: "",
  severity: "normal",
  surface: "both",
  dismiss_policy: "once",
  cta_label: "",
  cta_url: "",
  start_at: "",
  end_at: "",
};

/** ISO → `datetime-local` value in local timezone. */
function toLocalInput(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}`;
}

/** `datetime-local` → ISO, or null when blank. */
function fromLocalInput(value: string): string | null {
  const trimmed = value.trim();
  if (!trimmed) return null;
  const d = new Date(trimmed);
  if (Number.isNaN(d.getTime())) return null;
  return d.toISOString();
}

function noticeToForm(n: Notice): FormState {
  return {
    title: n.title,
    body: n.body,
    severity: (n.severity as NoticeSeverity) || "normal",
    surface: (n.surface as NoticeSurface) || "both",
    dismiss_policy: (n.dismiss_policy as NoticeDismissPolicy) || "once",
    cta_label: n.cta_label ?? "",
    cta_url: n.cta_url ?? "",
    start_at: toLocalInput(n.start_at),
    end_at: toLocalInput(n.end_at),
  };
}

function buildCreateBody(form: FormState): CreateNoticeRequest {
  return {
    title: form.title.trim(),
    body: form.body.trim(),
    severity: form.severity,
    surface: form.surface,
    dismiss_policy: form.dismiss_policy,
    cta_label: form.cta_label.trim() || null,
    cta_url: form.cta_url.trim() || null,
    start_at: fromLocalInput(form.start_at),
    end_at: fromLocalInput(form.end_at),
  };
}

function buildUpdateBody(form: FormState): UpdateNoticeRequest {
  return {
    title: form.title.trim(),
    body: form.body.trim(),
    severity: form.severity,
    surface: form.surface,
    dismiss_policy: form.dismiss_policy,
    cta_label: form.cta_label.trim() || null,
    cta_url: form.cta_url.trim() || null,
    start_at: fromLocalInput(form.start_at),
    end_at: fromLocalInput(form.end_at),
  };
}

function asStatus(raw: string): NoticeStatus {
  if (raw === "draft" || raw === "published" || raw === "archived") return raw;
  return "draft";
}

export function NoticesPage() {
  const [notices, setNotices] = useState<Notice[]>([]);
  const [total, setTotal] = useState(0);
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState<Notice | "new" | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await listNotices({
        status: statusFilter === "all" ? undefined : statusFilter,
        limit: PAGE_SIZE,
        offset: 0,
      });
      setNotices(res.data);
      setTotal(res.total);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  }, [statusFilter]);

  useEffect(() => {
    void load();
  }, [load]);

  const upsertLocal = (updated: Notice) => {
    setNotices((prev) => {
      const idx = prev.findIndex((n) => n.id === updated.id);
      if (idx < 0) return [updated, ...prev];
      const next = [...prev];
      next[idx] = updated;
      return next;
    });
  };

  const handlePublish = async (notice: Notice) => {
    if (busyId) return;
    setBusyId(notice.id);
    try {
      const updated = await publishNotice(notice.id);
      upsertLocal(updated);
      toast.success("公告已发布");
      if (statusFilter !== "all" && statusFilter !== "published") {
        void load();
      }
    } catch (err) {
      toast.error(errorMessage(err));
    } finally {
      setBusyId(null);
    }
  };

  const handleArchive = async (notice: Notice) => {
    if (busyId) return;
    setBusyId(notice.id);
    try {
      const updated = await archiveNotice(notice.id);
      upsertLocal(updated);
      toast.success("公告已归档");
      if (statusFilter !== "all" && statusFilter !== "archived") {
        void load();
      }
    } catch (err) {
      toast.error(errorMessage(err));
    } finally {
      setBusyId(null);
    }
  };

  const onSaved = (saved: Notice, isNew: boolean) => {
    setEditing(null);
    if (isNew) {
      toast.success("草稿已创建");
      void load();
    } else {
      toast.success("公告已更新");
      upsertLocal(saved);
    }
  };

  return (
    <div className="mx-auto max-w-[1200px] px-6 py-8">
      <div className="mb-6 flex items-center justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold text-foreground">公告</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            产品全局 Notice · 发布后写入桌面顶栏横幅与/或 IM「AgentCore 官方」· 共{" "}
            {total} 条
            {statusFilter === "all"
              ? ""
              : `（筛选：${STATUS[statusFilter].label}）`}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button size="sm" onClick={() => setEditing("new")}>
            <Plus size={14} />
            新建公告
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={() => void load()}
            disabled={loading}
            aria-label="刷新"
          >
            <RefreshCw size={14} className={cn(loading && "animate-spin")} />
          </Button>
        </div>
      </div>

      <div className="mb-4 flex flex-wrap items-center gap-2">
        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value as StatusFilter)}
          aria-label="按状态筛选"
          className="h-9 rounded-lg border border-input bg-card px-2 text-sm text-foreground outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          <option value="all">全部状态</option>
          <option value="draft">草稿</option>
          <option value="published">已发布</option>
          <option value="archived">已归档</option>
        </select>
      </div>

      <div className="overflow-hidden rounded-xl border border-border bg-card">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-border border-b bg-muted/40 text-left text-xs text-muted-foreground">
              <th className="px-5 py-2.5 font-medium">标题</th>
              <th className="px-5 py-2.5 font-medium">状态</th>
              <th className="px-5 py-2.5 font-medium">级别</th>
              <th className="px-5 py-2.5 font-medium">展示面</th>
              <th className="px-5 py-2.5 font-medium">关闭策略</th>
              <th className="px-5 py-2.5 font-medium">更新时间</th>
              <th className="px-5 py-2.5 text-right font-medium">操作</th>
            </tr>
          </thead>
          <tbody>
            {notices.map((n) => {
              const status = asStatus(n.status);
              const s = STATUS[status];
              const sev = SEVERITY[(n.severity as NoticeSeverity) || "normal"] ??
                SEVERITY.normal;
              const surface =
                SURFACE[(n.surface as NoticeSurface) || "both"] ?? n.surface;
              const dismiss =
                DISMISS[(n.dismiss_policy as NoticeDismissPolicy) || "once"] ??
                n.dismiss_policy;
              const rowBusy = busyId === n.id;
              const editable = status !== "archived";
              return (
                <tr
                  key={n.id}
                  className="border-border border-b last:border-0 hover:bg-accent/40"
                >
                  <td className="px-5 py-3">
                    <div className="font-medium text-foreground">{n.title}</div>
                    <div className="mt-0.5 line-clamp-1 text-xs text-muted-foreground">
                      {n.body}
                    </div>
                  </td>
                  <td className="px-5 py-3">
                    <Badge tone={s.tone}>{s.label}</Badge>
                  </td>
                  <td className="px-5 py-3">
                    <Badge tone={sev.tone}>{sev.label}</Badge>
                  </td>
                  <td className="px-5 py-3 text-muted-foreground">{surface}</td>
                  <td className="px-5 py-3 text-muted-foreground">{dismiss}</td>
                  <td className="px-5 py-3 text-muted-foreground tabular-nums">
                    {fmtTime(n.updated_at)}
                  </td>
                  <td className="px-5 py-3 text-right">
                    <div className="flex items-center justify-end gap-1">
                      {editable && (
                        <Button
                          variant="ghost"
                          size="sm"
                          disabled={rowBusy}
                          onClick={() => setEditing(n)}
                        >
                          <Pencil size={14} />
                          编辑
                        </Button>
                      )}
                      {status === "draft" && (
                        <Button
                          variant="ghost"
                          size="sm"
                          disabled={rowBusy}
                          onClick={() => void handlePublish(n)}
                        >
                          {rowBusy ? <Spinner /> : <Send size={14} />}
                          发布
                        </Button>
                      )}
                      {status !== "archived" && (
                        <Button
                          variant="ghost"
                          size="sm"
                          className="text-destructive"
                          disabled={rowBusy}
                          onClick={() => void handleArchive(n)}
                        >
                          {rowBusy ? <Spinner /> : <Archive size={14} />}
                          归档
                        </Button>
                      )}
                      {status === "archived" && (
                        <span className="text-muted-foreground">—</span>
                      )}
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>

        {loading && (
          <div className="flex items-center justify-center gap-2 py-10 text-muted-foreground text-sm">
            <Spinner />
            加载中…
          </div>
        )}
        {!loading && error && (
          <div className="flex flex-col items-center gap-3 py-10 text-sm">
            <span className="text-destructive">{error}</span>
            <Button variant="outline" size="sm" onClick={() => void load()}>
              重试
            </Button>
          </div>
        )}
        {!loading && !error && notices.length === 0 && (
          <div className="flex flex-col items-center gap-3 py-12 text-center text-muted-foreground text-sm">
            <Megaphone size={24} className="text-muted-foreground/60" />
            {statusFilter === "all"
              ? "还没有公告，点击「新建公告」创建第一条"
              : `没有「${STATUS[statusFilter].label}」状态的公告`}
          </div>
        )}
      </div>

      {editing && (
        <NoticeFormDialog
          notice={editing === "new" ? null : editing}
          onClose={() => setEditing(null)}
          onSaved={onSaved}
        />
      )}
    </div>
  );
}

function NoticeFormDialog({
  notice,
  onClose,
  onSaved,
}: {
  notice: Notice | null;
  onClose: () => void;
  onSaved: (saved: Notice, isNew: boolean) => void;
}) {
  const isNew = notice === null;
  const [form, setForm] = useState<FormState>(
    () => (notice ? noticeToForm(notice) : EMPTY_FORM),
  );
  const [saving, setSaving] = useState(false);

  const set =
    <K extends keyof FormState>(key: K) =>
    (value: FormState[K]) =>
      setForm((prev) => ({ ...prev, [key]: value }));

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (saving) return;
    if (!form.title.trim()) {
      toast.error("请填写标题");
      return;
    }
    if (!form.body.trim()) {
      toast.error("请填写正文");
      return;
    }
    setSaving(true);
    try {
      if (isNew) {
        const created = await createNotice(buildCreateBody(form));
        onSaved(created, true);
      } else {
        const updated = await updateNotice(
          notice.id,
          buildUpdateBody(form),
        );
        onSaved(updated, false);
      }
    } catch (err) {
      toast.error(errorMessage(err));
      setSaving(false);
    }
  };

  const selectClass =
    "h-9 w-full rounded-lg border border-input bg-card px-2 text-sm text-foreground outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50";

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-overlay px-6"
      onMouseDown={onClose}
    >
      <div
        className="flex max-h-[90vh] w-full max-w-lg flex-col rounded-xl border border-border bg-card p-5 shadow-lg"
        onMouseDown={(e) => e.stopPropagation()}
      >
        <div className="mb-4 flex shrink-0 items-start justify-between gap-3">
          <div>
            <h2 className="text-base font-semibold text-foreground">
              {isNew ? "新建公告" : "编辑公告"}
            </h2>
            <p className="mt-0.5 text-xs text-muted-foreground">
              {isNew
                ? "创建后为草稿；首次发布且含官方号展示面时，会写入 IM「AgentCore 官方」一条共享卡片"
                : "已归档不可改；已发布内容修改后立即对用户生效（不回填历史 IM）"}
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="关闭"
            className="flex size-7 items-center justify-center rounded-lg text-muted-foreground hover:bg-accent hover:text-accent-foreground"
          >
            <X size={16} />
          </button>
        </div>

        <form
          onSubmit={handleSubmit}
          className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto"
        >
          <label className="flex flex-col gap-1.5">
            <span className="text-xs font-medium text-muted-foreground">
              标题
            </span>
            <Input
              value={form.title}
              onChange={(e) => set("title")(e.target.value)}
              placeholder="简短标题"
              autoFocus
              required
            />
          </label>

          <label className="flex flex-col gap-1.5">
            <span className="text-xs font-medium text-muted-foreground">
              正文
            </span>
            <textarea
              value={form.body}
              onChange={(e) => set("body")(e.target.value)}
              placeholder="公告正文"
              required
              rows={5}
              className="w-full rounded-lg border border-input bg-card px-3 py-2 text-sm text-foreground outline-none transition-colors placeholder:text-muted-foreground focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50"
            />
          </label>

          <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
            <label className="flex flex-col gap-1.5">
              <span className="text-xs font-medium text-muted-foreground">
                级别
              </span>
              <select
                value={form.severity}
                onChange={(e) =>
                  set("severity")(e.target.value as NoticeSeverity)
                }
                className={selectClass}
              >
                <option value="normal">普通</option>
                <option value="high">重要</option>
                <option value="critical">紧急</option>
              </select>
            </label>
            <label className="flex flex-col gap-1.5">
              <span className="text-xs font-medium text-muted-foreground">
                展示面
              </span>
              <select
                value={form.surface}
                onChange={(e) =>
                  set("surface")(e.target.value as NoticeSurface)
                }
                className={selectClass}
              >
                <option value="both">横幅 + IM 官方号</option>
                <option value="banner">仅横幅</option>
                <option value="inbox">仅 IM 官方号</option>
              </select>
            </label>
            <label className="flex flex-col gap-1.5">
              <span className="text-xs font-medium text-muted-foreground">
                关闭策略
              </span>
              <select
                value={form.dismiss_policy}
                onChange={(e) =>
                  set("dismiss_policy")(
                    e.target.value as NoticeDismissPolicy,
                  )
                }
                className={selectClass}
              >
                <option value="once">可关闭（不回潮）</option>
                <option value="never">横幅可关、官方号常驻</option>
              </select>
            </label>
          </div>

          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <label className="flex flex-col gap-1.5">
              <span className="text-xs font-medium text-muted-foreground">
                CTA 文案
              </span>
              <Input
                value={form.cta_label}
                onChange={(e) => set("cta_label")(e.target.value)}
                placeholder="可选，如「了解更多」"
              />
            </label>
            <label className="flex flex-col gap-1.5">
              <span className="text-xs font-medium text-muted-foreground">
                CTA 链接
              </span>
              <Input
                value={form.cta_url}
                onChange={(e) => set("cta_url")(e.target.value)}
                placeholder="可选，https://…"
              />
            </label>
          </div>

          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <label className="flex flex-col gap-1.5">
              <span className="text-xs font-medium text-muted-foreground">
                开始时间
              </span>
              <Input
                type="datetime-local"
                value={form.start_at}
                onChange={(e) => set("start_at")(e.target.value)}
              />
            </label>
            <label className="flex flex-col gap-1.5">
              <span className="text-xs font-medium text-muted-foreground">
                结束时间
              </span>
              <Input
                type="datetime-local"
                value={form.end_at}
                onChange={(e) => set("end_at")(e.target.value)}
              />
            </label>
          </div>

          <div className="mt-1 flex shrink-0 justify-end gap-2">
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={onClose}
              disabled={saving}
            >
              取消
            </Button>
            <Button type="submit" size="sm" disabled={saving}>
              {saving && <Spinner />}
              {isNew ? "创建草稿" : "保存"}
            </Button>
          </div>
        </form>
      </div>
    </div>
  );
}
