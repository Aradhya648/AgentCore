import { api } from "@/services/api";
import { getActiveSidecarTarget } from "@/services/sidecarRouting";

/**
 * Ambient debate steer — fire-and-forget boss intervention.
 * Applied at the next round boundary (辩论永不硬停).
 */
export type DebateSteerDecision =
  | { kind: "continue"; focus: string; ask: string; askTarget: string }
  | { kind: "conclude"; ask: string; askTarget: string };

export interface SubmitDebateSteerParams {
  executionId: string;
  decision: DebateSteerDecision;
}

/**
 * Queue an ambient steer for the live debate.
 *
 * Local turns route to the sidecar (in-process queue); cloud turns POST the
 * HTTP endpoint. Never blocks the Moderator — echo「已发送·下一轮生效」client-side.
 */
export async function submitDebateSteer(
  conversationId: string,
  params: SubmitDebateSteerParams,
): Promise<void> {
  const decision = params.decision.kind;
  const focus =
    params.decision.kind === "continue" ? params.decision.focus : "";
  const ask = params.decision.ask;
  const askTarget = params.decision.askTarget;

  const sidecarTarget = getActiveSidecarTarget(conversationId);
  if (sidecarTarget) {
    await window.sidecarApi.debateSteer({
      rootId: sidecarTarget.rootId,
      subpath: sidecarTarget.subpath,
      conversationId,
      executionId: params.executionId,
      decision,
      focus,
      ask,
      askTarget,
    });
    return;
  }
  await api.post(`/v1/conversations/${conversationId}/debate-steer`, {
    execution_id: params.executionId,
    decision,
    focus,
    ask,
    ask_target: askTarget,
  });
}
