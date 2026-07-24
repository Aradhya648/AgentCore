/**
 * V2 Brief + Choose — mirrors production kickoff ({@link AskCommenceKickoffBody}).
 * Preview-only shell; submit/stop are no-ops for eyeballing.
 */
import type { CheckpointUserDecision } from "@/services/checkpoint";
import { useState } from "react";
import { AskCommenceKickoffBody } from "../AskCommenceKickoff";
import type { AskUserContent } from "../AskUserFields";
import { useAskAnswer } from "../AskUserFields";
import { PreviewShell } from "./AskCommenceShared";

export function AskCommenceV2({ content }: { content: AskUserContent }) {
  const answer = useAskAnswer(content);
  const [submitting, setSubmitting] = useState<CheckpointUserDecision | null>(
    null,
  );
  const busy = submitting !== null;
  const noop = (decision: CheckpointUserDecision) => {
    setSubmitting(decision);
    window.setTimeout(() => setSubmitting(null), 600);
  };

  return (
    <PreviewShell
      data-variant="ask-commence-v2"
      className="max-h-[min(60vh,36rem)]"
    >
      <AskCommenceKickoffBody
        content={content}
        answer={answer}
        busy={busy}
        submitting={submitting}
        onContinue={() => noop("continue")}
        onStop={() => noop("stop")}
      />
    </PreviewShell>
  );
}
