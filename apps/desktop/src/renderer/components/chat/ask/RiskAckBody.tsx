/**
 * risk_ack — 风险勾选清单：解析 label「[高]/[中]/[低]」前缀做严重度强调；recommended →「建议处理」。
 */
import { MANUAL_HELP, ManualHelpLink } from "@/components/ManualHelpLink";
import { Button } from "@/components/ui";
import type { CheckpointUserDecision } from "@/services/checkpoint";
import type { AskOption } from "@/types/events";
import { Check, Loader2, OctagonX, ShieldAlert } from "lucide-react";
import type { AskUserContent } from "./AskUserFields";
import type { useAskAnswer } from "./AskUserFields";
import { RISK_SEVERITY_META, parseRiskLabel } from "./parseRiskLabel";

export function RiskAckBody({
  content,
  answer,
  busy,
  submitting,
  caption,
  cta,
  onContinue,
  onStop,
}: {
  content: AskUserContent;
  answer: ReturnType<typeof useAskAnswer>;
  busy: boolean;
  submitting: CheckpointUserDecision | null;
  caption: string;
  cta: string;
  onContinue: () => void;
  onStop: () => void;
}) {
  const q = content.questions[0];
  const picked = q ? (answer.answers[q.id] ?? []) : [];

  return (
    <>
      <div className="min-h-0 flex-1 space-y-3 overflow-y-auto px-3 pt-3">
        <div className="flex items-start gap-1.5">
          <ShieldAlert
            size={14}
            className="mt-0.5 shrink-0 text-muted-foreground"
          />
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-1">
              <p className="min-w-0 flex-1 text-xs font-medium text-muted-foreground">
                {caption}
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

        {q && (
          <div className="space-y-1.5" data-ask-variant="risk_ack">
            {q.prompt && (
              <div className="flex items-center gap-2">
                <p className="min-w-0 flex-1 text-xs font-medium text-muted-foreground">
                  {q.prompt}
                </p>
                <span className="shrink-0 rounded-full bg-muted px-1.5 py-0.5 text-xs text-muted-foreground">
                  可多选
                </span>
              </div>
            )}
            {q.options.map((opt) => (
              <RiskRow
                key={opt.label}
                option={opt}
                active={picked.includes(opt.label)}
                disabled={busy}
                onToggle={() => answer.toggleChoice(q, opt.label)}
              />
            ))}
          </div>
        )}

        <textarea
          value={answer.note}
          onChange={(e) => answer.setNote(e.target.value)}
          disabled={busy}
          rows={2}
          placeholder="补充说明（可选）"
          className="w-full rounded-lg border border-border bg-card px-2.5 py-1.5 text-xs text-foreground placeholder:text-muted-foreground/70 focus:border-foreground/25 focus:outline-none disabled:opacity-40"
        />
      </div>

      <div className="shrink-0 space-y-2 px-3 pb-3 pt-1">
        <div className="flex flex-wrap items-center gap-2">
          <Button
            size="md"
            variant="primary"
            className="bg-primary text-primary-foreground hover:bg-primary/90"
            disabled={busy}
            onClick={onContinue}
            icon={
              submitting === "continue" ? (
                <Loader2 size={14} className="animate-spin" />
              ) : (
                <ShieldAlert size={14} />
              )
            }
          >
            {cta}
          </Button>
          <Button
            size="md"
            variant="danger"
            disabled={busy}
            onClick={onStop}
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
    </>
  );
}

function RiskRow({
  option,
  active,
  disabled,
  onToggle,
}: {
  option: AskOption;
  active: boolean;
  disabled: boolean;
  onToggle: () => void;
}) {
  const { severity, text } = parseRiskLabel(option.label);
  const meta = severity ? RISK_SEVERITY_META[severity] : null;

  return (
    <button
      type="button"
      disabled={disabled}
      onClick={onToggle}
      aria-pressed={active}
      className={`flex w-full items-start gap-2.5 rounded-xl border px-3 py-2.5 text-left transition-colors disabled:opacity-40 ${
        active
          ? `bg-muted/60 ${meta?.border ?? "border-foreground/25"}`
          : `${meta?.border ?? "border-border"} bg-card hover:bg-accent/50`
      }`}
    >
      <span
        className={`mt-0.5 flex size-4 shrink-0 items-center justify-center rounded border ${
          active
            ? "border-foreground/50 bg-foreground text-background"
            : "border-border bg-transparent"
        }`}
        aria-hidden
      >
        {active && <Check size={10} strokeWidth={3} />}
      </span>
      <span className="min-w-0 flex-1">
        <span className="flex flex-wrap items-center gap-x-2 gap-y-0.5">
          {meta && (
            <span
              className={`shrink-0 rounded px-1 py-0.5 text-xs font-medium ${meta.chip}`}
            >
              {meta.tag}
            </span>
          )}
          <span className="text-sm font-medium text-foreground">{text}</span>
          {option.recommended && (
            <span className="shrink-0 text-xs text-muted-foreground">
              建议处理
            </span>
          )}
        </span>
        {option.detail && (
          <span className="mt-0.5 block text-xs leading-snug text-muted-foreground">
            {option.detail}
          </span>
        )}
      </span>
    </button>
  );
}
