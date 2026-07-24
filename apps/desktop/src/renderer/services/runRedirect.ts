import { api } from "@/services/api";
import { getActiveSidecarTarget } from "@/services/sidecarRouting";

export interface SubmitRunRedirectParams {
  executionId: string;
  runId: string;
  feedback: string;
}

/**
 * Queue a mid-flight redirect for one worker (中间可见性 Phase 2a).
 *
 * Local turns route to the sidecar process (the cloud HTTP POST cannot reach the
 * in-process queue). Step 2 will drain this queue to cancel + re-run the worker.
 */
export async function submitRunRedirect(
  conversationId: string,
  params: SubmitRunRedirectParams,
): Promise<void> {
  const sidecarTarget = getActiveSidecarTarget(conversationId);
  if (sidecarTarget) {
    await window.sidecarApi.runRedirect({
      rootId: sidecarTarget.rootId,
      subpath: sidecarTarget.subpath,
      conversationId,
      executionId: params.executionId,
      runId: params.runId,
      feedback: params.feedback,
    });
    return;
  }
  await api.post(`/v1/conversations/${conversationId}/run-redirect`, {
    execution_id: params.executionId,
    run_id: params.runId,
    feedback: params.feedback,
  });
}

/** Why a run reached a terminal dead end the user is asked to accept (跑一半改方向 Step 4):
 *  a non-retryable failure, or a「立即改此人」steer that arrived too late to apply mid-run. */
export type RunOutcomeReason =
  | "deterministic_failure"
  | "redirect_ignored"
  | "recovery_ignored";

export interface AcceptRunOutcomeParams {
  /** The assistant message (turn) the run belongs to — scopes the audit trail. */
  messageId: string;
  runId: string;
  reason: RunOutcomeReason;
  executionId?: string;
  note?: string;
}

/**
 * Record the user's explicit accept of a run's terminal outcome (跑一半改方向 Step 4 · 忽略路径收口).
 *
 * Replaces the old frontend-only「忽略」(clearExecution) with a durable「用户主动接受此结果」row on
 * the SAME owner-scoped audit trail the run detail reads — so the acceptance survives reload and is
 * auditable. Cloud-only (like the audit read): the record lives with the turn's other audit rows.
 * Idempotent server-side; returns `recorded=false` if this run's outcome was already accepted.
 */
export async function acceptRunOutcome(
  conversationId: string,
  params: AcceptRunOutcomeParams,
): Promise<{ recorded: boolean }> {
  return api.post<{ ok: boolean; recorded: boolean; action: string }>(
    `/v1/conversations/${conversationId}/messages/${params.messageId}/accept-outcome`,
    {
      run_id: params.runId,
      reason: params.reason,
      execution_id: params.executionId,
      note: params.note,
    },
  );
}
