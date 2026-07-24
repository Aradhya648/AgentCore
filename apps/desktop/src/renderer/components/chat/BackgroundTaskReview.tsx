import { Button, IconButton } from "@/components/ui";
import { StreamError } from "@/lib/errors";
import {
  type ReviewRow,
  buildReviewRows,
  buildSelections,
  countChanges,
} from "@/lib/handoff-review";
import {
  type HandoffApplySummary,
  applyHandoffJob,
  getHandoffDiff,
  readLocalShas,
} from "@/services/handoff";
import {
  AlertTriangle,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  CloudUpload,
  Loader2,
} from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

/**
 * 后台云端任务的内联简化评审（交接「方案 B」/ P2e e3）。
 *
 * 对标旧工作区「交接」PR 评审卡，但按「方案 B」简化：默认全部接受（干净变更直接应用），
 * 只把**真冲突**（你在云端跑期间改过的同一文件）逐个列出让你选「云端覆盖 / 保留本地」。
 * 三方判定 / 选择集 / 应用回写复用同一套权威逻辑（`lib/handoff-review` + `services/handoff`）：
 * 应用前对每个文件**重新读本地哈希**，服务端再按快照哈希权威复核冲突，故安全性与旧路径一致。
 */
export function BackgroundTaskReview({
  conversationId,
  jobId,
  rootId,
  onClose,
}: {
  conversationId: string;
  jobId: string;
  rootId: string;
  onClose: () => void;
}) {
  const [rows, setRows] = useState<ReviewRow[] | null>(null);
  const [error, setError] = useState(false);
  const [applying, setApplying] = useState(false);
  const [applyError, setApplyError] = useState<string | null>(null);
  const [summary, setSummary] = useState<HandoffApplySummary | null>(null);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  const load = useCallback(async () => {
    setError(false);
    setRows(null);
    setSummary(null);
    try {
      const diff = await getHandoffDiff(conversationId, jobId);
      const shas = await readLocalShas(
        rootId,
        diff.changes.map((c) => c.path),
      );
      if (mounted.current) setRows(buildReviewRows(diff.changes, shas));
    } catch {
      if (mounted.current) setError(true);
    }
  }, [conversationId, jobId, rootId]);

  useEffect(() => {
    void load();
  }, [load]);

  const setDecision = useCallback(
    (path: string, decision: ReviewRow["decision"]) => {
      setRows((prev) =>
        prev
          ? prev.map((r) => (r.change.path === path ? { ...r, decision } : r))
          : prev,
      );
    },
    [],
  );

  const toggleExpand = useCallback((path: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(path)) next.delete(path);
      else next.add(path);
      return next;
    });
  }, []);

  const onApply = useCallback(async () => {
    if (!rows || applying) return;
    setApplying(true);
    setApplyError(null);
    try {
      // Re-hash local right before writing so the server's conflict gate sees the
      // CURRENT disk state — a file edited since review opened is refused (a "take
      // cloud" pick on it turns conflict) rather than silently clobbered.
      const freshShas = await readLocalShas(
        rootId,
        rows.map((r) => r.change.path),
      );
      const selections = buildSelections(
        rows.map((r) => ({
          ...r,
          localSha: freshShas.get(r.change.path) ?? null,
        })),
      );
      const result = await applyHandoffJob(conversationId, jobId, selections);
      if (mounted.current) setSummary(result);
    } catch (err) {
      if (mounted.current) {
        setApplyError(
          err instanceof StreamError
            ? "应用失败：网络或服务异常"
            : err instanceof Error
              ? err.message
              : "应用失败",
        );
      }
    } finally {
      if (mounted.current) setApplying(false);
    }
  }, [rows, applying, conversationId, jobId, rootId]);

  if (error) {
    return (
      <Bar>
        <span className="text-muted-foreground">加载结果失败</span>
        <BarButton onClick={() => void load()}>重试</BarButton>
        <BarButton onClick={onClose}>收起</BarButton>
      </Bar>
    );
  }
  if (rows === null) {
    return (
      <Bar>
        <Loader2 size={13} className="animate-spin text-muted-foreground" />
        <span className="text-muted-foreground">正在读取结果…</span>
      </Bar>
    );
  }
  if (rows.length === 0) {
    return (
      <Bar>
        <CheckCircle2 size={13} className="text-success" />
        <span className="text-muted-foreground">
          云端结果与本地一致，无需改动。
        </span>
        <BarButton className="ml-auto" onClick={onClose}>
          收起
        </BarButton>
      </Bar>
    );
  }

  if (summary) {
    const parts: string[] = [];
    if (summary.applied) parts.push(`${summary.applied} 已应用`);
    if (summary.skipped) parts.push(`${summary.skipped} 跳过`);
    if (summary.conflicts) parts.push(`${summary.conflicts} 冲突`);
    if (summary.errors) parts.push(`${summary.errors} 失败`);
    return (
      <Bar>
        <CheckCircle2 size={14} className="shrink-0 text-success" />
        <span className="text-foreground">
          {parts.length ? parts.join(" · ") : "无变更"}
        </span>
        <BarButton className="ml-auto" onClick={onClose}>
          收起
        </BarButton>
      </Bar>
    );
  }

  const counts = countChanges(rows.map((r) => r.change));
  const conflicts = rows.filter((r) => r.verdict === "conflict");
  const forced = conflicts.filter((r) => r.decision === "cloud").length;

  return (
    <div className="mt-2 rounded-lg border border-border bg-card/60 p-2.5">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
        <span className="text-success">+{counts.added}</span>
        <span className="text-primary">~{counts.modified}</span>
        <span className="text-destructive">-{counts.deleted}</span>
        {conflicts.length > 0 ? (
          <span className="flex items-center gap-1 text-destructive">
            <AlertTriangle size={12} />
            {conflicts.length} 个与本地改动冲突，需你选择
          </span>
        ) : (
          <span className="text-muted-foreground">无冲突，可直接全部接受</span>
        )}
      </div>

      {conflicts.length > 0 && (
        <ul className="mt-2 space-y-1">
          {conflicts.map((row) => {
            const canPreview =
              !row.change.isBinary &&
              row.change.changeType !== "deleted" &&
              row.change.content !== null;
            const open = expanded.has(row.change.path);
            return (
              <li
                key={row.change.path}
                className="rounded-lg border border-destructive/40 bg-destructive/5"
              >
                <div className="flex items-center gap-1.5 px-2 py-1.5">
                  <IconButton
                    onClick={() => toggleExpand(row.change.path)}
                    disabled={!canPreview}
                    aria-label="展开预览"
                    className="size-5 rounded disabled:opacity-30"
                  >
                    {open ? (
                      <ChevronDown size={13} />
                    ) : (
                      <ChevronRight size={13} />
                    )}
                  </IconButton>
                  <span
                    className="min-w-0 flex-1 truncate text-xs"
                    title={row.change.path}
                  >
                    {row.change.path}
                  </span>
                  <DecisionToggle
                    active={row.decision === "cloud"}
                    danger
                    onClick={() => setDecision(row.change.path, "cloud")}
                    label="云端（覆盖）"
                  />
                  <DecisionToggle
                    active={row.decision === "local"}
                    onClick={() => setDecision(row.change.path, "local")}
                    label="保留本地"
                  />
                </div>
                {open && canPreview && (
                  <pre className="max-h-48 overflow-auto whitespace-pre-wrap break-words border-t border-destructive/30 px-2.5 py-2 font-mono text-xs leading-relaxed text-foreground">
                    {row.change.content}
                  </pre>
                )}
              </li>
            );
          })}
        </ul>
      )}

      {forced > 0 && (
        <p className="mt-2 flex items-center gap-1 text-xs text-destructive">
          <AlertTriangle size={12} />
          将强制覆盖 {forced} 个有本地改动的文件
        </p>
      )}
      {applyError && (
        <p className="mt-1.5 text-xs text-destructive">{applyError}</p>
      )}

      <div className="mt-2 flex items-center gap-2">
        <Button
          className="flex-1"
          icon={
            applying ? (
              <Loader2 size={13} className="animate-spin" />
            ) : (
              <CloudUpload size={13} />
            )
          }
          disabled={applying}
          onClick={() => void onApply()}
        >
          {conflicts.length === 0
            ? `全部接受并应用（${rows.length} 个文件）`
            : "应用所选改动"}
        </Button>
        <Button
          variant="neutral"
          className="border border-border"
          onClick={onClose}
        >
          收起
        </Button>
      </div>
    </div>
  );
}

