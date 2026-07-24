import { NODE_HEIGHT } from "@/lib/graphMetrics";
import { describe, expect, it } from "vitest";
import { FACE_CARD_MAX_HEIGHT } from "../shared";

describe("AgentNodeFace · overflow soft cap", () => {
  it("FACE_CARD_MAX_HEIGHT is above cold NODE_HEIGHT so normal cards show full", () => {
    expect(FACE_CARD_MAX_HEIGHT).toBeGreaterThan(NODE_HEIGHT);
  });
});
