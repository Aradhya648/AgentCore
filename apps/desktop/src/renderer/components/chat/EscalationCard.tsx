import { MANUAL_HELP, ManualHelpLink } from "@/components/ManualHelpLink";
import { escalationRowKindLabel } from "@/components/graph/agentNode/shared";
import { Button, DecisionCard, DecisionCardIcon } from "@/components/ui";
import { interactiveCheckpointTone } from "@/components/ui/tone-presets";
import { notifyError } from "@/lib/toast";
import {
  type EscalationUserDecision,
  decideEscalation,
} from "@/services/escalation";
import { submitInteractionFeedback } from "@/services/interactionSubmit";
import { type RunEscalation, useMessageExecution } from "@/stores/execution";
import { useInteractionStore } from "@/stores/interactions";
import { useSidePanelStore } from "@/stores/sidePanel";
import {
  ArrowRight,
  Check,
  Clock,
  HelpCircle,
  Loader2,
  LogIn,
  Megaphone,
  Radio,
} from "lucide-react";
import { useState } from "react";
import { OrphanedInteractionCard } from "./OrphanedInteractionCard";
import {
  AskNoteField,
  AskQuestionFields,
  type AskUserContent,
  useAskAnswer,
} from "./ask/AskUserFields";

function escalationKindTag(esc: RunEscalation): string | null {
  return escalationRowKindLabel(esc);
}

export function EscalationCard({
  escalation,
  role,
  conversationId,
  interactive,
}: {
  escalation: RunEscalation;
  role: string;
  conversationId: string | null;
  interactive: boolean;
}) {
  // 非阻塞上报 (run_escalation): the worker flagged a decision but kept working on its
  // assumption — a turn-level NOTICE, never a 待拍板 card (no resolve target). Handled
  // first so it never falls through to the pending path (which POSTs to a null id).
  if (escalation.status === "raised") {
    return <RaisedEscalation escalation={escalation} role={role} />;
  }
  if (
    escalation.status === "resolved" ||
    escalation.status === "assumed" ||
    escalation.status === "timed_out"
  ) {
    return <ResolvedEscalation escalation={escalation} role={role} />;
  }
  // browser_login must stay user-facing (password); check before awaiting=ceo.
  if (escalation.status === "pending" && escalation.browserLogin) {
    return (
      <PendingBrowserLoginEscalation
        escalation={escalation}
        role={role}
        conversationId={conversationId}
      />
    );
  }
  // D1: CEO arbitration pending — visible but not user-answerable.
  if (escalation.status === "pending" && escalation.awaiting === "ceo") {
    return <AwaitingCeoEscalation escalation={escalation} role={role} />;
  }
  if (!interactive) {
    return <DormantEscalation escalation={escalation} role={role} />;
  }
  return (
    <PendingEscalation
      escalation={escalation}
      role={role}
      conversationId={conversationId}
    />
  );
}

function useEscalationSubmit(
  conversationId: string | null,
  escalationId: string | null,
) {
  const [submitting, setSubmitting] = useState<
    EscalationUserDecision["kind"] | null
  >(null);
  const busy = submitting !== null;

  const send = (decision: EscalationUserDecision) => {
    if (busy || !conversationId || !escalationId) return;
    setSubmitting(decision.kind);
    decideEscalation(conversationId, escalationId, decision)
      .then((result) => {
        if (result === "orphaned" || result === "busy") {
          notifyError(submitInteractionFeedback(result));
          setSubmitting(null);
        }
        // ok: SSE escalation_resolved settles the card
      })
      .catch((err) => {
        notifyError(err, "提交失败");
        setSubmitting(null);
      });
  };

  return { submitting, busy, send };
}

