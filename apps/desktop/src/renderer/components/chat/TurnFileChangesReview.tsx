import { type DiffLine, lineDiff } from "@/components/chat/toolResult/diff";
import { Button } from "@/components/ui";
import { useConversationWorkspace } from "@/hooks/useWorkspaces";
import type { FileArtifact, FileChangePreview } from "@/lib/fileArtifacts";
import { notifyActionError, notifySuccess } from "@/lib/toast";
import {
  type TurnFileChange,
  getLocalTurnFilesDiff,
  getTurnFilesDiff,
  restoreLocalTurnBaseline,
} from "@/services/turnFilesDiff";
import { restoreSnapshot } from "@/services/workspace";
import { ChevronDown, ChevronRight, Loader2, RotateCcw } from "lucide-react";
import { useEffect, useMemo, useState, type ReactNode } from "react";

/**
 * A1 / A1+ 只读「查看改动」——挂在产物卡内。
 * 优先拉回合基线真 diff（A1+）；无基线 / 失败则降级工具参数预览（A1）。
 * 标签按路径相对回合初是否存在（新建/更新/删除），不按 file_write/str_replace 工具名。
 * 不做 apply / 三方冲突（与交接「查看并应用」刻意区分）。
 *
 * 信息架构：折叠头 = 唯一身份条（路径 + 变更态 + 行统计）；展开体 = 纯 diff / 预览，不再套路径标题。
 */

const WRITE_PREVIEW_LINES = 300;

/** 真 diff：按回合基线路径是否存在 → 新建/更新/删除（非工具名）。 */
function turnChangeLabel(changeType: TurnFileChange["changeType"]): string {
  if (changeType === "added") return "新建";
  if (changeType === "deleted") return "删除";
  return "更新";
}

/**
 * 无基线降级：工具参数预览无法判定「回合初是否存在」，
 * write/edit 一律标「更新」，勿用写入/编辑冒充用户语义。
 */
function previewKindLabel(change: FileChangePreview): string {
  if (change.kind === "delete") return "删除";
  if (change.kind === "move") return "移动";
  return "更新";
}

function writeModeLabel(mode: "overwrite" | "append" | "added"): string {
  if (mode === "append") return "追加";
  if (mode === "added") return "新建";
  return "更新";
}

function diffSign(type: DiffLine["type"]): string {
  if (type === "add") return "+";
  if (type === "del") return "-";
  return " ";
}

function diffRowClass(type: DiffLine["type"]): string {
  if (type === "add") return "bg-success/10 text-foreground";
  if (type === "del") return "bg-destructive/10 text-foreground";
  return "text-muted-foreground";
}

function summarizeLineDiff(oldText: string, newText: string): {
  lines: DiffLine[];
  adds: number;
  dels: number;
} {
  const lines = lineDiff(oldText, newText);
  let adds = 0;
  let dels = 0;
  for (const l of lines) {
    if (l.type === "add") adds += 1;
    else if (l.type === "del") dels += 1;
  }
  return { lines, adds, dels };
}

/** 展开体：纯行 diff，无路径标题（身份在折叠头）。 */
function DiffBody({ lines }: { lines: DiffLine[] }) {
  return (
    <div className="max-h-72 overflow-auto rounded-lg border border-border font-mono text-xs leading-relaxed">
      {lines.map((l, i) => (
        <div
          // biome-ignore lint/suspicious/noArrayIndexKey: stable positional diff rows
          key={i}
          className={`flex ${diffRowClass(l.type)}`}
        >
          <span className="w-5 shrink-0 select-none text-center text-muted-foreground/50">
            {diffSign(l.type)}
          </span>
          <span className="whitespace-pre-wrap break-words pr-2">
            {l.text || " "}
          </span>
        </div>
      ))}
    </div>
  );
}

