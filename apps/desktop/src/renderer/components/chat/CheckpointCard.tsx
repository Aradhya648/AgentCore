import { MANUAL_HELP, ManualHelpLink } from "@/components/ManualHelpLink";
import {
  ASK_INTENT_META,
  ResolvedDecisionRecord,
  askResolvedOutcome,
} from "@/components/chat/decision";
import { Button, DecisionCard } from "@/components/ui";
import { interactiveCheckpointTone } from "@/components/ui/tone-presets";
import { notifyError } from "@/lib/toast";
import type { CheckpointUserDecision } from "@/services/checkpoint";
import type { CheckpointDisplay } from "@/stores/conversation";
import type { CheckpointIntent } from "@/types/events";
import { Loader2, OctagonX } from "lucide-react";
import { useState } from "react";
import { AskCommenceKickoffBody } from "./ask/AskCommenceKickoff";
import {
  AskNoteField,
  AskQuestionFields,
  type AskUserContent,
  useAskAnswer,
} from "./ask/AskUserFields";
import { OrganizePlanBody } from "./ask/OrganizePlanBody";
import { ProposalPickBody } from "./ask/ProposalPickBody";
import { RiskAckBody } from "./ask/RiskAckBody";
import { RISK_SEVERITY_META, parseRiskLabel } from "./ask/parseRiskLabel";

/**
 * Inline ask_user card — the CEO paused the turn to ask the user. This is the ONE
 * asking surface (it absorbed the former kickoff 开工提案卡): the same suspend +
 * resolve card adapts to both an **opening 引导** (a producible-but-underspecified
 * request → 起步计划 assumptions + ≤5 pre-filled 重点问题 + style presets) and a
 * compact **mid-task fork** (one focal A/B / irreversible step). Rendered under the
 * assistant bubble that raised it (会话流内), so it both gates the live turn and
 * replays inline on reload.
 *
 * The interactive body lives in {@link AskUserCard}, reused by the durable 待恢复 resume
 * card (ResumePrompt) — one card, one answer model.
 *
 * 挂起即收口 (②, Phase 3): an inline ask_user card is never live-interactive anymore — a
 * CEO checkpoint finalizes the turn (its in-process resolve Future is never parked), so
 * the actionable surface is always the durable resume card. Inline, pending renders nothing
 * (CEO message body stays visible); settled → resolved record card.
 *
 * Resolved copy / icons come from the shared decision meta ({@link ASK_INTENT_META}).
 */
export function CheckpointCard({
  checkpoint,
}: {
  checkpoint: CheckpointDisplay;
}) {
  if (checkpoint.status === "resolved") {
    return <ResolvedCheckpoint checkpoint={checkpoint} />;
  }
  return null;
}

/** Per-tone class sets — from shared tone-presets (Tailwind literal strings). */
const TONE = interactiveCheckpointTone;

/** Flatten per-question picks (+「其他」自定义) into resume `selected`. */
export function collectAskSelected(
  content: AskUserContent,
  answers: Record<string, string[]>,
  otherOn: Record<string, boolean>,
  otherText: Record<string, string>,
): string[] {
  const out: string[] = [];
  for (const q of content.questions) {
    for (const v of answers[q.id] ?? []) {
      const t = v.trim();
      if (t) out.push(t);
    }
    if (otherOn[q.id]) {
      const custom = (otherText[q.id] ?? "").trim();
      if (custom) out.push(custom);
    }
  }
  return out;
}

/**
 * The live, actionable ask_user card body — the single asking surface, shared by the
 * inline live card ({@link CheckpointCard}) and the durable 待恢复 resume card
 * (ResumePrompt). Settled by 提交/就这样开做 (→ continue) or 停止. Picks compose into
 * ONE readable note (答复模型 α), handed to `onSubmit`.
 *
 * - **kickoff**：V2 Brief + Choose（中文 caption 头 + brief 钳 2 行 + 题干与紧凑单行选项常驻 + 计划/补充折叠行）。
 * - **decision**：紧凑单栏拍板（灰壳灰选项；Footer 主 CTA 仍用品牌蓝）。
 * - **proposal_pick**：方案墙（单选卡 + selected）。
 * - **risk_ack**：风险勾选清单（多选 + 严重度前缀 + selected）。
 *
 * icon + caption + CTA 文案由后端 intent 查表驱动（{@link ASK_INTENT_META}）。真·风险审批由 ApprovalPrompt 承载（蓝）。
 */
