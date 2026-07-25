/**
 * Desktop INTERACTION_REGISTRY ⊇ wire UserInteractionKind exhaustiveness.
 *
 * Adding a wire kind without a registry row = silent missing card. Compile-time
 * Record typing does not fail the build when a kind is omitted from the array.
 */
import {
  INTERACTION_KIND_WIRE,
  USER_INTERACTION_KIND_VALUES,
} from "@agentcore/contract-types";
import { describe, expect, it } from "vitest";
import { INTERACTION_REGISTRY } from "../registry";

describe("INTERACTION_REGISTRY wire exhaustiveness", () => {
  it("registers every UserInteractionKind from codegen wire", () => {
    const registered = new Set(INTERACTION_REGISTRY.map((d) => d.kind));
    const wireKinds = new Set(USER_INTERACTION_KIND_VALUES);

    expect(registered).toEqual(wireKinds);
    for (const kind of USER_INTERACTION_KIND_VALUES) {
      expect(INTERACTION_KIND_WIRE[kind]).toBeDefined();
    }
  });
});
