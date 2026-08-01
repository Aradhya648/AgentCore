import { RunDetailBody } from "@/components/chat/detail/RunDetailBody";
import { IconButton } from "@/components/ui";
import { SimpleTooltip } from "@/components/ui/tooltip";
import { useStickToBottom } from "@/lib/useStickToBottom";
import { useMessageExecution } from "@/stores/execution";
import { ArrowDown } from "lucide-react";
import { useMemo } from "react";

function chunkChars(chunks: string[]): number {
  let n = 0;
  for (const c of chunks) n += c.length;
  return n;
}

/**
 * Scroll shell for a SidePanel run tab: stick-to-bottom while the worker is
 * live (same semantics as the main chat / IM thread), open finished runs at the
 * top. Lives outside {@link RunDetailBody} so the panel chrome does not subscribe
 * to every streaming token — only this shell + the body do.
 */
export function RunDetailScroll({
  messageId,
  runId,
}: {
  messageId: string;
  runId: string;
}) {
  const execution = useMessageExecution(messageId);
  const run = execution?.runs.find((r) => r.id === runId) ?? null;
  const agent = run
    ? (execution?.agents.find((a) => a.id === run.agentId) ?? null)
    : null;

  const ready = run != null && agent != null;
  const live =
    ready && (agent.status === "working" || run.status === "running");

  const contentKey = useMemo(() => {
    if (!ready) return `${runId}:pending`;
    return [
      runId,
      agent.status,
      run.status,
      chunkChars(agent.outputChunks),
      chunkChars(agent.reasoningChunks),
      agent.toolCalls.length,
      agent.toolProgress?.chars ?? 0,
      run.process.length,
      run.debrief ? 1 : 0,
      run.outputSummary?.length ?? 0,
    ].join("\u0001");
  }, [ready, runId, agent, run]);

  // Only fire reset once the run is projectable — avoids a false "done → top"
  // flash before execution lands, then a second reset when data arrives.
  const resetKey = ready ? `${messageId}:${runId}` : null;

  const { scrollRef, atBottom, jumpToBottom } = useStickToBottom(
    contentKey,
    resetKey,
    { followOnReset: live },
  );

  return (
    <div className="absolute inset-0">
      <div ref={scrollRef} className="h-full overflow-y-auto">
        <RunDetailBody
          key={`${messageId}:${runId}`}
          messageId={messageId}
          runId={runId}
        />
      </div>
      {!atBottom && (
        <SimpleTooltip label="回到底部">
          <IconButton
            size="md"
            onClick={jumpToBottom}
            aria-label="回到底部"
            className="absolute bottom-3 left-1/2 -translate-x-1/2 rounded-full border border-border bg-card text-muted-foreground shadow-md hover:text-foreground"
          >
            <ArrowDown size={16} />
          </IconButton>
        </SimpleTooltip>
      )}
    </div>
  );
}
