import { MANUAL_HELP, ManualHelpLink } from "@/components/ManualHelpLink";
import { CodeBlock } from "@/components/chat/CodeBlock";
import {
  OrphanedInteractionCard,
  WaitingForDecisionHint,
} from "@/components/chat/OrphanedInteractionCard";
import {
  codeExecuteLanguage,
  deriveCodeExecuteRiskTags,
  fencedCodeMarkdown,
  isPreviewTruncated,
} from "@/components/chat/codeExecuteApproval";
import { Badge, Button, DecisionCard, DecisionCardIcon } from "@/components/ui";
import { SimpleTooltip } from "@/components/ui/tooltip";
import {
  getConversations,
  patchConversationCache,
} from "@/hooks/useConversations";
import { notifyError } from "@/lib/toast";
import { cn } from "@/lib/utils";
import {
  decideApproval,
  isExecutionTool,
  isFileOpTool,
  supportsTurnGrant,
} from "@/services/approvals";
import {
  type PermissionAxes,
  matchRecipe,
  recipeToAxes,
  setConversationPermissionAxes,
} from "@/services/permissionAxes";
import { useConversationStore } from "@/stores/conversation";
import {
  type ApprovalView,
  isToolGranted,
  useInteractionStore,
  useOrphanedApprovals,
  usePendingApprovals,
} from "@/stores/interactions";
import { usePermissionChangeStore } from "@/stores/permissionChanges";
import type { ApprovalDecision } from "@/types/events";
import {
  Check,
  CheckCheck,
  ChevronDown,
  ChevronRight,
  FileCheck,
  Loader2,
  ShieldAlert,
  X,
} from "lucide-react";
import { type ComponentPropsWithoutRef, useMemo, useState } from "react";
import ReactMarkdown from "react-markdown";
import rehypeHighlight from "rehype-highlight";

const TOOL_LABELS: Record<string, string> = {
  file_write: "写入文件",
  file_append: "追加文件",
  str_replace: "修改文件",
  file_delete: "删除文件",
  file_move: "移动文件",
  file_copy: "复制文件",
  mkdir: "创建目录",
  file_batch: "批量文件操作",
  code_execute: "执行代码",
  test_run: "运行测试",
  terminal: "终端",
  desktop_notify: "系统通知",
};

const HIGHLIGHT_PLUGINS: ComponentPropsWithoutRef<
  typeof ReactMarkdown
>["rehypePlugins"] = [[rehypeHighlight, { ignoreMissing: true }]];

/** Consecutive same-tool approval prompts before nudging full_trust. */
const FULL_TRUST_HINT_AFTER = 3;

function toolLabel(name: string): string {
  return TOOL_LABELS[name] ?? name;
}

function batchOpLine(item: Record<string, unknown>): string {
  const op = String(item.op ?? "").trim();
  if (op === "move")
    return `move ${item.source ?? ""} → ${item.destination ?? ""}`;
  if (op === "copy")
    return `copy ${item.source ?? ""} → ${item.destination ?? ""}`;
  if (op === "delete") {
    const perm = item.permanent ? " (永久)" : "";
    return `delete ${item.path ?? ""}${perm}`;
  }
  if (op === "mkdir") return `mkdir ${item.path ?? ""}`;
  return JSON.stringify(item);
}

function primaryArg(
  toolName: string,
  args: Record<string, unknown>,
): string | null {
  if (toolName === "file_batch") {
    const ops = args.operations;
    if (Array.isArray(ops)) return `本次共 ${ops.length} 项`;
  }
  if (toolName === "code_execute") {
    const purpose = args.purpose;
    if (typeof purpose === "string" && purpose.trim()) return purpose.trim();
  }
  if (toolName === "terminal") {
    const cmd = args.command;
    if (typeof cmd === "string" && cmd.trim()) return cmd.trim();
  }
  for (const key of [
    "path",
    "file_path",
    "source",
    "destination",
    "command",
    "code",
    "title",
    "body",
  ]) {
    const value = args[key];
    if (typeof value === "string" && value.trim()) return value.trim();
  }
  return null;
}