/** 浏览器登录等待 escalate：不 auto-resume；用户接管登录后点「已登录，继续」resolve。 */
function PendingBrowserLoginEscalation({
  escalation,
  role,
  conversationId,
}: {
  escalation: RunEscalation;
  role: string;
  conversationId: string | null;
}) {
  const { submitting, busy, send } = useEscalationSubmit(
    conversationId,
    escalation.id,
  );

  return (
    <DecisionCard tone="primary" animate>
      <div className="flex items-start gap-2">
        <DecisionCardIcon tone="primary">
          <LogIn size={16} />
        </DecisionCardIcon>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1">
            <p className="min-w-0 flex-1 text-xs font-medium text-primary">
              {role} · 需要你登录
              {escalationKindTag(escalation)
                ? ` · ${escalationKindTag(escalation)}`
                : ""}
            </p>
            <ManualHelpLink to={MANUAL_HELP.control} />
          </div>
          <p className="mt-0.5 text-xs text-muted-foreground">
            在直播里完成登录后，点「已登录，继续」
          </p>
          <p className="mt-0.5 whitespace-pre-wrap text-sm text-foreground">
            {escalation.question}
          </p>
          {escalation.assumption ? (
            <p className="mt-2 rounded-lg bg-card/60 px-2.5 py-1.5 text-xs text-muted-foreground">
              未答则按此继续：{escalation.assumption}
            </p>
          ) : null}
        </div>
      </div>

      <div className="mt-2.5 flex flex-wrap items-center gap-1.5 pl-6">
        {conversationId && (
          <Button
            variant="neutral"
            disabled={busy}
            onClick={() =>
              useSidePanelStore.getState().openBrowserLive(conversationId)
            }
            icon={<Radio size={13} />}
          >
            打开浏览器直播
          </Button>
        )}
        <Button
          variant="primary"
          disabled={busy}
          onClick={() => send({ kind: "answer", answer: "已登录，继续" })}
          icon={
            submitting === "answer" ? (
              <Loader2 size={13} className="animate-spin" />
            ) : (
              <Check size={13} />
            )
          }
        >
          已登录，继续
        </Button>
        <Button
          variant="neutral"
          disabled={busy}
          onClick={() => send({ kind: "use_assumption" })}
          icon={
            submitting === "use_assumption" ? (
              <Loader2 size={13} className="animate-spin" />
            ) : (
              <ArrowRight size={13} />
            )
          }
        >
          按假设继续
        </Button>
      </div>
    </DecisionCard>
  );
}

function PendingEscalation({
  escalation,
  role,
  conversationId,
}: {
  escalation: RunEscalation;
  role: string;
  conversationId: string | null;
}) {
  // 结构化升级: reuse the ask_user 问答内核 (choice/text + 答复模型 α composition). A worker
  // fork is always a 待你拍板 (no 起步计划 / 风格), so the content carries only the structured
  // `questions`; the free note doubles as the answer box for a plain free-text escalate.
  const content: AskUserContent = {
    question: escalation.question,
    context: "",
    assumptions: [],
    questions: escalation.questions,
    styleOptions: [],
  };
  const ans = useAskAnswer(content);
  const tone = interactiveCheckpointTone.primary;
  const { submitting, busy, send } = useEscalationSubmit(
    conversationId,
    escalation.id,
  );
  const hasStructured = escalation.questions.length > 0;
  // composeAnswer flattens picks + note into one readable string (a worker reads it like the
  // CEO does); for a free-text escalate it is just the note. 提交 needs a non-empty answer.
  const composed = ans.compose("decision");
  const canSubmit = composed.trim().length > 0;

  return (
    <DecisionCard tone="primary" animate>
      <div className="flex items-start gap-2">
        <DecisionCardIcon tone="primary">
          <HelpCircle size={16} />
        </DecisionCardIcon>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1">
            <p className="min-w-0 flex-1 text-xs font-medium text-primary">
              {role} · 请你拍板
              {escalationKindTag(escalation)
                ? ` · ${escalationKindTag(escalation)}`
                : ""}
            </p>
            <ManualHelpLink to={MANUAL_HELP.control} />
          </div>
          <p className="mt-0.5 text-xs text-muted-foreground">
            等你拍板 · 不限时
          </p>
          <p className="mt-0.5 whitespace-pre-wrap text-sm text-foreground">
            {escalation.question}
          </p>
          <p className="mt-2 rounded-lg bg-card/60 px-2.5 py-1.5 text-xs text-muted-foreground">
            未答则按此继续：{escalation.assumption}
          </p>
          <div className="mt-2 space-y-3">
            {hasStructured && (
              <AskQuestionFields
                content={content}
                answer={ans}
                tone={tone}
                disabled={busy}
                disclosureKey={escalation.id}
              />
            )}
            <AskNoteField
              answer={ans}
              tone={tone}
              disabled={busy}
              placeholder={
                hasStructured
                  ? "可选 · 补充说明"
                  : "输入你的决定（留空则点「按假设继续」）"
              }
            />
          </div>
        </div>
      </div>

      <div className="mt-2.5 flex flex-wrap items-center gap-1.5 pl-6">
        <Button
          variant="primary"
          disabled={busy || !canSubmit}
          onClick={() => send({ kind: "answer", answer: composed })}
          icon={
            submitting === "answer" ? (
              <Loader2 size={13} className="animate-spin" />
            ) : (
              <Check size={13} />
            )
          }
        >
          提交
        </Button>
        <Button
          variant="neutral"
          disabled={busy}
          onClick={() => send({ kind: "use_assumption" })}
          icon={
            submitting === "use_assumption" ? (
              <Loader2 size={13} className="animate-spin" />
            ) : (
              <ArrowRight size={13} />
            )
          }
        >
          按假设继续
        </Button>
      </div>
    </DecisionCard>
  );
}