export function AskUserCard({
  content,
  intent,
  caption,
  onSubmit,
  disclosureKey,
  conversationId,
}: {
  content: AskUserContent;
  intent: CheckpointIntent;
  caption?: string;
  onSubmit: (
    decision: CheckpointUserDecision,
    note: string,
    selected?: string[],
    styleId?: string | null,
  ) => void | Promise<void>;
  /** 检查点 id：给了才把起步计划开合持久化。 */
  disclosureKey?: string | null;
  /** Enables bind_local_folder action options on desktop. */
  conversationId?: string | null;
}) {
  const config = ASK_INTENT_META[intent];
  const tone = TONE.neutral;
  const ans = useAskAnswer(content, {
    seedAllMultiple: intent === "organize_plan",
  });
  const [submitting, setSubmitting] = useState<CheckpointUserDecision | null>(
    null,
  );
  const busy = submitting !== null;
  const HeaderIcon = config.icon;
  const CtaIcon = config.ctaIcon;
  const carriesSelected =
    intent === "proposal_pick" ||
    intent === "risk_ack" ||
    intent === "organize_plan";

  const send = (decision: CheckpointUserDecision, noteOverride?: string) => {
    if (busy) return;
    setSubmitting(decision);
    const baseSelected =
      decision === "continue" && carriesSelected
        ? collectAskSelected(content, ans.answers, ans.otherOn, ans.otherText)
        : [];
    // Structured style wire (B+A): explicit style_id + sN in selected when styles offered.
    const stylePick =
      decision === "continue" && ans.styleId ? ans.styleId : null;
    const selected =
      stylePick && !baseSelected.includes(stylePick)
        ? [...baseSelected, stylePick]
        : baseSelected;
    const composed =
      noteOverride !== undefined
        ? noteOverride
        : decision === "stop"
          ? ans.note.trim()
          : carriesSelected
            ? ans.note.trim()
            : ans.compose(intent);
    Promise.resolve(onSubmit(decision, composed, selected, stylePick)).catch(
      (err) => {
        notifyError(err, "提交失败");
        setSubmitting(null);
      },
    );
  };

  const onBindResolve = (composedAnswer: string) =>
    send("continue", composedAnswer);

  // Kickoff: production default = V2 Brief + Choose (same IA as AskCommenceV2 preview).
  if (intent === "kickoff") {
    return (
      <DecisionCard
        tone="neutral"
        animate
        className="flex max-h-[min(60vh,36rem)] flex-col overflow-hidden p-0"
        data-ask-intent="kickoff"
      >
        <AskCommenceKickoffBody
          content={content}
          answer={ans}
          busy={busy}
          submitting={submitting}
          onContinue={() => send("continue")}
          onStop={() => send("stop")}
          conversationId={conversationId}
          onBindResolve={onBindResolve}
        />
      </DecisionCard>
    );
  }

  if (intent === "proposal_pick") {
    return (
      <DecisionCard
        tone="neutral"
        animate
        className="flex max-h-[min(50vh,28rem)] flex-col overflow-hidden p-0"
        data-ask-intent="proposal_pick"
      >
        <ProposalPickBody
          content={content}
          answer={ans}
          busy={busy}
          submitting={submitting}
          caption={caption ?? config.activeCaption}
          cta={config.cta}
          onContinue={() => send("continue")}
          onStop={() => send("stop")}
        />
      </DecisionCard>
    );
  }

  if (intent === "risk_ack") {
    return (
      <DecisionCard
        tone="neutral"
        animate
        className="flex max-h-[min(50vh,28rem)] flex-col overflow-hidden p-0"
        data-ask-intent="risk_ack"
      >
        <RiskAckBody
          content={content}
          answer={ans}
          busy={busy}
          submitting={submitting}
          caption={caption ?? config.activeCaption}
          cta={config.cta}
          onContinue={() => send("continue")}
          onStop={() => send("stop")}
        />
      </DecisionCard>
    );
  }

  if (intent === "organize_plan") {
    return (
      <DecisionCard
        tone="neutral"
        animate
        className="flex max-h-[min(60vh,36rem)] flex-col overflow-hidden p-0"
        data-ask-intent="organize_plan"
      >
        <OrganizePlanBody
          content={content}
          answer={ans}
          busy={busy}
          submitting={submitting}
          caption={caption ?? config.activeCaption}
          cta={config.cta}
          onContinue={() => send("continue")}
          onStop={() => send("stop")}
        />
      </DecisionCard>
    );
  }

  return (
    <DecisionCard
      tone="neutral"
      animate
      className="flex max-h-[min(50vh,28rem)] flex-col overflow-hidden p-0"
      data-ask-intent="decision"
    >
      <div className="min-h-0 flex-1 space-y-3 overflow-y-auto px-3 pt-3">
        <div className="flex items-start gap-1.5">
          <HeaderIcon size={14} className={`mt-0.5 shrink-0 ${tone.accent}`} />
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-1">
              <p
                className={`min-w-0 flex-1 text-xs font-medium ${tone.accent}`}
              >
                {caption ?? config.activeCaption}
              </p>
              <ManualHelpLink to={MANUAL_HELP.checkpoint} />
            </div>
            <p className="mt-0.5 whitespace-pre-wrap text-sm text-foreground">
              {content.question}
            </p>
            {content.context && (
              <p className="mt-1 whitespace-pre-wrap text-xs text-muted-foreground">
                {content.context}
              </p>
            )}
          </div>
        </div>

        <AskQuestionFields
          content={content}
          answer={ans}
          tone={tone}
          disabled={busy}
          disclosureKey={disclosureKey}
          conversationId={conversationId}
          onBindResolve={onBindResolve}
        />

        <AskNoteField
          answer={ans}
          tone={tone}
          disabled={busy}
          placeholder="补充说明"
        />
      </div>

      <div className="shrink-0 space-y-2 px-3 pb-3 pt-1">
        <div className="flex flex-wrap items-center gap-2">
          <Button
            size="md"
            variant="primary"
            className={tone.cta}
            disabled={busy}
            onClick={() => send("continue")}
            icon={
              submitting === "continue" ? (
                <Loader2 size={14} className="animate-spin" />
              ) : (
                <CtaIcon size={14} />
              )
            }
          >
            {config.cta}
          </Button>
          <Button
            size="md"
            variant="danger"
            disabled={busy}
            onClick={() => send("stop")}
            icon={
              submitting === "stop" ? (
                <Loader2 size={14} className="animate-spin" />
              ) : (
                <OctagonX size={14} />
              )
            }
          >
            停止
          </Button>
        </div>
      </div>
    </DecisionCard>
  );
}