/** 单行紧凑状态条（加载 / 空 / 错误 / 已应用汇总共用）。 */
function Bar({ children }: { children: React.ReactNode }) {
  return (
    <div className="mt-2 flex items-center gap-2 rounded-lg border border-border bg-card/60 px-2.5 py-2 text-xs">
      {children}
    </div>
  );
}

function BarButton({
  children,
  onClick,
  className = "",
}: {
  children: React.ReactNode;
  onClick: () => void;
  className?: string;
}) {
  return (
    <Button
      variant="neutral"
      onClick={onClick}
      className={`h-auto border border-border px-2 py-0.5 font-normal ${className}`}
    >
      {children}
    </Button>
  );
}

function DecisionToggle({
  active,
  onClick,
  label,
  danger,
}: {
  active: boolean;
  onClick: () => void;
  label: string;
  danger?: boolean;
}) {
  const cls = active
    ? danger
      ? "border-destructive bg-destructive/10 text-destructive"
      : "border-primary bg-primary/10 text-primary"
    : "border-transparent text-muted-foreground hover:bg-accent";
  return (
    <Button
      variant="ghost"
      onClick={onClick}
      className={`h-auto shrink-0 rounded-lg border px-2 py-0.5 text-xs font-medium ${cls}`}
    >
      {label}
    </Button>
  );
}
