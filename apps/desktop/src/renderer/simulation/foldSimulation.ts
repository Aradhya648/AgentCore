/**
 * Headless ST-02 sim protocol fold — pure event sequence → projected state.
 * No SSE pump, no Zustand side effects. Desktop production UI does not consume this;
 * conformance / unit tests use it as the oracle.
 */
import { activeInteractionFromResult } from "@/simulation/interactionModel";
import { formatSimEventSummary } from "@/simulation/simEventFormat";
import { DEFAULT_WORLD_MODIFIERS } from "@/simulation/worldModifiers";
import type { components } from "@agentcore/contract-rest-types";
import type {
  InteractionResult,
  SSEEvent,
  SimAgentActionPayload,
  SimAgentStatePayload,
  SimInteractionPayload,
  SimTickEndedPayload,
  SimTickFramePayload,
  SimTickStartedPayload,
  SimWorldEventPayload,
  WorldEventWire,
  WorldModifiersWire,
} from "@agentcore/contract-types";

export type SimTickSnapshot = components["schemas"]["SimTickSnapshot"];

export type TickDecisionEntry = {
  tick: number;
  agentId: string;
  summary: string;
  actionType: string;
  location?: string;
};

export type SimStreamEvent = {
  id: string;
  tick: number;
  type: string;
  agentId?: string;
  summary: string;
  timestamp?: string;
  interaction?: InteractionResult;
  worldEvent?: WorldEventWire;
  modifiers?: WorldModifiersWire;
};

export type SimNavTarget = { x: number; y: number; z: number };

/** Platform-neutral projection every ST-02 fold must agree on. */
export type SimProjectedState = {
  run: { tick: number; hour: number };
  navTargets: Record<string, SimNavTarget>;
  decisions: TickDecisionEntry[];
  tickEvents: SimStreamEvent[];
  activeInteractions: Record<
    string,
    ReturnType<typeof activeInteractionFromResult>
  >;
  worldModifiers: WorldModifiersWire;
  tickCache: Record<number, SimTickSnapshot>;
};

const SIM_PREFIX = "sim.";

function isSimEvent(type: string): boolean {
  return type.startsWith(SIM_PREFIX);
}

/** Coerce tick_frame / REST snapshot payload into the fold snapshot shape. */
export function normalizeTickSnapshot(
  tickNumber: number,
  raw: Record<string, unknown>,
): SimTickSnapshot {
  return {
    tick: typeof raw.tick === "number" ? raw.tick : tickNumber,
    hour: typeof raw.hour === "number" ? raw.hour : 0,
    agents: (raw.agents as SimTickSnapshot["agents"]) ?? {},
    event_log: Array.isArray(raw.event_log) ? (raw.event_log as string[]) : [],
    ...(raw.modifiers
      ? { modifiers: raw.modifiers as WorldModifiersWire }
      : {}),
  };
}

export function createInitialSimProjection(
  clock: { tick?: number; hour?: number } = {},
): SimProjectedState {
  return {
    run: { tick: clock.tick ?? 0, hour: clock.hour ?? 8 },
    navTargets: {},
    decisions: [],
    tickEvents: [],
    activeInteractions: {},
    worldModifiers: { ...DEFAULT_WORLD_MODIFIERS },
    tickCache: {},
  };
}

function nextEventId(state: SimProjectedState): string {
  return `sim-ev-${state.tickEvents.length + 1}`;
}

function recordTickEvent(
  state: SimProjectedState,
  event: Pick<SSEEvent, "type" | "payload" | "timestamp">,
): SimProjectedState {
  const tick =
    typeof (event.payload as { tick?: number }).tick === "number"
      ? (event.payload as { tick: number }).tick
      : state.run.tick;
  const { agentId, summary } = formatSimEventSummary(event.type, event.payload);
  const interaction =
    event.type === "sim.interaction"
      ? (event.payload as SimInteractionPayload).interaction
      : undefined;
  const worldEvent =
    event.type === "sim.world_event"
      ? (event.payload as SimWorldEventPayload).event
      : undefined;
  const modifiers =
    event.type === "sim.world_event"
      ? (event.payload as SimWorldEventPayload).modifiers
      : undefined;
  return {
    ...state,
    tickEvents: [
      {
        id: nextEventId(state),
        tick,
        type: event.type,
        agentId,
        summary,
        timestamp: event.timestamp,
        interaction,
        worldEvent,
        modifiers,
      },
      ...state.tickEvents,
    ].slice(0, 400),
  };
}

