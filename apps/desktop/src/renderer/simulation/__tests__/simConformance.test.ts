import {
  createInitialSimProjection,
  foldSimulationEvents,
} from "@/simulation/foldSimulation";
import type { SSEEvent, WorldModifiersWire } from "@agentcore/contract-types";
import m1Tick from "@agentcore/protocol-conformance/fixtures/simulation-m1-tick.json" with {
  type: "json",
};
import coordinateTransform from "@agentcore/protocol-conformance/fixtures/simulation/coordinate-transform.json" with {
  type: "json",
};
import interactionConversation from "@agentcore/protocol-conformance/fixtures/simulation/interaction-conversation.json" with {
  type: "json",
};
import multiAgentTick from "@agentcore/protocol-conformance/fixtures/simulation/multi-agent-tick.json" with {
  type: "json",
};
import tickFrameSnapshot from "@agentcore/protocol-conformance/fixtures/simulation/tick-frame-snapshot.json" with {
  type: "json",
};
import worldEvent from "@agentcore/protocol-conformance/fixtures/simulation/world-event.json" with {
  type: "json",
};
import { describe, expect, it } from "vitest";

/** The platform-neutral sim projection every end's fold must agree on: the run clock,
 * per-agent nav targets, the decision feed (newest first), and — when the vector exercises
 * them — world modifiers and active interactions. */
type SimFoldFixture = {
  name: string;
  description?: string;
  events: SSEEvent[];
  projected: {
    run: { tick: number; hour: number };
    navTargets: Record<string, { x: number; y: number; z: number }>;
    decisions: Array<{
      tick: number;
      agentId: string;
      actionType: string;
      location?: string;
      summary?: string;
    }>;
    worldModifiers?: WorldModifiersWire;
    activeInteractions?: Array<{
      id: string;
      kind: string;
      status: string;
      initiatorId: string;
      targetId?: string | null;
    }>;
  };
};

const FIXTURES: SimFoldFixture[] = [
  m1Tick as unknown as SimFoldFixture,
  multiAgentTick as unknown as SimFoldFixture,
  coordinateTransform as unknown as SimFoldFixture,
  interactionConversation as unknown as SimFoldFixture,
  worldEvent as unknown as SimFoldFixture,
  tickFrameSnapshot as unknown as SimFoldFixture,
];

describe("simulation ST-02 conformance · SSE fold", () => {
  for (const fx of FIXTURES) {
    it(`${fx.name}: dispatch fold matches golden`, () => {
      const projected = foldSimulationEvents(
        fx.events,
        createInitialSimProjection(),
      );

      expect(projected.run.tick).toBe(fx.projected.run.tick);
      expect(projected.run.hour).toBe(fx.projected.run.hour);
      expect(projected.navTargets).toEqual(fx.projected.navTargets);

      expect(projected.decisions).toHaveLength(fx.projected.decisions.length);
      fx.projected.decisions.forEach((decision, index) => {
        expect(projected.decisions[index]).toMatchObject(decision);
      });

      if (fx.projected.worldModifiers) {
        expect(projected.worldModifiers).toEqual(fx.projected.worldModifiers);
      }

      if (fx.projected.activeInteractions) {
        for (const ai of fx.projected.activeInteractions) {
          expect(projected.activeInteractions[ai.id]).toMatchObject({
            kind: ai.kind,
            status: ai.status,
            initiatorId: ai.initiatorId,
            targetId: ai.targetId,
          });
        }
      }
    });
  }
});