/** 展开体：纯内容预览，无路径 / 模式标题。 */
function WriteBody({ content }: { content: string }) {
  const allLines = content.split("\n");
  const shown = allLines.slice(0, WRITE_PREVIEW_LINES);
  const hidden = allLines.length - shown.length;
  return (
    <div className="overflow-hidden rounded-lg border border-border">
      <div className="max-h-72 overflow-auto font-mono text-xs leading-relaxed">
        {shown.map((line, i) => (
          <div
            // biome-ignore lint/suspicious/noArrayIndexKey: stable positional preview
            key={i}
            className="flex"
          >
            <span className="w-8 shrink-0 select-none pr-2 text-right text-muted-foreground/40">
              {i + 1}
            </span>
            <span className="whitespace-pre-wrap break-words pr-2 text-foreground/90">
              {line || " "}
            </span>
          </div>
        ))}
      </div>
      {hidden > 0 && (
        <div className="border-border/60 border-t bg-muted/40 px-2.5 py-1 text-muted-foreground text-xs">
          … 还有 {hidden} 行（共 {allLines.length} 行）
        </div>
      )}
    </div>
  );
}

/** 展开体：删除/移动说明，不重复路径。 */
function MetaBody({ detail }: { detail: string }) {
  return (
    <div className="rounded-lg border border-border bg-muted/30 px-2.5 py-2 font-mono text-xs text-muted-foreground">
      {detail}
    </div>
  );
}

function FileChangeChrome({
  path,
  open,
  onToggle,
  trailing,
}: {
  path: string;
  open: boolean;
  onToggle: () => void;
  trailing: ReactNode;
}) {
  return (
    <Button
      variant="ghost"
      onClick={onToggle}
      className="h-auto w-full justify-start gap-1.5 rounded-lg px-1.5 py-1 hover:bg-accent/50"
    >
      <span className="flex w-full items-center gap-1.5 text-left text-xs">
        {open ? (
          <ChevronDown size={12} className="shrink-0 text-muted-foreground" />
        ) : (
          <ChevronRight size={12} className="shrink-0 text-muted-foreground" />
        )}
        <span className="min-w-0 truncate font-mono text-foreground" title={path}>
          {path}
        </span>
        <span className="ml-auto flex shrink-0 items-center gap-1.5 tabular-nums text-muted-foreground">
          {trailing}
        </span>
      </span>
    </Button>
  );
}

function EditTrailing({ adds, dels, label }: { adds: number; dels: number; label: string }) {
  return (
    <>
      <span>{label}</span>
      <span className="text-success">+{adds}</span>
      <span className="text-destructive">-{dels}</span>
    </>
  );
}

function ArtifactChangeRow({ artifact }: { artifact: FileArtifact }) {
  const [open, setOpen] = useState(false);
  const change = artifact.change;
  const editDiff = useMemo(() => {
    if (!change || change.kind !== "edit") return null;
    return summarizeLineDiff(change.oldText, change.newText);
  }, [change]);

  if (!change) {
    return (
      <div className="px-1 py-1 text-xs text-muted-foreground">
        <span className="font-mono text-foreground">{artifact.path}</span>
        <span className="mx-1.5">·</span>
        无参数侧预览（可打开工作区查看终态）
      </div>
    );
  }

  const label = previewKindLabel(change);
  let trailing: ReactNode = label;
  if (change.kind === "edit" && editDiff) {
    trailing = (
      <EditTrailing adds={editDiff.adds} dels={editDiff.dels} label={label} />
    );
  } else if (change.kind === "write") {
    const lines = change.content.split("\n").length;
    trailing = (
      <>
        <span>{writeModeLabel(change.mode)}</span>
        <span>{lines} 行</span>
      </>
    );
  }

  return (
    <div className="space-y-1.5">
      <FileChangeChrome
        path={artifact.path}
        open={open}
        onToggle={() => setOpen((v) => !v)}
        trailing={trailing}
      />
      {open && change.kind === "edit" && editDiff && (
        <DiffBody lines={editDiff.lines} />
      )}
      {open && change.kind === "write" && <WriteBody content={change.content} />}
      {open && change.kind === "delete" && <MetaBody detail="已删除" />}
      {open && change.kind === "move" && (
        <MetaBody
          detail={`移动：${change.fromPath || "?"} → ${artifact.path}`}
        />
      )}
    </div>
  );
}

