import { DeliveryStatusCard } from "@/components/chat/DeliveryStatusCard";
import { FileArtifactsCard } from "@/components/chat/FileArtifactsCard";
import { Markdown } from "@/components/chat/Markdown";
import { SourceCards } from "@/components/chat/SourceCards";
import { TurnWarningBanner } from "@/components/chat/TurnWarningBanner";
import { CollapsibleSpeech } from "@/components/chat/debate/CollapsibleSpeech";
import { Button, IconButton } from "@/components/ui";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { FinishReasonChip } from "@/components/ui/finish-reason-chip";
import { SimpleTooltip } from "@/components/ui/tooltip";
import { buildCitationDisplayMap } from "@/lib/citationDisplayMap";
import { copyText } from "@/lib/clipboard";
import {
  connectivityEscalationSuffix,
  degradedFinishChipLabel,
  errorActionForCode,
  formatAssistantErrorMessage,
  isConnectivityErrorCode,
  syntheticErrorForEmptyFailure,
} from "@/lib/errors";
import {
  fileArtifactsFromExecution,
  fileArtifactsFromProcess,
  mergeArtifacts,
} from "@/lib/fileArtifacts";
import {
  COST_UNPRICED_LABEL,
  formatCostCaption,
  pickCostMoney,
} from "@/lib/format";
import { formatMessageExport } from "@/lib/messageExport";
import { formatSupportDiagnosticText } from "@/lib/supportDiagnostics";
import { notifySuccess } from "@/lib/toast";
import { runRegenerate } from "@/services/turns";
import {
  assistantProjectionId,
  getActiveRuntime,
  useActiveGenerating,
  useConversationStore,
} from "@/stores/conversation";
import { useExecutionStore, useMessageExecution } from "@/stores/execution";
import { useMessageInteractionCards } from "@/stores/interactions";
import { useUsageStore } from "@/stores/usage";
import type { ProcessStep } from "@/types/events";
import { AlertTriangle, Check, Copy, KeyRound, RefreshCw } from "lucide-react";
import { useMemo, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { AssistantMessageFooter } from "./AssistantMessageFooter";
import { ComposingToolLine, ProcessTimeline } from "./ProcessTimeline";
import { SyncStatusHint } from "./SyncStatusHint";
import { ThinkingDots, ThinkingPanel } from "./Thinking";
import type { MessageBubbleProps } from "./types";
import { useCopyAction } from "./useCopyAction";

function MultiAgentFileArtifacts({
  messageId,
  process,
}: {
  messageId: string;
  process: ProcessStep[] | undefined;
}) {
  const execution = useMessageExecution(messageId);
  const conversationId = useConversationStore((s) => s.currentConversationId);
  // 交付状态（能力闸门与交付诚实性）：delegate 收尾的结构化交付对账（同 execution_id
  // 保最新）。缺口/待操作卡渲染在产出文件卡上方——诚实缺口先于清单。
  const deliveryStatus = useExecutionStore(
    (s) => s.byId[messageId]?.deliveryStatus ?? null,
  );
  const artifacts = useMemo(
    () =>
      mergeArtifacts(
        fileArtifactsFromProcess(process),
        fileArtifactsFromExecution(execution),
      ),
    [process, execution],
  );
  return (
    <>
      {deliveryStatus && (
        <DeliveryStatusCard
          status={deliveryStatus}
          conversationId={conversationId}
          turnKey={messageId}
        />
      )}
      <FileArtifactsCard
        artifacts={artifacts}
        conversationId={conversationId}
        turnKey={messageId}
      />
    </>
  );
}

export function AssistantMessage({ message }: MessageBubbleProps) {
  const isGenerating = useActiveGenerating();
  const cnyPerUsd = useUsageStore((s) => s.cnyPerUsd);
  const loadMessageCost = useUsageStore((s) => s.loadMessageCost);
  const cachedTurn = useUsageStore((s) => s.messageCosts[message.id] ?? null);
  const conversationId = useConversationStore((s) => s.currentConversationId);
  const navigate = useNavigate();
  const finishReason = !message.isStreaming
    ? (message.finishReason ?? message.runs?.finishReason)
    : undefined;
  const displayError =
    message.error ??
    (!message.isStreaming && !(message.content ?? "").trim()
      ? syntheticErrorForEmptyFailure(finishReason)
      : null);
  const errorAction = displayError
    ? errorActionForCode(displayError.code)
    : null;
  const showRetry =
    !!displayError &&
    (isConnectivityErrorCode(displayError.code) || !errorAction);
  const supportDiagnosticText = formatSupportDiagnosticText({
    conversationId,
    messageId: assistantProjectionId(message),
    traceId: message.traceId,
    executionId: message.executionId,
  });
  const copySupportDiagnostics = () => {
    if (!supportDiagnosticText) return;
    void copyText(supportDiagnosticText).then((ok) => {
      if (ok) notifySuccess("已复制诊断信息");
    });
  };
  const hasReasoning =
    !!message.reasoning && message.reasoning.trim().length > 0;
  const captainContext = message.captainContext ?? [];
  const hasProcess = (message.process?.length ?? 0) > 0;
  const citations = useMemo(() => message.citations ?? [], [message.citations]);
  const evidenceLedger = useMemo(
    () => message.evidenceLedger ?? [],
    [message.evidenceLedger],
  );
  const knownLedgerIds = useMemo(() => {
    const ids = new Set<string>();
    for (const e of evidenceLedger) {
      if (e.id) ids.add(e.id);
    }
    for (const c of citations) {
      if (c.id) ids.add(c.id);
    }
    return ids;
  }, [evidenceLedger, citations]);
  // Display renumbering: append-only across stream frames so assigned numbers
  // never jump. Reset when the message identity changes (component remounts per
  // bubble; also guard via message.id in case of reuse).
  const prevDisplayRef = useRef<Map<number, number>>(new Map());
  const prevMessageIdRef = useRef(message.id);
  if (prevMessageIdRef.current !== message.id) {
    prevMessageIdRef.current = message.id;
    prevDisplayRef.current = new Map();
  }
  const citationDisplay = useMemo(() => {
    const next = buildCitationDisplayMap(
      message.content,
      citations.length,
      prevDisplayRef.current,
      citations,
    );
    prevDisplayRef.current = next.stableCited;
    return next;
  }, [message.content, citations]);
  // Execution / graph slot key = server turn id when stamped (pause/resume share it).
  // ALSO the interaction lookup key: SSE / journal hydration writes interaction
  // entries keyed by `serverMessageId ?? id` (execMessageId), so the query MUST use
  // the same projection key — querying by the local client UUID silently missed
  // every card (统一投影键, 时间线一期).
  const projectionId = assistantProjectionId(message);
  const { checkpoints, nonBlockingAsks, planReviews, teamPreviews } =
    useMessageInteractionCards(conversationId, projectionId);
  const hideContentForCheckpoint = checkpoints.some(
    (c) => c.status === "resolved",
  );
  const singleAgentArtifacts = useMemo(
    () =>
      message.executionId === null
        ? fileArtifactsFromProcess(message.process)
        : [],
    [message.executionId, message.process],
  );
  const money =
    pickCostMoney(message.cost) ??
    (cachedTurn
      ? pickCostMoney({
          total: cachedTurn.cost.total,
          estimated_total: cachedTurn.estimated_cost?.total ?? null,
        })
      : null);
  // 未计价可见 (拍板 2026-07-20)：BYOK 无价可算时明示「未计价」，不静默省略。
  const costText =
    message.executionId === null && money != null && money.nano > 0
      ? formatCostCaption(money.nano, cnyPerUsd, money.estimated)
      : message.executionId === null &&
          message.cost?.pricing_source === "unpriced"
        ? COST_UNPRICED_LABEL
        : null;

  const onPeekCost = () => {
    if (!message.isStreaming && message.cost == null) {
      void loadMessageCost(message.id);
    }
  };

  // 流式中可复制 (对话基础功能补齐): the full footer is gated until the turn settles (its
  // usage / regenerate actions are meaningless mid-stream), but a long reply is often worth
  // copying before it finishes — so expose a lightweight copy affordance while streaming.
  // Default = 仅交付; with process timeline offer「含过程」too.
  const { copied: streamCopied, onCopy: onStreamCopy } = useCopyAction(() =>
    formatMessageExport(message.content, message.process, "deliverable"),
  );
  const { copied: streamCopiedProcess, onCopy: onStreamCopyProcess } =
    useCopyAction(() =>
      formatMessageExport(message.content, message.process, "with_process"),
    );

  const handleRegenerate = () => {
    const msgs = getActiveRuntime().messages;
    const idx = msgs.findIndex((m) => m.id === message.id);
    if (idx <= 0) return;
    let userId: string | null = null;
    for (let i = idx - 1; i >= 0; i--) {
      if (msgs[i].role === "user") {
        userId = msgs[i].id;
        break;
      }
    }
    if (userId) void runRegenerate(userId);
  };

  // 回合正文（时间线或答案）：对话页恒为传统聊天平铺（单 Agent 回合不再退化成 CEO 节点卡——
  // 那条「图主界面化」第一刀已撤，图相关体验只在画布；多 Agent 回合协作图内嵌在
  // `team` 标记槽——CEO 导语 content 步之下（协作图时间线落点））。
  // 回合级附件（收到的上下文 / 错误卡 / 产物 / 引用 / 检查点 / 操作行）随后平铺。
  const turnBody = hasProcess ? (
    <ProcessTimeline
      process={message.process ?? []}
      isStreaming={message.isStreaming}
      citations={citations}
      citationToDisplay={citationDisplay.toDisplay}
      knownLedgerIds={knownLedgerIds}
      evidenceLedger={evidenceLedger}
      composingTool={
        message.executionId === null ? (message.composingTool ?? null) : null
      }
      fallbackContent={hideContentForCheckpoint ? "" : message.content}
      messageId={projectionId}
      journal={message.runs}
      conversationId={conversationId}
      checkpoints={checkpoints}
      nonBlockingAsks={nonBlockingAsks}
      planReviews={planReviews}
      teamPreviews={teamPreviews}
    />
  ) : (
    <>
      {hasReasoning && (
        <ThinkingPanel
          reasoning={message.reasoning ?? ""}
          isStreaming={message.isStreaming}
          persistKey={`${message.id}:reasoning`}
        />
      )}
      {/* 不变量（时间线一期）：多 Agent 回合必有 `team` 标记（live 由
          setLastAssistantExecutionId 盖章，reload 由 journal 补齐）→ hasProcess 恒真、
          协作图只在 ProcessTimeline 的标记槽渲染；此分支仅剩单 Agent 纯文本回合。 */}
      {/* 长回答折叠 (对话基础功能补齐): while streaming, render full so the user watches
          it grow; once settled, cap a truly long answer to a fade + 展开全文 so it doesn't
          dominate the viewport (短/中答案原样全展). */}
      {message.isStreaming && !hideContentForCheckpoint ? (
        <Markdown
          content={message.content}
          citations={citations}
          citationToDisplay={citationDisplay.toDisplay}
          knownLedgerIds={knownLedgerIds}
          evidenceLedger={evidenceLedger}
          isStreaming={message.isStreaming}
        />
      ) : hideContentForCheckpoint ? null : (
        <CollapsibleSpeech
          contentKey={message.content}
          fadeToClass="from-background"
          collapsedMaxHClass="max-h-[40rem]"
          sceneKey={`answer:${message.id}`}
        >
          <Markdown
            content={message.content}
            citations={citations}
            citationToDisplay={citationDisplay.toDisplay}
            knownLedgerIds={knownLedgerIds}
            evidenceLedger={evidenceLedger}
            isStreaming={false}
          />
        </CollapsibleSpeech>
      )}
      {message.isStreaming &&
        (message.composingTool && message.executionId === null ? (
          <ComposingToolLine tool={message.composingTool} />
        ) : message.content.length === 0 && !hasReasoning ? (
          <span className="inline-flex items-center gap-2 text-sm text-muted-foreground">
            <ThinkingDots />
            Thinking…
          </span>
        ) : (
          <span
            className="mt-1 inline-block h-4 w-1.5 rounded-full bg-foreground/60"
            style={{ animation: "blink-cursor 0.8s step-end infinite" }}
          />
        ))}
    </>
  );

  return (
    <div className="group min-w-0" onMouseEnter={onPeekCost}>
      <FinishReasonChip
        reason={finishReason}
        diagnosisLabel={degradedFinishChipLabel(
          message.error?.context?.empty_diagnosis,
          displayError?.message ?? message.error?.message,
        )}
      />
      {message.turnWarning && (
        <TurnWarningBanner message={message.turnWarning} />
      )}
      {turnBody}
      {displayError && (
        <div className="mt-2 flex items-start gap-2 rounded-lg border border-destructive/30 bg-destructive/10 px-3 py-2.5 text-sm text-destructive">
          <AlertTriangle size={15} className="mt-0.5 shrink-0" />
          <p className="min-w-0 flex-1 whitespace-pre-wrap break-words">
            {formatAssistantErrorMessage(displayError)}
            {connectivityEscalationSuffix(displayError.code, message.id, {
              message: displayError.message,
              upstreamStatus: message.error?.context?.upstream_status,
            })}
          </p>
          {supportDiagnosticText && (
            <Button
              variant="ghost"
              className="shrink-0 text-destructive hover:bg-destructive/15"
              icon={<Copy size={13} />}
              onClick={copySupportDiagnostics}
            >
              复制诊断信息
            </Button>
          )}
          {errorAction && (
            <Button
              variant="destructive"
              className="shrink-0"
              icon={<KeyRound size={13} />}
              onClick={() => navigate(errorAction.href)}
            >
              {errorAction.label}
            </Button>
          )}
          {showRetry && (
            <Button
              variant="danger"
              className="shrink-0 border border-destructive/40"
              icon={<RefreshCw size={13} />}
              onClick={handleRegenerate}
            >
              重试
            </Button>
          )}
        </div>
      )}
      {message.executionId === null ? (
        singleAgentArtifacts.length > 0 && (
          <FileArtifactsCard
            artifacts={singleAgentArtifacts}
            conversationId={conversationId}
            turnKey={projectionId}
          />
        )
      ) : (
        <MultiAgentFileArtifacts
          messageId={projectionId}
          process={message.process}
        />
      )}
      {citations.length > 0 && (
        <SourceCards
          citations={citations}
          displayMap={citationDisplay}
          turnKey={projectionId}
          evidenceLedger={evidenceLedger}
        />
      )}
      {/* 底部堆叠回退已废除（时间线一期）：交互卡只在 ProcessTimeline 标记槽渲染。
          不变量「有交互卡必有时间线标记」由 live 盖章 + reload journal 补标记保证。 */}
      {message.isStreaming && message.content.length > 0 && (
        <div className="mt-1 flex items-center opacity-0 transition-opacity group-hover:opacity-100 focus-within:opacity-100">
          {(message.process?.length ?? 0) > 0 ? (
            <DropdownMenu>
              <SimpleTooltip
                label={streamCopied || streamCopiedProcess ? "已复制" : "复制"}
              >
                <DropdownMenuTrigger asChild>
                  <IconButton size="sm" aria-label="复制">
                    {streamCopied || streamCopiedProcess ? (
                      <Check size={14} />
                    ) : (
                      <Copy size={14} />
                    )}
                  </IconButton>
                </DropdownMenuTrigger>
              </SimpleTooltip>
              <DropdownMenuContent align="start" className="min-w-40">
                <DropdownMenuItem onSelect={() => void onStreamCopy()}>
                  仅交付
                </DropdownMenuItem>
                <DropdownMenuItem onSelect={() => void onStreamCopyProcess()}>
                  含过程
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          ) : (
            <SimpleTooltip label={streamCopied ? "已复制" : "复制"}>
              <IconButton
                size="sm"
                aria-label="复制"
                onClick={() => void onStreamCopy()}
              >
                {streamCopied ? <Check size={14} /> : <Copy size={14} />}
              </IconButton>
            </SimpleTooltip>
          )}
        </div>
      )}
      {!message.isStreaming && message.syncStatus && (
        <div className="mt-1">
          <SyncStatusHint syncStatus={message.syncStatus} />
        </div>
      )}
      {!message.isStreaming && !isGenerating && message.content.length > 0 && (
        <AssistantMessageFooter
          message={message}
          captainContext={captainContext}
          costText={costText}
          finishReason={finishReason}
          onRegenerate={handleRegenerate}
        />
      )}
    </div>
  );
}
