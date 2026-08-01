import { CollapsibleBody } from "@/components/conversation-replay/shared";
import { InlineTeamGraph } from "@/components/conversation-replay/InlineTeamGraph";
import {
  LlmProcessRow,
  ToolLine,
} from "@/components/conversation-replay/ToolLine";
import type {
  ReplayMessage,
  ReplayRun,
} from "@/services/adminObservability";
import { ChevronDown, ChevronRight } from "lucide-react";
import { useMemo, useState } from "react";

function runLabelMap(runs: ReplayRun[]): Map<string, string> {
  const map = new Map<string, string>();
  for (const r of runs) {
    map.set(r.run_id, r.role || r.agent_id);
  }
  return map;
}

/**
 * Read-only process timeline: model/tool rows → inline team graph → final body.
 * No streaming, no interactive approval/debate cards. Worker prose stays in the dock.
 */
export function ProcessTimeline({
  message,
  selectedRunId,
  onSelectRun,
}: {
  message: ReplayMessage;
  selectedRunId: string | null;
  onSelectRun: (runId: string) => void;
}) {
  const tools = useMemo(
    () => message.spans.filter((s) => s.kind === "tool"),
    [message.spans],
  );
  const llms = useMemo(
    () => message.spans.filter((s) => s.kind !== "tool"),
    [message.spans],
  );
  const labels = useMemo(() => runLabelMap(message.runs), [message.runs]);
  const hasProcess = tools.length > 0 || llms.length > 0;
  const multi = message.runs.length > 0;
  const [processOpen, setProcessOpen] = useState(false);

  const processSummary = formatProcessSummary(llms.length, tools.length);

  return (
    <div className="space-y-2.5">
      {hasProcess && (
        <div>
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              setProcessOpen((v) => !v);
            }}
            className="inline-flex items-center gap-1.5 text-sm text-muted-foreground outline-none hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring rounded"
          >
            <span>{processSummary}</span>
            {processOpen ? (
              <ChevronDown size={14} className="shrink-0" />
            ) : (
              <ChevronRight size={14} className="shrink-0" />
            )}
          </button>
          {processOpen && (
            <div className="mt-2 space-y-1.5">
              {message.spans.map((span, i) =>
                span.kind === "tool" ? (
                  <ToolLine
                    key={`tool-${i}`}
                    span={span}
                    runLabel={
                      multi && span.run_id
                        ? (labels.get(span.run_id) ?? null)
                        : null
                    }
                  />
                ) : (
                  <LlmProcessRow key={`llm-${i}`} span={span} />
                ),
              )}
            </div>
          )}
        </div>
      )}

      {multi && (
        <InlineTeamGraph
          runs={message.runs}
          selectedRunId={selectedRunId}
          onSelectRun={onSelectRun}
        />
      )}

      {message.content ? (
        <div className="text-sm leading-relaxed">
          <CollapsibleBody content={message.content} />
        </div>
      ) : !hasProcess && !multi ? (
        <div className="text-muted-foreground text-sm italic">（无正文）</div>
      ) : null}
    </div>
  );
}

function formatProcessSummary(llmCount: number, toolCount: number): string {
  const parts: string[] = [];
  if (llmCount > 0) parts.push(`${llmCount} 次模型调用`);
  if (toolCount > 0) parts.push(`${toolCount} 次工具`);
  return parts.join(" · ") || "过程";
}
