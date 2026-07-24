/**
 * proposal_pick — 方案墙：每个候选一张可点选卡（方案名 + 取舍一行 + 推荐徽章）。
 */
import { MANUAL_HELP, ManualHelpLink } from "@/components/ManualHelpLink";
import { Button } from "@/components/ui";
import type { CheckpointUserDecision } from "@/services/checkpoint";
import { Layers, Loader2, OctagonX } from "lucide-react";
import { OptionButton } from "./AskCommenceParts";
import type { AskUserContent } from "./AskUserFields";
import type { useAskAnswer } from "./AskUserFields";

export function ProposalPickBody({
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
  const canSubmit = picked.length > 0;

  return (
    <>
      <div className="min-h-0 flex-1 space-y-3 overflow-y-auto px-3 pt-3">
        <div className="flex items-start gap-1.5">
          <Layers size={14} className="mt-0.5 shrink-0 text-muted-foreground" />
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
          <div className="grid gap-2" data-ask-variant="proposal_pick">
            {q.prompt && (
              <p className="text-xs font-medium text-muted-foreground">
                {q.prompt}
              </p>
            )}
            {q.options.map((opt) => (
              <OptionButton
                key={opt.label}
                label={opt.label}
                detail={opt.detail}
                recommended={opt.recommended}
                active={picked.includes(opt.label)}
                disabled={busy}
                onClick={() => answer.toggleChoice(q, opt.label)}
                layout="card"
                size="lg"
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
            disabled={busy || !canSubmit}
            onClick={onContinue}
            icon={
              submitting === "continue" ? (
                <Loader2 size={14} className="animate-spin" />
              ) : (
                <Layers size={14} />
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
