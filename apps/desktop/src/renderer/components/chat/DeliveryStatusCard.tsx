import { Button } from "@/components/ui";
import {
  type StatusTone,
  statusAccentText,
  statusPillSoft,
} from "@/components/ui/tone-presets";
import {
  formatBindLocalFolderAnswer,
  pickAndBindLocalFolder,
} from "@/lib/bindLocalFolder";
import { sendTurn } from "@/services/turns";
import { useComposerDraftStore } from "@/stores/composer";
import { useConversationStore } from "@/stores/conversation";
import { usePersistentDisclosure } from "@/stores/disclosure";
import { useSidePanelStore } from "@/stores/sidePanel";
import type {
  DeliveryAction,
  DeliveryGap,
  DeliveryStatusPayload,
} from "@/types/events";
import {
  AlertTriangle,
  ChevronDown,
  ChevronUp,
  ClipboardCheck,
  FileText,
  FolderOpen,
  Info,
  PackageOpen,
  PlayCircle,
} from "lucide-react";
import { type ReactNode, useMemo, useState } from "react";

/** Known cutoff / shortfall reason codes on ``DeliveryGap.reason`` (forward-compatible). */
const GAP_REASON_LABEL: Record<string, string> = {
  token_budget: "预算触顶",
  turn_token_budget: "回合额度触顶",
  worker_timeout: "运行超时",
  degraded_handoff: "降级交接",
  qa_deferred_budget: "验收推迟",
  unverified_note: "待核实",
  files_not_landed: "未落盘",
};

/**
 * 「交付验收」卡（批次验收 / completion_criteria）—— 渲染 `delivery_status` 的结构化对账：
 * 交付缺口 + 待用户操作（如绑定本地文件夹 / 续派整页验收 / 续跑跳过节点）。与 finish_guard 的
 * 「引用/格式核验后已重写」chip 是两回事——本卡表示批次交付验收未过；跑完生命周期仍由 StatusStrip /
 * 节点绿勾表达。挂在答复正文下方、「本回合产出文件」卡上方。
 *
 * C3 职责分离：结构化 gaps 是缺口唯一可信源，本卡是缺口的唯一披露面——综述正文不承担
 * 缺口披露，避免「正文乐观、卡片悲观」割裂。partial / blocked 的强调色由卡片头部
 * （图标 + 状态徽标）承接；仅 soft 待核实 → state=notes 轻提醒（非「部分未满足」）。
 *
 * `state=delivered`（有产物、无缺口）不渲染——已交付清单由 FileArtifactsCard 承载，
 * 本卡只在有诚实缺口或待核实提醒要交代（partial / blocked / notes）时出现。
 * `actions` 里已知的 `bind_local_folder` / `website_verify` / `continue_skipped_runs`
 * 渲染为真按钮；未知 kind 按普通提示行渲染（契约向前兼容）。
 * 成篇未写完改由对话框接着说——已撤 `continue_writing` 一键按钮。
 * 「团队可能重派」仅在 actions 含上述可续派 kind 时显示。
 */

/** Action kinds that mean the user/team can continue or redispatch this batch. */
const REDISPATCH_ACTION_KINDS = new Set([
  "bind_local_folder",
  "website_verify",
  "continue_skipped_runs",
]);

/** True when payload actions express a continue / redispatch path. */
export function mayShowRedispatchHint(status: DeliveryStatusPayload): boolean {
  return (status.actions ?? []).some((a) =>
    REDISPATCH_ACTION_KINDS.has(a.kind),
  );
}

function isWarningGap(gap: DeliveryGap): boolean {
  return gap.severity === "warning";
}

const STATE_META: Record<
  "partial" | "blocked" | "notes",
  { label: string; tone: StatusTone }
> = {
  partial: { label: "部分未满足", tone: "primary" },
  blocked: { label: "未满足", tone: "destructive" },
  notes: { label: "有备注", tone: "muted" },
};