/** Count approval cards (any status except orphaned) for a tool this conversation. */
function countToolApprovals(conversationId: string, toolName: string): number {
  let n = 0;
  for (const e of useInteractionStore.getState().byId.values()) {
    if (e.conversationId !== conversationId) continue;
    if (e.kind !== "approval") continue;
    if (e.status === "orphaned") continue;
    if (String(e.payload.tool_name ?? "") !== toolName) continue;
    n += 1;
  }
  return n;
}

/**
 * Pending tool-approval surface — composer-dock strip (Chat / 画布指挥台同实例).
 * Visually fuses with MessageInput when ``attached`` (Chat bottom bar).
 */
export function ApprovalPrompt({
  attached = false,
}: {
  /** True when stacked flush above the chat composer (同底栏一体). */
  attached?: boolean;
}) {
  const conversationId = useConversationStore((s) => s.currentConversationId);
  const pending = usePendingApprovals(conversationId);
  const orphaned = useOrphanedApprovals(conversationId);
  const visible = pending.filter(
    (p) => conversationId != null && !isToolGranted(conversationId, p.toolName),
  );
  if (visible.length === 0 && orphaned.length === 0) return null;

  return (
    <div
      className={cn("space-y-2", attached ? "px-0" : "mx-4 mb-2")}
      data-approval-dock={attached ? "composer" : "panel"}
    >
      {orphaned.map((o) => (
        <OrphanedInteractionCard
          key={o.id}
          title="审批已失效"
          detail="该工具放行请求已不可答复（服务已重启或回合已结束）。"
        />
      ))}
      {visible.map((approval) => (
        <ApprovalCard
          key={approval.approvalId}
          approval={approval}
          attached={attached}
        />
      ))}
    </div>
  );
}

