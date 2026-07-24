import { FinaleStage } from "@/components/chat/debate/arena/FinaleStage";
import {
  DEMO_DEBATE_EXECUTION,
  DEMO_DEBATE_MESSAGE_ID,
  DEMO_DEBATE_MODEL,
} from "./demoDebate";

/**
 * 手册「真组件预览」：辩论室终审舞台。
 * 复用 {@link FinaleStage} + 手造简报 / Execution；侧栏钻取在手册页无害（点开会写 sidePanel store）。
 */
export function ManualDebateFinalePreview() {
  return (
    <div className="w-full max-w-3xl overflow-hidden rounded-xl border border-border bg-card px-3 pb-4">
      <FinaleStage
        model={DEMO_DEBATE_MODEL}
        execution={DEMO_DEBATE_EXECUTION}
        messageId={DEMO_DEBATE_MESSAGE_ID}
      />
    </div>
  );
}
