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
import {
  ChevronDown,
  ChevronRight,
  FileCode2,
  FileText,
  Loader2,
  RotateCcw,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";

/**
 * A1 / A1+ 只读「查看改动」——挂在产物卡内。
 * 优先拉回合基线真 diff（A1+）；无基线 / 失败则降级工具参数预览（A1）。
 * 不做 apply / 三方冲突（与交接「查看并应用」刻意区分）。
 */

const WRITE_PREVIEW_LINES = 300;

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

function EditBlock({
  path,
  oldText,
  newText,
}: {
  path: string;
  oldText: string;
  newText: string;
}) {
  const lines = useMemo(() => lineDiff(oldText, newText), [oldText, newText]);
  const adds = lines.reduce((n, l) => (l.type === "add" ? n + 1 : n), 0);
  const dels = lines.reduce((n, l) => (l.type === "del" ? n + 1 : n), 0);
  return (
    <div className="overflow-hidden rounded-lg border border-border">
      <div className="flex items-center gap-2 border-border/60 border-b bg-muted/40 px-2.5 py-1 text-xs">
        <FileCode2 size={12} className="shrink-0 text-muted-foreground" />
        <span className="truncate font-mono text-foreground">{path}</span>
        <span className="ml-auto flex shrink-0 items-center gap-1.5 tabular-nums">
          <span className="text-success">+{adds}</span>
          <span className="text-destructive">-{dels}</span>
        </span>
      </div>
      <div className="max-h-72 overflow-auto font-mono text-xs leading-relaxed">
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
    </div>
  );
}

function WriteBlock({
  path,
  content,
  mode,
}: {
  path: string;
  content: string;
  mode: "overwrite" | "append" | "added";
}) {
  const allLines = content.split("\n");
  const shown = allLines.slice(0, WRITE_PREVIEW_LINES);
  const hidden = allLines.length - shown.length;
  const modeLabel =
    mode === "append" ? "追加" : mode === "added" ? "新增" : "写入";
  return (
    <div className="overflow-hidden rounded-lg border border-border">
      <div className="flex items-center gap-2 border-border/60 border-b bg-muted/40 px-2.5 py-1 text-xs">
        <FileText size={12} className="shrink-0 text-muted-foreground" />
        <span className="truncate font-mono text-foreground">{path}</span>
        <span className="ml-auto shrink-0 tabular-nums text-muted-foreground">
          {modeLabel} · {allLines.length} 行
        </span>
      </div>
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

function MetaBlock({
  path,
  change,
}: {
  path: string;
  change: Extract<FileChangePreview, { kind: "delete" | "move" }>;
}) {
  const detail =
    change.kind === "delete"
      ? "已删除"
      : `移动：${change.fromPath || "?"} → ${path}`;
  return (
    <div className="rounded-lg border border-border bg-muted/30 px-2.5 py-2 font-mono text-xs text-muted-foreground">
      <span className="text-foreground">{path}</span>
      <span className="mx-1.5">·</span>
      {detail}
    </div>
  );
}

function ArtifactChangeRow({ artifact }: { artifact: FileArtifact }) {
  const [open, setOpen] = useState(true);
  const change = artifact.change;
  if (!change) {
    return (
      <div className="px-1 py-1 text-xs text-muted-foreground">
        <span className="font-mono text-foreground">{artifact.path}</span>
        <span className="mx-1.5">·</span>
        无参数侧预览（可打开工作区查看终态）
      </div>
    );
  }
  return (
    <div className="space-y-1.5">
      <Button
        variant="ghost"
        onClick={() => setOpen((v) => !v)}
        className="h-auto w-full justify-start gap-1.5 rounded-lg px-1.5 py-1 hover:bg-accent/50"
      >
        <span className="flex w-full items-center gap-1.5 text-left text-xs">
          {open ? (
            <ChevronDown size={12} className="shrink-0 text-muted-foreground" />
          ) : (
            <ChevronRight
              size={12}
              className="shrink-0 text-muted-foreground"
            />
          )}
          <span className="truncate font-mono text-foreground">
            {artifact.path}
          </span>
        </span>
      </Button>
      {open && change.kind === "edit" && (
        <EditBlock
          path={artifact.path}
          oldText={change.oldText}
          newText={change.newText}
        />
      )}
      {open && change.kind === "write" && (
        <WriteBlock
          path={artifact.path}
          content={change.content}
          mode={change.mode}
        />
      )}
      {open && (change.kind === "delete" || change.kind === "move") && (
        <MetaBlock path={artifact.path} change={change} />
      )}
    </div>
  );
}

function TrueDiffRow({ change }: { change: TurnFileChange }) {
  const [open, setOpen] = useState(true);
  return (
    <div className="space-y-1.5">
      <Button
        variant="ghost"
        onClick={() => setOpen((v) => !v)}
        className="h-auto w-full justify-start gap-1.5 rounded-lg px-1.5 py-1 hover:bg-accent/50"
      >
        <span className="flex w-full items-center gap-1.5 text-left text-xs">
          {open ? (
            <ChevronDown size={12} className="shrink-0 text-muted-foreground" />
          ) : (
            <ChevronRight
              size={12}
              className="shrink-0 text-muted-foreground"
            />
          )}
          <span className="truncate font-mono text-foreground">
            {change.path}
          </span>
          <span className="ml-auto shrink-0 text-muted-foreground">
            {change.changeType === "added"
              ? "新增"
              : change.changeType === "deleted"
                ? "删除"
                : "修改"}
          </span>
        </span>
      </Button>
      {open &&
        change.changeType === "modified" &&
        !change.isBinary &&
        change.baseContent != null &&
        change.content != null && (
          <EditBlock
            path={change.path}
            oldText={change.baseContent}
            newText={change.content}
          />
        )}
      {open &&
        change.changeType === "added" &&
        !change.isBinary &&
        change.content != null && (
          <WriteBlock
            path={change.path}
            content={change.content}
            mode="added"
          />
        )}
      {open && change.changeType === "deleted" && (
        <MetaBlock path={change.path} change={{ kind: "delete" }} />
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
}: {
  artifacts: FileArtifact[];
  conversationId?: string | null;
  /** Assistant message id（= turnKey）；有则尝试 A1+ 真 diff。 */
  messageId?: string | null;
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

  if (artifacts.length === 0 && phase !== "true") return null;

  return (
    <div className="space-y-3 border-t border-border bg-muted/20 px-3 py-2.5">
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