function BindActionRow({
  action,
  conversationId,
}: {
  action: DeliveryAction;
  conversationId: string | null;
}) {
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const [bound, setBound] = useState(false);
  const isGenerating = useConversationStore((s) =>
    conversationId ? Boolean(s.byId[conversationId]?.isGenerating) : false,
  );

  const onBind = async () => {
    if (!conversationId || busy || bound || isGenerating) return;
    setBusy(true);
    setNote(null);
    const result = await pickAndBindLocalFolder(conversationId);
    if (!result.ok) {
      setBusy(false);
      if (result.reason === "error") setNote(result.message);
      else if (result.reason === "unavailable")
        setNote("绑定本地文件夹仅桌面端可用");
      // cancelled → 静默（用户主动关掉选择器）。
      return;
    }
    setBound(true);
    const content = `${formatBindLocalFolderAnswer("已绑定本地文件夹", result.root.name)}，请在本机继续完成未交付项。`;
    const userMsgId = crypto.randomUUID();
    try {
      useConversationStore.getState().addMessage(
        {
          id: userMsgId,
          role: "user",
          content,
          createdAt: new Date().toISOString(),
          executionId: null,
          isStreaming: false,
        },
        conversationId,
      );
      useComposerDraftStore.getState().setValue(conversationId, "");
      await sendTurn({
        conversationId,
        content,
        attachments: [],
        optimisticUserId: userMsgId,
      });
      setNote(`已绑定「${result.root.name}」为本机工作目录，正在让团队继续。`);
    } catch {
      setNote(
        `已绑定「${result.root.name}」为本机工作目录；自动续跑失败，可在输入框手动告诉团队继续。`,
      );
    } finally {
      setBusy(false);
    }
  };

  return (
    <li className="flex flex-col gap-1.5 px-3 py-2.5">
      <div className="flex items-start gap-2">
        <FolderOpen
          size={14}
          className={`mt-0.5 shrink-0 ${statusAccentText.primary}`}
        />
        <p className="min-w-0 flex-1 text-sm text-foreground">
          {action.description}
        </p>
        {conversationId && !bound && (
          <Button
            variant="primary"
            size="sm"
            className="shrink-0"
            disabled={busy || isGenerating}
            onClick={() => void onBind()}
          >
            {busy ? "选择文件夹…" : "绑定本地文件夹"}
          </Button>
        )}
      </div>
      {note && (
        <p
          className={`pl-6 text-xs ${bound ? statusAccentText.success : "text-muted-foreground"}`}
        >
          {note}
        </p>
      )}
    </li>
  );
}

/** Prompt-backed delivery CTAs (`website_verify` / `continue_skipped_runs`):
 *  one-click `sendTurn` with the action's `prompt`. */
const PROMPT_ACTION_UI: Record<
  string,
  {
    buttonLabel: string;
    sentNote: string;
    icon: ReactNode;
  }
> = {
  website_verify: {
    buttonLabel: "续派页面验收",
    sentNote: "已发出续派验收请求",
    icon: (
      <ClipboardCheck
        size={14}
        className={`mt-0.5 shrink-0 ${statusAccentText.primary}`}
      />
    ),
  },
  continue_skipped_runs: {
    buttonLabel: "续跑未执行节点",
    sentNote: "已发出续跑请求",
    icon: (
      <PlayCircle
        size={14}
        className={`mt-0.5 shrink-0 ${statusAccentText.primary}`}
      />
    ),
  },
};

function PromptSendActionRow({
  action,
  conversationId,
}: {
  action: DeliveryAction;
  conversationId: string | null;
}) {
  // Caller only mounts for known prompt kinds (`action.kind in PROMPT_ACTION_UI`).
  const ui = PROMPT_ACTION_UI[action.kind];
  const [busy, setBusy] = useState(false);
  const [sent, setSent] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const isGenerating = useConversationStore((s) =>
    conversationId ? Boolean(s.byId[conversationId]?.isGenerating) : false,
  );
  const prompt = (action.prompt ?? "").trim() || action.description;
  if (!ui) return null;

  const onSend = async () => {
    if (!conversationId || busy || sent || !prompt || isGenerating) return;
    setBusy(true);
    setNote(null);
    const userMsgId = crypto.randomUUID();
    try {
      useConversationStore.getState().addMessage(
        {
          id: userMsgId,
          role: "user",
          content: prompt,
          createdAt: new Date().toISOString(),
          executionId: null,
          isStreaming: false,
        },
        conversationId,
      );
      useComposerDraftStore.getState().setValue(conversationId, "");
      await sendTurn({
        conversationId,
        content: prompt,
        attachments: [],
        optimisticUserId: userMsgId,
      });
      setSent(true);
      setNote(ui.sentNote);
    } catch {
      setNote("发送失败，请重试或手动粘贴提示到输入框");
    } finally {
      setBusy(false);
    }
  };

  return (
    <li className="flex flex-col gap-1.5 px-3 py-2.5">
      <div className="flex items-start gap-2">
        {ui.icon}
        <p className="min-w-0 flex-1 text-sm text-foreground">
          {action.description}
        </p>
        {conversationId && !sent && (
          <Button
            variant="primary"
            size="sm"
            className="shrink-0"
            disabled={busy || isGenerating}
            onClick={() => void onSend()}
          >
            {busy ? "发送中…" : ui.buttonLabel}
          </Button>
        )}
      </div>
      {note && (
        <p
          className={`pl-6 text-xs ${sent ? statusAccentText.success : "text-muted-foreground"}`}
        >
          {note}
        </p>
      )}
    </li>
  );
}