/** The settled record of an ask_user card: how it was decided, plus the user's
 * answer note. Carries its outcome's tone (calm) so a glance down the history reads
 * the verdict without expanding. */
function ResolvedCheckpoint({ checkpoint }: { checkpoint: CheckpointDisplay }) {
  const decision = checkpoint.decision ?? "timeout";
  const resolved = askResolvedOutcome(checkpoint.intent, decision);
  const showRiskChips = checkpoint.intent === "risk_ack";

  return (
    <ResolvedDecisionRecord
      layout="toneStub"
      disclosureKey={checkpoint.id ? `${checkpoint.id}:resolved` : null}
      tone={resolved.tone}
      icon={resolved.icon}
      label={resolved.label}
      collapsedSummary={checkpoint.question}
      askIntent={checkpoint.intent}
    >
      <div className="space-y-1.5 pb-3 pl-10 pr-3">
        <p className="whitespace-pre-wrap text-sm text-foreground">
          {checkpoint.question}
        </p>
        {checkpoint.selected.length > 0 && (
          <div className="flex flex-wrap gap-1">
            {checkpoint.selected.map((s) =>
              showRiskChips ? (
                <ResolvedRiskChip key={s} label={s} />
              ) : (
                <span
                  key={s}
                  className="rounded-full bg-muted px-2 py-0.5 text-xs text-foreground"
                >
                  {s}
                </span>
              ),
            )}
          </div>
        )}
        {checkpoint.note && (
          <p className="whitespace-pre-wrap rounded-lg bg-muted/50 px-2.5 py-1.5 text-xs text-foreground">
            {checkpoint.note}
          </p>
        )}
      </div>
    </ResolvedDecisionRecord>
  );
}

function ResolvedRiskChip({ label }: { label: string }) {
  const { severity, text } = parseRiskLabel(label);
  const meta = severity ? RISK_SEVERITY_META[severity] : null;
  return (
    <span className="inline-flex max-w-full items-center gap-1 rounded-full bg-muted px-2 py-0.5 text-xs text-foreground">
      {meta && (
        <span className={`rounded px-1 py-px text-xs font-medium ${meta.chip}`}>
          {meta.tag}
        </span>
      )}
      <span className="min-w-0 truncate">{text}</span>
    </span>
  );
}
