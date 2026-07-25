import {
  isTeamSynthesizing,
  teamSynthesisPhaseLabel,
} from "@/components/chat/teamSynthesisPhase";
import { useCoordinationWaitChrome } from "@/components/chat/useCoordinationWaitChrome";
import { useActiveGenerating, useActiveMessages } from "@/stores/conversation";
import { useMessageExecution } from "@/stores/execution";

export function StreamingIndicator() {
  const isGenerating = useActiveGenerating();
  const messages = useActiveMessages();
  const last = messages[messages.length - 1];
  const isStreaming = last?.role === "assistant" && last.isStreaming;
  const executionId = isStreaming ? last.executionId : null;
  const messageId = isStreaming ? last.id : null;
  const execution = useMessageExecution(messageId);
  const { waitLabel } = useCoordinationWaitChrome(execution, messageId);

  if (!isGenerating || !isStreaming) return null;

  let text = "Replying…";
  if (execution && execution.status === "running") {
    const hasInlineGraph = execution.planType !== "single_agent";
    // 有 InlineTeamGraph/StatusStrip 时等待态已由顶栏承载，底部不再复述同一 waitLabel；
    // 无图场景（单 Agent）仍可用 waitLabel 作唯一心跳。
    if (waitLabel && !hasInlineGraph) {
      text = waitLabel;
    } else if (isTeamSynthesizing(execution)) {
      text = teamSynthesisPhaseLabel(execution);
    } else if (executionId) {
      const runningRun = execution.runs.find((r) => r.status === "running");
      const role = runningRun
        ? execution.agents.find((a) => a.id === runningRun.agentId)?.role
        : null;
      // 团队/辩论回合的内嵌协作图卡片已承载辩题与逐 Agent 状态，底部条只留
      // 「谁在动」的心跳、不再复述辩题（避免与画布三重复述同一句）。单 Agent
      // 回复无画布，这条是唯一「还活着」信号，仍保留完整任务摘要。
      if (hasInlineGraph) {
        text = role
          ? `${role} 正在工作`
          : execution.planType === "debate"
            ? "辩论进行中"
            : "团队协作进行中";
      } else {
        text = role
          ? `${execution.taskSummary} · ${role} 正在工作`
          : execution.taskSummary;
      }
    }
  }

  return (
    <div className="flex items-center gap-2 px-4 py-1.5">
      <span className="size-1.5 shrink-0 animate-pulse rounded-full bg-primary motion-reduce:animate-none" />
      <span className="truncate text-xs text-muted-foreground">{text}</span>
    </div>
  );
}