function collectWarningPaths(warnings: DeliveryGap[]): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const gap of warnings) {
    for (const path of gap.paths ?? []) {
      if (path && !seen.has(path)) {
        seen.add(path);
        out.push(path);
      }
    }
  }
  return out;
}

function warningHitCount(warnings: DeliveryGap[]): number {
  let total = 0;
  for (const gap of warnings) {
    const m = gap.description.match(/（(\d+)\s*处）/);
    if (m) total += Number(m[1]) || 1;
    else total += 1;
  }
  return total;
}

function SoftNotesRow({
  warnings,
  tone,
}: {
  warnings: DeliveryGap[];
  tone: StatusTone;
}) {
  const [open, setOpen] = useState(false);
  const showFile = useSidePanelStore((s) => s.showFile);
  const paths = useMemo(() => collectWarningPaths(warnings), [warnings]);
  const hits = warningHitCount(warnings);
  const fileLabel = paths.length > 0 ? `（${paths.length} 个文件）` : "";
  const summary = `有 ${hits} 处待核实备注${fileLabel}`;

  const onOpenFiles = () => {
    for (const path of paths) {
      const name = path.replace(/\\/g, "/").split("/").pop() || path;
      showFile(path, name);
    }
  };

  return (
    <li className="flex flex-col gap-1 px-3 py-2.5">
      <div className="flex items-start gap-2">
        <Info
          size={14}
          className={`mt-0.5 shrink-0 ${statusAccentText[tone]}`}
        />
        <button
          type="button"
          className="min-w-0 flex-1 text-left text-sm text-foreground"
          onClick={() => setOpen((v) => !v)}
        >
          <span>{summary}</span>
          <span className="ml-1 text-xs text-muted-foreground">
            {open ? "收起" : "展开"}
          </span>
        </button>
        {paths.length > 0 && (
          <Button
            variant="neutral"
            size="sm"
            className="shrink-0"
            onClick={onOpenFiles}
          >
            <FileText size={14} className="mr-1" />
            打开相关文件
          </Button>
        )}
      </div>
      {open && (
        <ul className="space-y-1.5 pl-6">
          {warnings.map((gap, i) => (
            <li
              key={`${gap.role}:warn:${i}`}
              className="text-xs text-muted-foreground"
            >
              <span className="text-foreground/80">{gap.role}：</span>
              {gap.description}
            </li>
          ))}
        </ul>
      )}
    </li>
  );
}

