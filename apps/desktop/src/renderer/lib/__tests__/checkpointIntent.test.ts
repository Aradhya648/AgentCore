import { describe, expect, it } from "vitest";
import { parseCheckpointIntent } from "../checkpointIntent";

describe("parseCheckpointIntent", () => {
  it("preserves known intents", () => {
    expect(parseCheckpointIntent("kickoff")).toBe("kickoff");
    expect(parseCheckpointIntent("decision")).toBe("decision");
    expect(parseCheckpointIntent("proposal_pick")).toBe("proposal_pick");
    expect(parseCheckpointIntent("risk_ack")).toBe("risk_ack");
    expect(parseCheckpointIntent("organize_plan")).toBe("organize_plan");
  });

  it("defaults unknown / missing to decision", () => {
    expect(parseCheckpointIntent(undefined)).toBe("decision");
    expect(parseCheckpointIntent(null)).toBe("decision");
    expect(parseCheckpointIntent("other")).toBe("decision");
  });
});
