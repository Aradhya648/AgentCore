/**
 * V5 —— 现生产通用澄清卡（{@link AskDecisionBody}）。
 * 原「开工提案」行式壳已退役；本变体对照现产品主路径（提交/停止在预览里是空操作）。
 */
import type { CheckpointUserDecision } from "@/services/checkpoint";
import { useState } from "react";
import { AskDecisionBody } from "../AskDecisionBody";
import type { AskUserContent } from "../AskUserFields";
import { useAskAnswer } from "../AskUserFields";
import { PreviewShell } from "./AskCommenceShared";

export function AskCommenceV5({ content }: { content: AskUserContent }) {
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
      data-variant="ask-commence-v5"
      className="max-h-[min(50vh,28rem)]"
    >
      <AskDecisionBody
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
