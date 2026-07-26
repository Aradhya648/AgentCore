/**
 * V5 Row List —— 单页全览 + 行式选项。挂载的就是生产候选 {@link AskKickoffBody}，
 * 所以这一屏看到的即上线后的样子（提交/停止在预览里是空操作）。
 */
import type { CheckpointUserDecision } from "@/services/checkpoint";
import { useState } from "react";
import { AskKickoffBody } from "../AskKickoffBody";
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
      className="max-h-[min(70vh,44rem)]"
    >
      <AskKickoffBody
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
