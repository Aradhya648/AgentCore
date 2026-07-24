import type {
  SimAgentActionPayload,
  SimAgentStatePayload,
  SimInteractionPayload,
  SimTickEndedPayload,
  SimTickStartedPayload,
  SimWorldEventPayload,
} from "@agentcore/contract-types";

export function formatSimEventSummary(
  type: string,
  payload: unknown,
): { agentId?: string; summary: string } {
  switch (type) {
    case "sim.tick_started": {
      const p = payload as SimTickStartedPayload;
      return { summary: `Tick ${p.tick} 开始 · ${p.hour}:00` };
    }
    case "sim.tick_ended": {
      const p = payload as SimTickEndedPayload;
      return {
        summary: `Tick ${p.tick} 结束 · ${p.agent_count} 位居民`,
      };
    }
    case "sim.agent_action": {
      const p = payload as SimAgentActionPayload;
      const { action } = p;
      const text =
        action.thought.trim() ||
        action.detail.trim() ||
        `${action.action}${action.success ? "" : "（失败）"}`;
      return {
        agentId: action.agent_id,
        summary: `${action.action}: ${text}`,
      };
    }
    case "sim.agent_state": {
      const p = payload as SimAgentStatePayload;
      const { state } = p;
      return {
        agentId: state.agent_id,
        summary: `${state.name} @ ${state.location} · ${state.activity}`,
      };
    }
    case "sim.interaction": {
      const p = payload as SimInteractionPayload;
      const { interaction } = p;
      return {
        agentId: interaction.initiator_id,
        summary: `[${interaction.kind}] ${interaction.summary}`,
      };
    }
    case "sim.world_event": {
      const p = payload as SimWorldEventPayload;
      const { event } = p;
      const summary =
        event.title.trim() || event.description.trim() || event.event_type;
      return { summary };
    }
    default:
      return { summary: type };
  }
}
