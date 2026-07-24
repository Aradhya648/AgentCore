import { Button } from "@/components/ui";
import { invalidateTurnAudit, useTurnAudit } from "@/hooks/useTurnAudit";
import { isWebPreview } from "@/lib/preview";
import {
  type RunOutcomeReason,
  acceptRunOutcome,
} from "@/services/runRedirect";
import { AlertTriangle, CheckCircle2 } from "lucide-react";
import { useMemo, useState } from "react";
import { toast } from "sonner";
import { Section } from "./shared";

/** What the terminal dead end was, driving the card copy + the recorded `reason`. */
type AcceptState =
  | { kind: "hidden" }
  | { kind: "accepted" }
  | { kind: "offer"; reason: RunOutcomeReason };

const COPY: Record<RunOutcomeReason, { heading: string; body: string }> = {
  redirect_ignored: {
    heading: "改方向未生效",
    body: "你的「立即改此人」发出时，该步骤已结束或无法中途改道——这次调整没有应用。可接受当前结果，或在对话里让 CEO 重新安排。",
  },
  deterministic_failure: {
    heading: "重试大概率仍会失败",
    body: "这是确定性失败（如提示过长 / 鉴权 / 余额），同样的重试会再次失败。可接受此结果，让团队据此收尾。",
  },
  recovery_ignored: {
    heading: "已忽略这次救火",
    body: "你发起了新回合，上次救火已隐式收口——该步骤保持失败态收尾。可接受此结果，或在对话里让 CEO 重新安排。",
  },
};

function resolveAcceptState(
  forRun: { action: string }[],
  optimisticAccepted: boolean,
): AcceptState {
  if (optimisticAccepted) return { kind: "accepted" };
  if (forRun.some((ev) => ev.action === "run.outcome_accepted")) {
    return { kind: "accepted" };
  }
  if (forRun.some((ev) => ev.action === "run.redirect_ignored")) {
    return { kind: "offer", reason: "redirect_ignored" };
  }
  if (forRun.some((ev) => ev.action === "run.deterministic_failure")) {
    return { kind: "offer", reason: "deterministic_failure" };
  }
  return { kind: "hidden" };
}

/**
 * 跑一半改方向 · 忽略路径收口 (run_redirect Step 4): when a run hit a dead end the system can't
 * auto-recover — a「改方向」steer that arrived too late (``run.redirect_ignored``) or a
 * non-retryable failure (``run.deterministic_failure``) — surface it in the run detail and let the
 * user *record* an explicit accept, instead of the old frontend-only「忽略」that left no trace.
 *
 * Read/written entirely on the owner-scoped audit trail (no new SSE event): the two triggers are
 * existing audit rows; the accept appends a ``run.outcome_accepted`` row (via
 * {@link acceptRunOutcome}). Renders nothing unless a trigger is present for this run.
 */
export function RunOutcomeAcceptSection({
  conversationId,
  messageId,
  runId,
}: {
  conversationId: string;
  messageId: string;
  runId: string;
}) {
  const preview = isWebPreview();
  const { data } = useTurnAudit(
    preview ? null : conversationId,
    preview ? null : messageId,
  );
  const [submitting, setSubmitting] = useState(false);
  const [optimisticAccepted, setOptimisticAccepted] = useState(false);

  const state = useMemo((): AcceptState => {
    if (preview || !data) return { kind: "hidden" };
    const forRun = data.data.filter((ev) => ev.run_id === runId);
    return resolveAcceptState(forRun, optimisticAccepted);
  }, [preview, data, runId, optimisticAccepted]);

  if (state.kind === "hidden") return null;

  if (state.kind === "accepted") {
    return (
      <Section title="结果处理">
        <div className="flex items-center gap-2 rounded-lg bg-muted px-3 py-2 text-xs text-muted-foreground">
          <CheckCircle2 size={13} className="shrink-0 text-success" />
          <span>已接受此结果</span>
        </div>
      </Section>
    );
  }

  const copy = COPY[state.reason];
  const onAccept = async () => {
    setSubmitting(true);
    try {
      await acceptRunOutcome(conversationId, {
        messageId,
        runId,
        reason: state.reason,
      });
      setOptimisticAccepted(true);
      invalidateTurnAudit(conversationId, messageId);
      toast.success("已接受此结果");
    } catch {
      toast.error("提交失败，请稍后重试");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Section title="结果处理">
      <div className="space-y-2 rounded-lg border border-warning/30 bg-warning/10 px-3 py-2.5 text-xs">
        <div className="flex items-start gap-2">
          <AlertTriangle size={13} className="mt-0.5 shrink-0 text-warning" />
          <div className="min-w-0 flex-1">
            <p className="font-medium text-foreground">{copy.heading}</p>
            <p className="mt-0.5 text-muted-foreground">{copy.body}</p>
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button
            variant="primary"
            className="h-7"
            disabled={submitting}
            onClick={onAccept}
          >
            接受此结果
          </Button>
        </div>
      </div>
    </Section>
  );
}