function AwaitingCeoEscalation({
  escalation,
  role,
}: {
  escalation: RunEscalation;
  role: string;
}) {
  return (
    <DecisionCard tone="neutral">
      <div className="flex items-start gap-2">
        <DecisionCardIcon tone="neutral">
          <Loader2 size={16} className="animate-spin" />
        </DecisionCardIcon>
        <div className="min-w-0 flex-1">
          <p className="text-xs font-medium text-muted-foreground">
            {role} · 等待主管仲裁
            {escalationKindTag(escalation)
              ? ` · ${escalationKindTag(escalation)}`
              : ""}
          </p>
          <p className="mt-0.5 whitespace-pre-wrap text-sm text-foreground">
            {escalation.question}
          </p>
          <p className="mt-2 rounded-lg bg-card/60 px-2.5 py-1.5 text-xs text-muted-foreground">
            未裁则按此继续：{escalation.assumption}
          </p>
        </div>
      </div>
    </DecisionCard>
  );
}

function DormantEscalation({
  escalation,
  role,
}: {
  escalation: RunEscalation;
  role: string;
}) {
  return (
    <DecisionCard tone="neutral">
      <div className="flex items-start gap-2">
        <DecisionCardIcon tone="neutral">
          <HelpCircle size={16} />
        </DecisionCardIcon>
        <div className="min-w-0 flex-1">
          <p className="text-xs font-medium text-muted-foreground">
            {role} 曾请你拍板（本回合已结束）
          </p>
          <p className="mt-0.5 whitespace-pre-wrap text-sm text-foreground">
            {escalation.question}
          </p>
          <p className="mt-1.5 text-xs text-muted-foreground">
            暂定假设：{escalation.assumption}
          </p>
        </div>
      </div>
    </DecisionCard>
  );
}

/** 非阻塞上报「边干边提醒」(run_escalation, status=raised): the worker surfaced a
 * decision/blocker but did NOT suspend — it proceeded on its assumption. A passive,
 * non-interactive notice (neutral tone, no buttons) so 升级实时可见 holds even when the
 * 协作图 is collapsed, while staying visibly distinct from a 待你拍板 decision card. */
