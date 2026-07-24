import { describe, expect, it } from "vitest";
import { graphStructureKey } from "../useGraphLayout";

describe("graphStructureKey", () => {
  it("ignores streaming-only fields (structural fingerprint only)", () => {
    const a = graphStructureKey([
      { id: "w1", dependsOn: [], parentRunId: null, replacesRunId: null },
    ]);
    const b = graphStructureKey([
      { id: "w1", dependsOn: [], parentRunId: null, replacesRunId: null },
    ]);
    expect(a).toBe(b);
  });

  it("changes when a run is appended (追加委派)", () => {
    const before = graphStructureKey([
      { id: "w1", dependsOn: [], parentRunId: null },
    ]);
    const after = graphStructureKey([
      { id: "w1", dependsOn: [], parentRunId: null },
      { id: "w2", dependsOn: [], parentRunId: null },
    ]);
    expect(before).not.toBe(after);
  });

  it("changes when replacesRunId appears (补派接手)", () => {
    const before = graphStructureKey([
      { id: "w1", dependsOn: [], replacesRunId: null },
      { id: "w1b", dependsOn: [], replacesRunId: null },
    ]);
    const after = graphStructureKey([
      { id: "w1", dependsOn: [], replacesRunId: null },
      { id: "w1b", dependsOn: [], replacesRunId: "w1" },
    ]);
    expect(before).not.toBe(after);
  });

  it("changes when dependsOn is rewritten to the replacement", () => {
    const before = graphStructureKey([
      { id: "w1b", dependsOn: [], replacesRunId: "w1" },
      { id: "w2", dependsOn: ["w1"] },
    ]);
    const after = graphStructureKey([
      { id: "w1b", dependsOn: [], replacesRunId: "w1" },
      { id: "w2", dependsOn: ["w1b"] },
    ]);
    expect(before).not.toBe(after);
  });
});