/** 单张工具审批卡。可选 `onDecide` 供手册等纯演示覆盖默认提交路径。 */
export function ApprovalCard({
  approval,
  onDecide: onDecideProp,
  attached = false,
}: {
  approval: ApprovalView;
  onDecide?: (decision: ApprovalDecision) => void;
  attached?: boolean;
}) {
  const [expanded, setExpanded] = useState(false);
  const [clicked, setClicked] = useState<ApprovalDecision | null>(null);
  const [trustBusy, setTrustBusy] = useState(false);
  const [axesOverride, setAxesOverride] = useState<PermissionAxes | null>(null);
  const axes =
    axesOverride ??
    getConversations().find((c) => c.id === approval.conversationId)
      ?.permissionAxes;
  const recipe = axes ? matchRecipe(axes) : "custom";

  const isCodeExecute = approval.toolName === "code_execute";
  const isFileBatch = approval.toolName === "file_batch";
  const isExecution = isExecutionTool(approval.toolName);
  const preferTurnGrant = isExecution && supportsTurnGrant(approval.toolName);
  const headline = primaryArg(approval.toolName, approval.arguments);
  const argEntries = Object.entries(approval.arguments);
  const busy = approval.resolving;
  const isFileOp = isFileOpTool(approval.toolName);
  const circuitBreakerHint =
    typeof approval.arguments.circuit_breaker_hint === "string"
      ? approval.arguments.circuit_breaker_hint.trim()
      : "";

  const sameToolCount = useMemo(
    () => countToolApprovals(approval.conversationId, approval.toolName),
    [approval.conversationId, approval.toolName],
  );
  const showManagedHint =
    sameToolCount >= FULL_TRUST_HINT_AFTER &&
    recipe !== "managed" &&
    !circuitBreakerHint;

  const batchOps = useMemo(() => {
    if (!isFileBatch) return [];
    const ops = approval.arguments.operations;
    if (!Array.isArray(ops)) return [];
    return ops.filter(
      (item): item is Record<string, unknown> =>
        item != null && typeof item === "object" && !Array.isArray(item),
    );
  }, [approval.arguments.operations, isFileBatch]);

  const codeText =
    isCodeExecute && typeof approval.arguments.code === "string"
      ? approval.arguments.code
      : null;
  const riskTags = useMemo(
    () => (codeText ? deriveCodeExecuteRiskTags(codeText) : []),
    [codeText],
  );
  const codeTruncated = codeText != null && isPreviewTruncated(codeText);
  const otherArgs = useMemo(() => {
    if (!isCodeExecute) return approval.arguments;
    return Object.fromEntries(
      Object.entries(approval.arguments).filter(
        ([key]) =>
          key !== "code" && key !== "purpose" && key !== "circuit_breaker_hint",
      ),
    );
  }, [approval.arguments, isCodeExecute]);
  const displayArgs = useMemo(() => {
    if (isCodeExecute) return otherArgs;
    if (isFileBatch) {
      return Object.fromEntries(
        Object.entries(approval.arguments).filter(
          ([key]) => key !== "circuit_breaker_hint" && key !== "operations",
        ),
      );
    }
    return Object.fromEntries(
      Object.entries(approval.arguments).filter(
        ([key]) => key !== "circuit_breaker_hint",
      ),
    );
  }, [approval.arguments, isCodeExecute, isFileBatch, otherArgs]);

  const onDecide = (decision: ApprovalDecision) => {
    setClicked(decision);
    if (onDecideProp) {
      onDecideProp(decision);
      return;
    }
    void decideApproval(approval, decision).catch((err) => {
      notifyError(err, "操作失败");
    });
  };

  const switchManaged = () => {
    if (trustBusy || !approval.conversationId) return;
    if (
      !window.confirm(
        "切换到「托管」后，AI 将与你同权执行命令（含本地运行代码）。确定继续？",
      )
    ) {
      return;
    }
    setTrustBusy(true);
    const next = recipeToAxes("managed");
    void setConversationPermissionAxes(approval.conversationId, next)
      .then((saved) => {
        patchConversationCache(approval.conversationId, {
          permissionAxes: saved,
        });
        setAxesOverride(saved);
        // 与 PermissionAxesBadge 一致：同步审计后重拉，主流立即出现 A→B 行。
        void usePermissionChangeStore
          .getState()
          .load(approval.conversationId)
          .catch(() => {});
      })
      .catch((err) => notifyError(err, "切换失败"))
      .finally(() => setTrustBusy(false));
  };

  const spinnerOr = (decision: ApprovalDecision, icon: React.ReactNode) =>
    busy && clicked === decision ? (
      <Loader2 size={13} className="animate-spin" />
    ) : (
      icon
    );

  const onceButton = (
    <Button
      variant={preferTurnGrant ? "neutral" : "primary"}
      icon={spinnerOr("approve", <Check size={13} />)}
      disabled={busy}
      onClick={() => onDecide("approve")}
    >
      允许一次
    </Button>
  );
  const turnGrantButton = supportsTurnGrant(approval.toolName) ? (
    <Button
      variant={preferTurnGrant ? "primary" : "neutral"}
      icon={spinnerOr("approve_always", <CheckCheck size={13} />)}
      disabled={busy}
      onClick={() => onDecide("approve_always")}
    >
      本轮内都允许
    </Button>
  ) : null;

  return (
    <DecisionCard
      tone="primary"
      animate={!attached}
      className={cn(
        "mx-0",
        attached &&
          "mt-0 rounded-b-none rounded-t-xl border-b-0 shadow-none animate-none",
      )}
    >
      <div className="flex items-start gap-2">
        <DecisionCardIcon tone="primary">
          <ShieldAlert size={16} />
        </DecisionCardIcon>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1">
            <p className="min-w-0 flex-1 text-sm text-foreground">
              <span className="font-medium">Agent 请求执行</span>
              <span className="text-muted-foreground"> · </span>
              <span className="font-medium">
                {toolLabel(approval.toolName)}
              </span>
            </p>
            <ManualHelpLink to={MANUAL_HELP.autonomy} />
          </div>
          <WaitingForDecisionHint />
          {headline && (
            <SimpleTooltip label={headline}>
              <p
                className={`mt-0.5 truncate text-xs text-muted-foreground ${
                  isCodeExecute &&
                  typeof approval.arguments.purpose === "string" &&
                  approval.arguments.purpose.trim()
                    ? ""
                    : "font-mono"
                }`}
              >
                {headline}
              </p>
            </SimpleTooltip>
          )}
          {isFileBatch && batchOps.length > 0 && (
            <ol className="mt-1 max-h-40 list-decimal space-y-0.5 overflow-auto pl-4 font-mono text-xs text-muted-foreground">
              {batchOps.map((item, idx) => (
                <li key={`${idx}-${batchOpLine(item)}`} className="break-all">
                  {batchOpLine(item)}
                </li>
              ))}
            </ol>
          )}
          {isCodeExecute && riskTags.length > 0 && (
            <div className="mt-1 flex flex-wrap gap-1">
              {riskTags.map((tag) => (
                <Badge key={tag} tone="muted" className="font-normal">
                  {tag}
                </Badge>
              ))}
            </div>
          )}
          {circuitBreakerHint && (
            <p className="mt-1 text-xs text-muted-foreground">
              安全熔断升格审批（启发式兜底，并非完整拦截）：{circuitBreakerHint}
            </p>
          )}
          {showManagedHint && (
            <p className="mt-1 text-xs text-muted-foreground">
              同类审批较频繁。可切换为
              <button
                type="button"
                className="mx-0.5 text-primary underline-offset-2 hover:underline"
                disabled={trustBusy}
                onClick={switchManaged}
              >
                托管
              </button>
              （下一回合生效；熔断仍在）。
            </p>
          )}
          {argEntries.length > 0 && (
            <Button
              variant="ghost"
              onClick={() => setExpanded((v) => !v)}
              className="mt-1 h-auto gap-1 px-0 py-0 text-xs text-muted-foreground hover:text-foreground"
              icon={
                expanded ? (
                  <ChevronDown size={13} />
                ) : (
                  <ChevronRight size={13} />
                )
              }
            >
              {expanded ? "收起参数" : "查看参数"}
            </Button>
          )}
          {expanded && isCodeExecute && codeText != null && (
            <div className="mt-1 space-y-1">
              {codeTruncated && (
                <p className="text-xs text-muted-foreground">代码预览已截断</p>
              )}
              <ApprovalHighlightedCode
                code={codeText}
                language={codeExecuteLanguage(approval.arguments)}
              />
            </div>
          )}
          {expanded && isCodeExecute && Object.keys(otherArgs).length > 0 && (
            <pre className="mt-1 max-h-40 overflow-auto rounded-lg bg-card/70 p-2 font-mono text-xs text-foreground">
              {JSON.stringify(otherArgs, null, 2)}
            </pre>
          )}
          {expanded &&
            !isCodeExecute &&
            Object.keys(displayArgs).length > 0 && (
              <pre className="mt-1 max-h-40 overflow-auto rounded-lg bg-card/70 p-2 font-mono text-xs text-foreground">
                {JSON.stringify(displayArgs, null, 2)}
              </pre>
            )}
        </div>
      </div>

      <div className="mt-2.5 flex flex-wrap items-center gap-1.5 pl-6">
        {preferTurnGrant ? (
          <>
            {turnGrantButton}
            {onceButton}
          </>
        ) : (
          <>
            {onceButton}
            {turnGrantButton}
          </>
        )}
        {isFileOp && (
          <Button
            variant="neutral"
            icon={spinnerOr("approve_always_files", <FileCheck size={13} />)}
            disabled={busy}
            onClick={() => onDecide("approve_always_files")}
          >
            本轮内允许所有文件改动
          </Button>
        )}
        <Button
          variant="danger"
          icon={spinnerOr("deny", <X size={13} />)}
          disabled={busy}
          onClick={() => onDecide("deny")}
        >
          拒绝
        </Button>
      </div>
    </DecisionCard>
  );
}

function ApprovalHighlightedCode({
  code,
  language,
}: {
  code: string;
  language: string;
}) {
  const markdown = useMemo(
    () => fencedCodeMarkdown(code, language),
    [code, language],
  );
  return (
    <ReactMarkdown
      rehypePlugins={HIGHLIGHT_PLUGINS}
      components={{
        pre: CodeBlock,
        p: ({ children }) => <>{children}</>,
      }}
    >
      {markdown}
    </ReactMarkdown>
  );
}
