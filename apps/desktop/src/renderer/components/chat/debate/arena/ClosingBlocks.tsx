import { Markdown } from "@/components/chat/Markdown";
import { Button } from "@/components/ui";
import type { Execution } from "@/stores/execution";
import { useSidePanelStore } from "@/stores/sidePanel";
import { TriangleAlert } from "lucide-react";
import { CollapsibleSpeech } from "../CollapsibleSpeech";
import type { DebateClosingView } from "../model";
import { SectionHeader } from "./SectionHeader";
import { closingAnchorId } from "./anchors";
import {
  DEBATE_SPLIT_GRID,
  type DebateArenaLayout,
  partitionSides,
} from "./debateLayoutPreference";

export function ClosingBlocks({
  closings,
  execution,
  messageId,
  layoutMode = "stack",
}: {
  closings: DebateClosingView[];
  execution: Execution;
  messageId: string;
  layoutMode?: DebateArenaLayout;
}) {
  return (
    <div>
      <SectionHeader id={closingAnchorId()} label="结辩" />
      {layoutMode === "split" ? (
        <SplitClosingColumns
          closings={closings}
          execution={execution}
          messageId={messageId}
        />
      ) : (
        <div className="space-y-4">
          {closings.map((c) => (
            <ClosingBlock
              key={c.sideKey}
              closing={c}
              execution={execution}
              messageId={messageId}
            />
          ))}
        </div>
      )}
    </div>
  );
}

/** split 布局：正反两方结辩左右对开（对齐立论 / 质询的列布局），其余方顺次堆叠。 */
function SplitClosingColumns({
  closings,
  execution,
  messageId,
}: {
  closings: DebateClosingView[];
  execution: Execution;
  messageId: string;
}) {
  const { pro, con, others } = partitionSides(
    closings,
    (c) => c.sideKey,
    (c) => c.stance,
  );

  return (
    <div className="space-y-4">
      <div className={DEBATE_SPLIT_GRID}>
        <div className="min-w-0">
          {pro && (
            <ClosingBlock
              closing={pro}
              execution={execution}
              messageId={messageId}
            />
          )}
        </div>
        <div className="min-w-0">
          {con && (
            <ClosingBlock
              closing={con}
              execution={execution}
              messageId={messageId}
            />
          )}
        </div>
      </div>
      {others.map((c) => (
        <ClosingBlock
          key={c.sideKey}
          closing={c}
          execution={execution}
          messageId={messageId}
        />
      ))}
    </div>
  );
}

function ClosingBlock({
  closing,
  execution,
  messageId,
}: {
  closing: DebateClosingView;
  execution: Execution;
  messageId: string;
}) {
  const showRunDetail = useSidePanelStore((s) => s.showRunDetail);
  const run = closing.run;
  const agent = run
    ? execution.agents.find((a) => a.id === run.agentId)
    : undefined;
  const text = agent ? agent.outputChunks.join("") : "";

  const meta = (
    <>
      <span className="font-medium" style={{ color: closing.colorVar }}>
        {closing.name}
      </span>
      <span className="text-muted-foreground">· 结辩</span>
      {!closing.ok && (
        <span className="inline-flex items-center gap-0.5 text-destructive">
          <TriangleAlert size={11} />
          未产出
        </span>
      )}
    </>
  );

  return (
    <div
      className="border-l-[3px] pl-3"
      style={{ borderLeftColor: closing.colorVar }}
    >
      <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5 text-xs">
        {run ? (
          // 对齐 SpeakerBlock / CrossExamSideBlock：名字行即钻取入口（有 run 即可点）。
          <Button
            variant="ghost"
            onClick={() =>
              showRunDetail(messageId, run.id, `${closing.name} · 结辩`)
            }
            className="h-auto justify-start gap-2 rounded-none px-0 py-0 text-xs hover:bg-transparent"
          >
            {meta}
          </Button>
        ) : (
          <span className="flex items-center gap-2">{meta}</span>
        )}
      </div>
      <div className="mt-1 pb-4 text-sm text-foreground">
        {text ? (
          <CollapsibleSpeech
            contentKey={text}
            sceneKey={`${messageId}:aclosing:${closing.sideKey}`}
          >
            <Markdown content={text} evidence />
          </CollapsibleSpeech>
        ) : (
          <p className="text-xs text-muted-foreground">
            {closing.ok ? "等待结辩…" : "未产出结辩。"}
          </p>
        )}
      </div>
    </div>
  );
}