function TrueDiffRow({ change }: { change: TurnFileChange }) {
  const [open, setOpen] = useState(false);
  const editDiff = useMemo(() => {
    if (
      change.changeType !== "modified" ||
      change.isBinary ||
      change.baseContent == null ||
      change.content == null
    ) {
      return null;
    }
    return summarizeLineDiff(change.baseContent, change.content);
  }, [change]);

  const label = turnChangeLabel(change.changeType);
  let trailing: ReactNode = label;
  if (editDiff) {
    trailing = (
      <EditTrailing adds={editDiff.adds} dels={editDiff.dels} label={label} />
    );
  } else if (
    change.changeType === "added" &&
    !change.isBinary &&
    change.content != null
  ) {
    const lines = change.content.split("\n").length;
    trailing = (
      <>
        <span>{label}</span>
        <span>{lines} 行</span>
      </>
    );
  }

  return (
    <div className="space-y-1.5">
      <FileChangeChrome
        path={change.path}
        open={open}
        onToggle={() => setOpen((v) => !v)}
        trailing={trailing}
      />
      {open && editDiff && <DiffBody lines={editDiff.lines} />}
      {open &&
        change.changeType === "added" &&
        !change.isBinary &&
        change.content != null && <WriteBody content={change.content} />}
      {open && change.changeType === "deleted" && (
        <MetaBody detail="已删除" />
      )}
      {open && change.isBinary && change.changeType !== "deleted" && (
        <div className="rounded-lg border border-border bg-muted/30 px-2.5 py-2 text-xs text-muted-foreground">
          二进制文件（{change.sizeBytes} 字节）— 请在工作区打开查看
        </div>
      )}
    </div>
  );
}

function ToolArgFallback({ artifacts }: { artifacts: FileArtifact[] }) {
  return (
    <>
      <p className="text-xs text-muted-foreground">
        改动已写入工作区。以下为工具参数侧预览（非云→本地「应用」）。
      </p>
      {artifacts.map((a) => (
        <ArtifactChangeRow key={`${a.op}:${a.path}`} artifact={a} />
      ))}
    </>
  );
}