function RaisedEscalation({
  escalation,
  role,
}: {
  escalation: RunEscalation;
  role: string;
}) {
  return (
    <DecisionCard tone="neutral" className="bg-card/60">
      <div className="flex items-start gap-2">
        <span className="mt-0.5 shrink-0 text-muted-foreground">
          <Megaphone size={14} />
        </span>
        <div className="min-w-0 flex-1">
          <p className="text-xs font-medium text-muted-foreground">
            {role} · 边干边上报（无需你拍板）
            {escalationKindTag(escalation)
              ? ` · ${escalationKindTag(escalation)}`
              : ""}
          </p>
          <p className="mt-0.5 whitespace-pre-wrap text-sm text-foreground">
            {escalation.question}
          </p>
          <p className="mt-1.5 text-xs text-muted-foreground">
            已按假设继续：{escalation.assumption}
          </p>
        </div>
      </div>
    </DecisionCard>
  );
}

function ResolvedEscalation({
  escalation,
  role,
}: {
  escalation: RunEscalation;
  role: string;
}) {
  const byCeo = escalation.arbitrated_by === "ceo";
  const viaUser = byCeo && escalation.via_user === true;
  const assumed = escalation.status === "assumed";
  const timedOut = escalation.status === "timed_out";
  const isFallback = assumed || timedOut;
  let headline: string;
  if (assumed) {
    headline = byCeo ? "主管选按假设继续" : "你选了按假设继续";
  } else if (timedOut) {
    headline = byCeo ? "主管未裁 · 超时按假设继续" : "超时未答 · 已按假设继续";
  } else if (byCeo) {
    headline = viaUser ? "CEO 已仲裁（经用户）" : "CEO 已仲裁";
  } else {
    headline = "已答复";
  }
  return (
    <DecisionCard tone="neutral" className="bg-card/60">
      <div className="flex items-start gap-2">
        <span className="mt-0.5 shrink-0 text-muted-foreground">
          {isFallback ? <Clock size={14} /> : <Check size={14} />}
        </span>
        <div className="min-w-0 flex-1">
          <p className="text-xs font-medium text-muted-foreground">
            {role} · {headline}
          </p>
          <p className="mt-0.5 whitespace-pre-wrap text-sm text-foreground">
            {escalation.question}
          </p>
          {isFallback ? (
            <p className="mt-1.5 text-xs text-muted-foreground">
              {timedOut ? "超时回落假设：" : "按假设继续："}
              {escalation.assumption}
            </p>
          ) : (
            escalation.answer && (
              <p className="mt-1.5 whitespace-pre-wrap rounded-lg bg-muted/50 px-2.5 py-1.5 text-xs text-foreground">
                {escalation.answer}
              </p>
            )
          )}
        </div>
      </div>
    </DecisionCard>
  );
}

export function EscalationCards({
  messageId,
  conversationId,
  interactive,
}: {
  messageId: string;
  conversationId: string | null;
  interactive: boolean;
}) {
  const execution = useMessageExecution(messageId);
  const orphanedEscalations = useInteractionStore((s) => s.byId);
  if (!execution) return null;

  const roleById = new Map(execution.agents.map((a) => [a.id, a.role]));
  const items = execution.runs.flatMap((run) =>
    run.escalations.map((e, i) => ({
      esc: e,
      role: roleById.get(run.agentId) ?? run.agentId,
      key: e.id ?? `${run.id}-${i}`,
    })),
  );
  const orphaned = conversationId
    ? [...orphanedEscalations.values()].filter(
        (e) =>
          e.conversationId === conversationId &&
          e.kind === "escalation" &&
          e.status === "orphaned" &&
          (e.messageId === messageId || !e.messageId),
      )
    : [];
  if (items.length === 0 && orphaned.length === 0) return null;

  const pendingCount = items.filter((i) => i.esc.status === "pending").length;

  return (
    <div className="mt-2 space-y-2">
      {orphaned.map((o) => (
        <OrphanedInteractionCard
          key={o.id}
          title="升级确认已失效"
          detail="该升级请求已不可答复（服务已重启或回合已结束）。"
        />
      ))}
      {pendingCount > 0 && (
        <p className="text-xs font-medium text-primary">
          团队有 {pendingCount} 项待你拍板
        </p>
      )}
      {items.map((i) => (
        <EscalationCard
          key={i.key}
          escalation={i.esc}
          role={i.role}
          conversationId={conversationId}
          interactive={interactive}
        />
      ))}
    </div>
  );
}
