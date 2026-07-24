import {
  captainSynthesisPreviewText,
  isTeamSynthesizing,
  teamSynthesisPhaseLabel,
} from "@/components/chat/teamSynthesisPhase";
import { Badge } from "@/components/ui";
import { type Execution, useActiveExecField } from "@/stores/execution";
import { Loader2 } from "lucide-react";

/**
 * CEO 协调模式：多 worker 团队进展卡片（transport-only，不走 content_delta / CEO 气泡）。
 *
 * 产品语义（2026-07 拍板）：以【系统自动进度】为主、CEO 里程碑总结为辅——
 * - 协调等待（``coordination_wait``）：一行等待摘要归状态条标题行、成员级细节归协作图节点，
 *   本行在等待期不渲染（避免与标题 / 图重复）。
 * - 进展主体用确定性 run 完成态派生的每员摘要（权威来源），非 CEO 逐条手写。
 * - CEO 的 ``update_synthesis`` 里程碑草稿降为「CEO 小结」辅助块，挂在系统进度之下。
 * - 汇总空窗（工人全完成、终稿/方案卡未到）即使无新 preview 事件，也渲染确定性
 *   「N/N 已完成，正在生成汇总」+ 活性指示。
 */
export function TeamSynthesisPreviewLine({
  execution,
}: {
  execution: Execution;
}) {
  const preview = useActiveExecField((rt) => rt.teamSynthesisPreview);
  const wait = useActiveExecField((rt) => rt.coordinationWait);

  // 协调等待期：一行等待摘要由状态条标题行承载、成员级细节由协作图节点承担，
  // 本行不再内联渲染（避免与标题 / 图重复）。
  if (wait) return null;

  const synthesizing = isTeamSynthesizing(execution);
  if (!preview && !synthesizing) return null;

  // 系统自动进度为主：优先用确定性 run 完成态派生每员摘要（权威来源，覆盖「已 2/2 只见
  // 1 人摘要」的空窗），仅当尚无 run 摘要时回落 CEO preview.workers。
  const runBlurbs = execution.runs
    .filter(
      (r) =>
        r.kind !== "captain" && r.status === "completed" && !!r.outputSummary,
    )
    .map((r) => ({
      run_id: r.id,
      role: execution.agents.find((a) => a.id === r.agentId)?.role ?? r.id,
      summary: r.outputSummary as string,
    }));
  const previewWorkers =
    preview?.workers.filter((w) => w.status !== "pending" && w.summary) ?? [];
  const blurbs = runBlurbs.length > 0 ? runBlurbs : previewWorkers;
  const phaseLabel = synthesizing ? teamSynthesisPhaseLabel(execution) : "";
  const headline = synthesizing ? phaseLabel : (preview?.headline ?? "");
  const badge = synthesizing
    ? "生成汇总"
    : preview?.in_progress
      ? "进展中"
      : "团队进展";

  // CEO 里程碑总结为辅：update_synthesis 的自由文草稿（workers=[]）挂在系统进度【之下】。
  // 系统进度预览通道（workers 有值）的 text 是确定性进度行、非草稿，故不重复展示。
  let ceoNote: string | null = null;
  if (preview && previewWorkers.length === 0 && !synthesizing) {
    const text = preview.text.trim();
    const h = preview.headline.trim();
    if (text && text !== h && text !== phaseLabel) ceoNote = text;
  } else if (preview && synthesizing) {
    // 空窗期：在确定性标题下再挂一截已有草稿（若有且不同于 headline / blurbs）。
    const hint = captainSynthesisPreviewText(preview);
    if (
      hint &&
      hint !== phaseLabel &&
      hint !== preview.headline.trim() &&
      !blurbs.some((w) => hint.includes(w.summary))
    ) {
      ceoNote = hint;
    }
  }

  return (
    <div
      className={`mt-2 rounded-lg px-3 py-2 text-xs text-muted-foreground ${
        synthesizing ? "border border-primary/25 bg-primary/5" : "bg-muted/60"
      }`}
      data-testid="team-synthesis-preview"
      data-synthesizing={synthesizing ? "true" : "false"}
    >
      <div className="flex items-center gap-2">
        {synthesizing ? (
          <Loader2
            size={13}
            className="shrink-0 animate-spin text-primary motion-reduce:animate-none"
            aria-hidden
          />
        ) : null}
        <Badge tone="primary" pill className="font-medium">
          {badge}
        </Badge>
        <span
          className={`min-w-0 flex-1 truncate font-medium ${
            synthesizing ? "text-primary" : "text-foreground"
          }`}
          data-testid="team-synthesis-headline"
        >
          {headline}
        </span>
        {synthesizing ? (
          <span
            className="size-1.5 shrink-0 animate-pulse rounded-full bg-primary motion-reduce:animate-none"
            aria-hidden
            data-testid="team-synthesis-pulse"
          />
        ) : null}
      </div>
      {blurbs.length > 0 && (
        <ul className="mt-1.5 space-y-0.5 pl-0.5">
          {blurbs.map((w) => (
            <li key={w.run_id} className="truncate">
              · {w.role}：{w.summary}
            </li>
          ))}
        </ul>
      )}
      {ceoNote && (
        <div className="mt-1.5" data-testid="team-synthesis-ceo-note">
          <span className="text-muted-foreground/70">CEO 小结</span>
          <p
            className="mt-0.5 line-clamp-3 whitespace-pre-wrap text-foreground/80"
            data-testid="team-synthesis-draft"
          >
            {ceoNote}
          </p>
        </div>
      )}
    </div>
  );
}