function applySnapshotNav(
  state: SimProjectedState,
  snapshot: SimTickSnapshot,
): SimProjectedState {
  const navTargets = { ...state.navTargets };
  for (const [agentId, agentState] of Object.entries(snapshot.agents ?? {})) {
    navTargets[agentId] = { ...agentState.position };
  }
  let next: SimProjectedState = {
    ...state,
    navTargets,
    tickCache: { ...state.tickCache, [snapshot.tick]: snapshot },
    run: { tick: snapshot.tick, hour: snapshot.hour },
  };
  if (snapshot.modifiers) {
    next = { ...next, worldModifiers: snapshot.modifiers };
  }
  return next;
}

/**
 * Fold one sim.* event into projected state (immutable).
 * Non-sim events are ignored. `expectedRunId` is reserved for callers that
 * gate on run identity; the pure fold itself does not carry a run id.
 */
export function foldSimulationEvent(
  state: SimProjectedState,
  event: Pick<SSEEvent, "type" | "payload" | "timestamp">,
): SimProjectedState {
  if (!isSimEvent(event.type)) return state;

  const next =
    event.type === "sim.tick_frame" ? state : recordTickEvent(state, event);

  switch (event.type) {
    case "sim.tick_started": {
      const p = event.payload as SimTickStartedPayload;
      return {
        ...next,
        run: { tick: p.tick, hour: p.hour },
      };
    }
    case "sim.tick_ended": {
      const p = event.payload as SimTickEndedPayload;
      return {
        ...next,
        run: { tick: p.tick, hour: p.hour },
      };
    }
    case "sim.tick_frame": {
      const p = event.payload as SimTickFramePayload;
      const snapshot = normalizeTickSnapshot(
        p.tick_number,
        p.snapshot as Record<string, unknown>,
      );
      return applySnapshotNav(next, snapshot);
    }
    case "sim.agent_action": {
      const p = event.payload as SimAgentActionPayload;
      const { action } = p;
      const summary =
        action.thought.trim() ||
        action.detail.trim() ||
        `${action.action}${action.success ? "" : "（失败）"}`;
      const destination =
        typeof action.tool_args?.destination === "string"
          ? action.tool_args.destination
          : undefined;
      return {
        ...next,
        decisions: [
          {
            tick: p.tick,
            agentId: action.agent_id,
            summary,
            actionType: action.action,
            location: destination,
          },
          ...next.decisions,
        ].slice(0, 50),
      };
    }
    case "sim.agent_state": {
      const p = event.payload as SimAgentStatePayload;
      const { state: agentState } = p;
      const navTargets = {
        ...next.navTargets,
        [agentState.agent_id]: { ...agentState.position },
      };
      const decisions = [...next.decisions];
      if (
        decisions[0]?.agentId === agentState.agent_id &&
        decisions[0]?.tick === p.tick
      ) {
        decisions[0] = { ...decisions[0], location: agentState.location };
      }
      return { ...next, navTargets, decisions };
    }
    case "sim.interaction": {
      const p = event.payload as SimInteractionPayload;
      const { interaction } = p;
      const active = activeInteractionFromResult(interaction, p.tick, 0);
      return {
        ...next,
        activeInteractions: {
          ...next.activeInteractions,
          [active.id]: active,
        },
        decisions: [
          {
            tick: p.tick,
            agentId: interaction.initiator_id,
            summary: interaction.summary,
            actionType: interaction.kind,
          },
          ...next.decisions,
        ].slice(0, 50),
      };
    }
    case "sim.world_event": {
      const p = event.payload as SimWorldEventPayload;
      return { ...next, worldModifiers: p.modifiers };
    }
    default:
      return next;
  }
}

/** Fold an event sequence (ST-02 oracle entry point). */
export function foldSimulationEvents(
  events: Array<Pick<SSEEvent, "type" | "payload" | "timestamp">>,
  initial: SimProjectedState = createInitialSimProjection(),
): SimProjectedState {
  return events.reduce(foldSimulationEvent, initial);
}