export function TurnFileChangesReview({
  artifacts,
  conversationId = null,
  messageId = null,
  variant = "card",
}: {
  artifacts: FileArtifact[];
  conversationId?: string | null;
  /** Assistant message id（= turnKey）；有则尝试 A1+ 真 diff。 */
  messageId?: string | null;
  /** `card` = 产物卡内嵌（顶部分隔）；`panel` = 右坞「改动」tab 段落内。 */
  variant?: "card" | "panel";
}) {
  const ws = useConversationWorkspace(conversationId);
  const isLocal = ws?.location === "local" && !!ws.rootId;
  const [phase, setPhase] = useState<"loading" | "true" | "fallback">(
    conversationId && messageId ? "loading" : "fallback",
  );
  const [trueChanges, setTrueChanges] = useState<TurnFileChange[] | null>(null);
  const [baselineSnapshotId, setBaselineSnapshotId] = useState<string | null>(
    null,
  );
  const [counts, setCounts] = useState<{
    added: number;
    modified: number;
    deleted: number;
  } | null>(null);
  const [restoring, setRestoring] = useState(false);
  const [reloadToken, setReloadToken] = useState(0);

  // biome-ignore lint/correctness/useExhaustiveDependencies: reloadToken is an intentional re-run key after rollback
  useEffect(() => {
    if (!conversationId || !messageId) {
      setPhase("fallback");
      return;
    }
    let cancelled = false;
    setPhase("loading");
    const load = isLocal
      ? getLocalTurnFilesDiff(
          { rootId: ws.rootId as string, subpath: ws.subpath ?? "" },
          messageId,
        )
      : getTurnFilesDiff(conversationId, messageId);
    void load
      .then((diff) => {
        if (cancelled) return;
        if (diff.available) {
          setTrueChanges(diff.changes);
          setBaselineSnapshotId(diff.baselineSnapshotId);
          setCounts({
            added: diff.added,
            modified: diff.modified,
            deleted: diff.deleted,
          });
          setPhase("true");
        } else {
          setBaselineSnapshotId(null);
          setPhase("fallback");
        }
      })
      .catch(() => {
        if (!cancelled) {
          setBaselineSnapshotId(null);
          setPhase("fallback");
        }
      });
    return () => {
      cancelled = true;
    };
  }, [
    conversationId,
    messageId,
    reloadToken,
    isLocal,
    ws?.rootId,
    ws?.subpath,
  ]);

  const onRollback = async () => {
    if (!conversationId || !baselineSnapshotId || restoring) return;
    const confirmMsg = isLocal
      ? "回退到本回合开始会覆盖当前本机工作区的所有文件（恢复到本回合开始时的快照），确定继续？"
      : "回退到本回合开始会覆盖当前工作区的所有文件（恢复到本回合开始时的快照），确定继续？";
    if (!window.confirm(confirmMsg)) {
      return;
    }
    setRestoring(true);
    try {
      if (isLocal && ws?.rootId) {
        await restoreLocalTurnBaseline(
          { rootId: ws.rootId, subpath: ws.subpath ?? "" },
          baselineSnapshotId,
        );
      } else {
        await restoreSnapshot(conversationId, baselineSnapshotId);
      }
      notifySuccess("已回退到本回合开始");
      setReloadToken((n) => n + 1);
    } catch (e) {
      notifyActionError("回退失败", e);
    } finally {
      setRestoring(false);
    }
  };

  if (artifacts.length === 0 && phase !== "true" && phase !== "loading") {
    if (variant === "panel") {
      return (
        <div className="px-3 py-2.5 text-xs text-muted-foreground">
          暂无工具参数侧预览；若本回合有工作区基线，上方会显示相对基线的改动。
        </div>
      );
    }
    return null;
  }

  return (
    <div
      className={
        variant === "panel"
          ? "space-y-3 px-3 py-2.5"
          : "space-y-3 border-t border-border bg-muted/20 px-3 py-2.5"
      }
    >
      {phase === "loading" && (
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <Loader2 size={13} className="animate-spin" />
          正在读取相对基线的改动…
        </div>
      )}
      {phase === "true" && trueChanges && (
        <>
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
            <p className="min-w-0 flex-1 text-xs text-muted-foreground">
              {isLocal
                ? "相对本回合开始时的本机工作区基线（只读；相对「此刻」树）。"
                : "相对本回合开始时的工作区基线（只读；相对「此刻」树，非云→本地应用）。"}
              {counts && (
                <span className="ml-2 tabular-nums">
                  <span className="text-success">+{counts.added}</span>
                  <span className="mx-1 text-primary">~{counts.modified}</span>
                  <span className="text-destructive">-{counts.deleted}</span>
                </span>
              )}
            </p>
            {baselineSnapshotId && conversationId && (
              <Button
                variant="ghost"
                size="sm"
                disabled={restoring}
                onClick={() => void onRollback()}
                aria-label="回退到本回合开始"
                className="h-7 shrink-0 gap-1.5 px-2 text-xs text-muted-foreground hover:text-foreground"
              >
                {restoring ? (
                  <Loader2 size={13} className="animate-spin" />
                ) : (
                  <RotateCcw size={13} />
                )}
                回退到本回合开始
              </Button>
            )}
          </div>
          {trueChanges.length === 0 ? (
            <p className="text-xs text-muted-foreground">
              相对基线无文件差异。
            </p>
          ) : (
            trueChanges.map((c) => (
              <TrueDiffRow key={`${c.changeType}:${c.path}`} change={c} />
            ))
          )}
        </>
      )}
      {phase === "fallback" && <ToolArgFallback artifacts={artifacts} />}
    </div>
  );
}