export function DeliveryStatusCard({
  status,
  conversationId = null,
  turnKey,
}: {
  status: DeliveryStatusPayload;
  conversationId?: string | null;
  /** 回合作用域（= messageId）：给了才把整卡开合按回合持久化（对齐产出文件卡）。 */
  turnKey?: string;
}) {
  // 诚实披露卡：默认展开（不套产物卡「>4 收起」阈值），收起仅折叠 gap 明细与 actions，
  // 头部（图标 + 交付验收 + 状态徽标 + summary + 条件性「团队可能重派」）恒可见。
  // 恒在早退前调用以稳定 hook 顺序（state 可能在 partial/blocked/delivered/notes 间切换）。
  const [expanded, setExpanded] = usePersistentDisclosure(
    turnKey ? `${turnKey}:delivery` : null,
    true,
  );
  // 已交付且无缺口：清单由「本回合产出文件」卡承载，本卡不重复出现。
  if (status.state === "delivered") return null;
  const meta = STATE_META[status.state];
  const gaps = status.gaps ?? [];
  // 已撤 continue_writing：旧 journal / 旧载荷里若仍带该 action，一律不渲染，避免与
  // 「请在对话框接着写」提示重复。
  const actions = (status.actions ?? []).filter(
    (a) => a.kind !== "continue_writing",
  );
  const showRedispatchHint = mayShowRedispatchHint({
    ...status,
    actions,
  });
  const blockingGaps = gaps.filter((g) => !isWarningGap(g));
  const warningGaps = gaps.filter(isWarningGap);
  // 成篇未写完：引导在对话框接着说（无一键按钮）。
  const writingIncomplete =
    status.state === "partial" &&
    blockingGaps.some(
      (g) => g.reason === "token_budget" || g.reason === "worker_timeout",
    );

  return (
    <div
      className="mt-3 overflow-hidden rounded-xl border border-border bg-card"
      data-testid="delivery-status-bound"
    >
      <Button
        variant="ghost"
        onClick={() => setExpanded((v) => !v)}
        className="h-auto w-full justify-start gap-2 rounded-none px-3 py-2.5 hover:bg-accent/50"
      >
        <span className="flex w-full items-center gap-2 text-left">
          <PackageOpen
            size={15}
            className={`shrink-0 ${statusAccentText[meta.tone]}`}
          />
          <span className="shrink-0 text-sm font-medium text-foreground">
            交付验收
          </span>
          <span
            className={`shrink-0 rounded-full px-1.5 py-0.5 text-xs leading-none ${statusPillSoft[meta.tone]}`}
          >
            {meta.label}
          </span>
          <span className="min-w-0 flex-1 truncate text-xs text-muted-foreground">
            {status.summary}
          </span>
          {showRedispatchHint && (
            <span className="shrink-0 text-xs text-muted-foreground">
              团队可能重派
            </span>
          )}
          {expanded ? (
            <ChevronUp size={15} className="shrink-0 text-muted-foreground" />
          ) : (
            <ChevronDown size={15} className="shrink-0 text-muted-foreground" />
          )}
        </span>
      </Button>
      {expanded && (blockingGaps.length > 0 || warningGaps.length > 0) && (
        <ul className="border-t border-border">
          {blockingGaps.map((gap, i) => {
            const reasonLabel =
              gap.reason && GAP_REASON_LABEL[gap.reason]
                ? GAP_REASON_LABEL[gap.reason]
                : null;
            return (
              // 无行间横线（统一两卡列表语言）；gap 描述可多行，py-2.5 保换行行与相邻行不糊。
              <li
                key={`${gap.role}:${i}`}
                className="flex items-start gap-2 px-3 py-2.5"
              >
                <AlertTriangle
                  size={14}
                  className={`mt-0.5 shrink-0 ${statusAccentText[meta.tone]}`}
                />
                <p className="min-w-0 flex-1 text-sm text-foreground">
                  <span className="text-muted-foreground">{gap.role}：</span>
                  {reasonLabel && (
                    <span
                      className={`mr-1.5 inline-block shrink-0 rounded-full px-1.5 py-0.5 text-xs leading-none ${statusPillSoft[meta.tone]}`}
                    >
                      {reasonLabel}
                    </span>
                  )}
                  {gap.description}
                </p>
              </li>
            );
          })}
          {warningGaps.length > 0 && (
            <SoftNotesRow warnings={warningGaps} tone={meta.tone} />
          )}
          {writingIncomplete && (
            <li className="flex items-start gap-2 px-3 py-2.5">
              <Info
                size={14}
                className={`mt-0.5 shrink-0 ${statusAccentText.primary}`}
              />
              <p className="min-w-0 flex-1 text-sm text-muted-foreground">
                成篇未写完——请在对话框告诉我接着写（从已完成章节继续；勿删稿重写整篇）
              </p>
            </li>
          )}
        </ul>
      )}
      {expanded && actions.length > 0 && (
        <ul className="border-t border-border bg-muted/30">
          {actions.map((action, i) =>
            action.kind === "bind_local_folder" ? (
              <BindActionRow
                key={`${action.kind}:${i}`}
                action={action}
                conversationId={conversationId}
              />
            ) : action.kind in PROMPT_ACTION_UI ? (
              <PromptSendActionRow
                key={`${action.kind}:${i}`}
                action={action}
                conversationId={conversationId}
              />
            ) : (
              <li
                key={`${action.kind}:${i}`}
                className="flex items-start gap-2 px-3 py-2.5"
              >
                <FolderOpen
                  size={14}
                  className={`mt-0.5 shrink-0 ${statusAccentText.primary}`}
                />
                <p className="min-w-0 flex-1 text-sm text-foreground">
                  {action.description}
                </p>
              </li>
            ),
          )}
        </ul>
      )}
    </div>
  );
}
