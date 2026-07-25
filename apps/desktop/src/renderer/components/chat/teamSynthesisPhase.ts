import type { Execution, RunStatus } from "@/stores/execution";
import type {
  CoordinationWaitPayload,
  TeamSynthesisPreviewPayload,
} from "@/types/events";

/** Worker runs only (CEO captain sink is not a delegate progress unit). */
export function workerProgress(execution: Execution): {
  completed: number;
  total: number;
} {
  const workers = execution.runs.filter((r) => r.kind !== "captain");
  return {
    completed: workers.filter((r) => r.status === "completed").length,
    total: workers.length,
  };
}

/** Roles still outstanding while CEO is in ``coordination_wait``. */
export function waitingWorkerRoles(execution: Execution): string[] {
  return coordinationWaitWorkerRows(execution)
    .filter((w) => w.status !== "completed")
    .map((w) => w.role);
}

export type CoordinationWaitWorkerRow = {
  runId: string;
  role: string;
  status: RunStatus;
  summary: string;
  /** 证人席位根：pending 显示「待命」，skipped 显示「未传唤」。 */
  witnessSeat?: boolean;
};

/** All non-captain workers with display role + live run status. */
export function coordinationWaitWorkerRows(
  execution: Execution,
): CoordinationWaitWorkerRow[] {
  return execution.runs
    .filter((r) => r.kind !== "captain")
    .map((r) => ({
      runId: r.id,
      role:
        execution.agents.find((a) => a.id === r.agentId)?.role ??
        r.role ??
        r.id,
      status: r.status,
      summary: (r.outputSummary ?? "").trim(),
      witnessSeat: r.group === "debate:witness" && r.continuesRunId == null,
    }));
}

function formatWaitElapsed(elapsedSec: number | undefined): string {
  if (elapsedSec === undefined || elapsedSec < 1) return "";
  return ` · 已等 ${elapsedSec}s`;
}

/**
 * Live ``coordination_wait`` copy for StatusStrip / StreamingIndicator (long form).
 * Global only — member names stay on graph worker nodes / captain short caption.
 * ``waitingRoles`` kept in opts for call-site compat; Strip no longer embeds them.
 */
export function coordinationWaitLabel(
  wait: Pick<CoordinationWaitPayload, "completed" | "total"> | null | undefined,
  opts?: {
    elapsedSec?: number;
    /** @deprecated Strip uses global copy only; ignored. */
    waitingRoles?: string[];
  },
): string | null {
  if (!wait) return null;
  const total = Math.max(0, wait.total);
  const completed = Math.max(
    0,
    Math.min(wait.completed, total || wait.completed),
  );
  const elapsed = formatWaitElapsed(opts?.elapsedSec);
  return `等待团队成员完成 (${completed}/${total})${elapsed}…`;
}

/** Short captain-node caption (space-constrained). */
export function coordinationWaitCaptainCaption(
  wait: Pick<CoordinationWaitPayload, "completed" | "total"> | null | undefined,
  opts?: {
    elapsedSec?: number;
    waitingRoles?: string[];
  },
): string | null {
  if (!wait) return null;
  const total = Math.max(0, wait.total);
  const completed = Math.max(
    0,
    Math.min(wait.completed, total || wait.completed),
  );
  const elapsed = formatWaitElapsed(opts?.elapsedSec);
  const roles = (opts?.waitingRoles ?? []).filter(Boolean);
  if (roles.length === 1) {
    return `等待「${roles[0]}」(${completed}/${total})${elapsed}`;
  }
  return `等待团队 (${completed}/${total})${elapsed}`;
}

/**
 * All workers finished while the turn is still running — CEO synthesis /
 * proposal_pick gap. Matches {@link deriveCaptainStatus}'s "running" sink.
 */
export function isTeamSynthesizing(execution: Execution): boolean {
  if (execution.status !== "running") return false;
  const { completed, total } = workerProgress(execution);
  return total > 0 && completed >= total;
}

/** Deterministic strip / indicator copy for the synthesis empty window. */
export function teamSynthesisPhaseLabel(execution: Execution): string {
  const { completed, total } = workerProgress(execution);
  return `${completed}/${total} 已完成，正在生成汇总`;
}

/**
 * Short preview for the CEO graph node while final answer is not yet streaming
 * into the bubble (synthesis uses `team_synthesis_preview`, not content_delta).
 */
export function captainSynthesisPreviewText(
  preview: TeamSynthesisPreviewPayload | null | undefined,
): string {
  if (!preview) return "";
  const text = preview.text.trim();
  const headline = preview.headline.trim();
  if (text && text !== headline) return text;
  if (headline) return headline;
  const blurbs = preview.workers
    .filter((w) => w.status !== "pending" && w.summary)
    .map((w) => `${w.role}：${w.summary}`);
  return blurbs.join(" · ");
}
