import { EditorState } from "@codemirror/state";
import { describe, expect, it } from "vitest";
import { isRewriteTargetIntact, sliceSelectionContext } from "../aiRewrite";

/** Build an EditorState with the main selection spanning [anchor, head). */
function stateWith(doc: string, anchor: number, head: number): EditorState {
  return EditorState.create({ doc, selection: { anchor, head } });
}

describe("sliceSelectionContext", () => {
  it("returns null for an empty (cursor-only) selection", () => {
    expect(sliceSelectionContext(stateWith("abcdefghij", 4, 4))).toBeNull();
  });

  it("extracts the selection plus symmetric context slices", () => {
    // doc = a b c d e f g h i j  → select [3,6) = "def", ctxChars=2.
    const ctx = sliceSelectionContext(stateWith("abcdefghij", 3, 6), 2);
    expect(ctx).toEqual({
      from: 3,
      to: 6,
      selection: "def",
      contextBefore: "bc", // slice(1, 3)
      contextAfter: "gh", // slice(6, 8)
    });
  });

  it("clamps context at the document boundaries", () => {
    // from=1, to=2, ctxChars=5 → before clamps to slice(0,1), after to slice(2,7).
    const ctx = sliceSelectionContext(stateWith("abcdefghij", 1, 2), 5);
    expect(ctx?.contextBefore).toBe("a");
    expect(ctx?.contextAfter).toBe("cdefg");
  });

  it("normalizes a backwards selection (head before anchor)", () => {
    // CodeMirror's main.from/to are min/max of anchor/head, so a drag leftwards
    // still yields the same [from,to) span.
    const ctx = sliceSelectionContext(stateWith("abcdefghij", 6, 3), 2);
    expect(ctx?.from).toBe(3);
    expect(ctx?.to).toBe(6);
    expect(ctx?.selection).toBe("def");
  });
});

describe("isRewriteTargetIntact", () => {
  const state = stateWith("abcdefghij", 0, 0);

  it("accepts a target whose span still holds the original text", () => {
    expect(
      isRewriteTargetIntact(state, { from: 3, to: 6, selection: "def" }),
    ).toBe(true);
  });

  it("accepts the whole-document span at exact boundaries", () => {
    expect(
      isRewriteTargetIntact(state, {
        from: 0,
        to: 10,
        selection: "abcdefghij",
      }),
    ).toBe(true);
  });

  it("rejects when the span's current text drifted from the captured original", () => {
    expect(
      isRewriteTargetIntact(state, { from: 3, to: 6, selection: "xyz" }),
    ).toBe(false);
  });

  it("rejects out-of-bounds spans (绝不改错位置)", () => {
    expect(
      isRewriteTargetIntact(state, { from: -1, to: 6, selection: "def" }),
    ).toBe(false);
    expect(
      isRewriteTargetIntact(state, { from: 3, to: 99, selection: "def" }),
    ).toBe(false);
  });

  it("rejects an inverted span (from > to)", () => {
    expect(
      isRewriteTargetIntact(state, { from: 6, to: 3, selection: "def" }),
    ).toBe(false);
  });
});
