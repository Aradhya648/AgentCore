import { MAX_EXPANDED_TURNS, useGraphStore } from "@/stores/graph";
import { beforeEach, describe, expect, it } from "vitest";

describe("graph fold store", () => {
  beforeEach(() => {
    useGraphStore.setState({ foldByConversation: {} });
  });

  it("LRU-evicts oldest expanded turn beyond MAX_EXPANDED_TURNS", () => {
    const id = "conv-1";
    useGraphStore.getState().expandTurn(id, "t1");
    useGraphStore.getState().expandTurn(id, "t2");
    useGraphStore.getState().expandTurn(id, "t3");
    useGraphStore.getState().expandTurn(id, "t4");
    const fold = useGraphStore.getState().foldByConversation[id];
    expect(fold.expandedTurns).toEqual(["t2", "t3", "t4"]);
    expect(fold.expandedTurns.length).toBe(MAX_EXPANDED_TURNS);
  });

  it("bumps an already-expanded turn to the end (most recent)", () => {
    const id = "conv-1";
    useGraphStore.getState().expandTurn(id, "t1");
    useGraphStore.getState().expandTurn(id, "t2");
    useGraphStore.getState().expandTurn(id, "t3");
    useGraphStore.getState().expandTurn(id, "t1");
    expect(
      useGraphStore.getState().foldByConversation[id].expandedTurns,
    ).toEqual(["t2", "t3", "t1"]);
  });

  it("seeds default expanded turns once (newest-first window)", () => {
    const id = "conv-1";
    useGraphStore
      .getState()
      .ensureDefaultExpandedTurns(id, ["newest", "mid", "old", "older"]);
    expect(
      useGraphStore.getState().foldByConversation[id].expandedTurns,
    ).toEqual(["old", "mid", "newest"]);
    // Second call must not overwrite user state.
    useGraphStore.getState().collapseTurn(id, "newest");
    useGraphStore
      .getState()
      .ensureDefaultExpandedTurns(id, ["newest", "mid", "old"]);
    expect(
      useGraphStore.getState().foldByConversation[id].expandedTurns,
    ).toEqual(["old", "mid"]);
  });

  it("toggles subtree collapse and keeps expand sticky across re-seed", () => {
    const id = "conv-1";
    useGraphStore
      .getState()
      .ensureSubtreeDefaults(id, ["parent-1", "parent-2"]);
    expect(
      useGraphStore.getState().foldByConversation[id].collapsedSubtrees,
    ).toEqual(["parent-1", "parent-2"]);
    useGraphStore.getState().toggleSubtreeCollapsed(id, "parent-1");
    expect(
      useGraphStore.getState().foldByConversation[id].collapsedSubtrees,
    ).toEqual(["parent-2"]);
    // Re-seed must not re-collapse an explicitly expanded parent.
    useGraphStore
      .getState()
      .ensureSubtreeDefaults(id, ["parent-1", "parent-2"]);
    expect(
      useGraphStore.getState().foldByConversation[id].collapsedSubtrees,
    ).toEqual(["parent-2"]);
  });
});
