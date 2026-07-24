import { describe, expect, it } from "vitest";
import { applyBoardOps } from "../ops";
import type { SceneElement } from "../types";

/** Build a minimal valid scene element for fixtures. */
const el = (p: Partial<SceneElement> & { id: string }): SceneElement => ({
  type: "rectangle",
  x: 0,
  y: 0,
  width: 100,
  height: 60,
  schemaVersion: 1,
  ...p,
});

const find = (els: readonly SceneElement[], id: string) =>
  els.find((e) => e.id === id);
const arrows = (els: readonly SceneElement[]) =>
  els.filter((e) => e.type === "arrow");

describe("applyBoardOps — add_node", () => {
  it("creates a sticky node with text and reports it as created", () => {
    const { elements, created } = applyBoardOps(
      [],
      [{ op: "add_node", ref: "a", text: "Hello" }],
    );
    expect(created).toHaveLength(1);
    const node = find(elements, created[0]);
    expect(node).toMatchObject({ type: "sticky", text: "Hello" });
    expect(node?.id).toMatch(/^brd-/);
  });

  it("creates a text node carrying its text", () => {
    const { elements, created } = applyBoardOps(
      [],
      [{ op: "add_node", ref: "t", kind: "text", text: "note" }],
    );
    expect(find(elements, created[0])).toMatchObject({
      type: "text",
      text: "note",
    });
  });

  it("auto-lays-out nodes that omit coordinates (no pile at 0,0)", () => {
    const { elements, created } = applyBoardOps(
      [],
      [
        { op: "add_node", ref: "a" },
        { op: "add_node", ref: "b" },
      ],
    );
    const a = find(elements, created[0]);
    const b = find(elements, created[1]);
    expect(a?.x).toBeGreaterThan(0);
    expect(a?.x === b?.x && a?.y === b?.y).toBe(false);
  });

  it("honors explicit coordinates", () => {
    const { elements, created } = applyBoardOps(
      [],
      [{ op: "add_node", ref: "a", x: 42, y: 99 }],
    );
    expect(find(elements, created[0])).toMatchObject({ x: 42, y: 99 });
  });
});

describe("applyBoardOps — connect", () => {
  it("binds an arrow between two same-batch refs, carrying the label", () => {
    const { elements } = applyBoardOps(
      [],
      [
        { op: "add_node", ref: "a" },
        { op: "add_node", ref: "b" },
        { op: "connect", from: "a", to: "b", label: "depends" },
      ],
    );
    const nodes = elements.filter((e) => e.type === "sticky");
    expect(arrows(elements)[0]).toMatchObject({
      start: { id: nodes[0].id },
      end: { id: nodes[1].id },
      text: "depends",
    });
  });

  it("binds an arrow to an existing element by id", () => {
    const { elements } = applyBoardOps(
      [el({ id: "x", x: 0, y: 0, width: 100, height: 50 })],
      [
        { op: "add_node", ref: "a" },
        { op: "connect", from: "a", to: "x" },
      ],
    );
    expect(arrows(elements)[0]?.end).toEqual({ id: "x" });
  });

  it("skips a connect to an unknown id (not a ref, not in the scene)", () => {
    const { elements } = applyBoardOps(
      [],
      [
        { op: "add_node", ref: "a" },
        { op: "connect", from: "a", to: "ghost" },
      ],
    );
    expect(arrows(elements)).toHaveLength(0);
  });
});

describe("applyBoardOps — move / set_text / delete", () => {
  const scene = (): SceneElement[] => [
    el({ id: "x", type: "rectangle", x: 0, y: 0, width: 10, height: 10 }),
    el({
      id: "t",
      type: "text",
      x: 0,
      y: 0,
      width: 40,
      height: 24,
      text: "old",
    }),
  ];

  it("moves an existing element by id", () => {
    const { elements } = applyBoardOps(scene(), [
      { op: "move", id: "x", x: 50, y: 60 },
    ]);
    expect(find(elements, "x")).toMatchObject({ x: 50, y: 60 });
  });

  it("rewrites the text of an element via set_text", () => {
    const { elements } = applyBoardOps(scene(), [
      { op: "set_text", id: "t", text: "new" },
    ]);
    expect(find(elements, "t")?.text).toBe("new");
  });

  it("deletes an existing element by id", () => {
    const { elements } = applyBoardOps(scene(), [{ op: "delete", id: "x" }]);
    expect(find(elements, "x")).toBeUndefined();
    expect(find(elements, "t")).toBeDefined();
  });

  it("prunes an arrow whose endpoint was deleted", () => {
    const withArrow = applyBoardOps(scene(), [
      { op: "connect", from: "x", to: "t" },
    ]).elements;
    expect(arrows(withArrow)).toHaveLength(1);
    const { elements } = applyBoardOps(withArrow, [{ op: "delete", id: "x" }]);
    expect(arrows(elements)).toHaveLength(0);
  });

  it("ignores an op whose target id is absent", () => {
    const { elements } = applyBoardOps(scene(), [
      { op: "move", id: "ghost", x: 9, y: 9 },
    ]);
    expect(elements).toHaveLength(2);
  });

  // A batch commonly creates a node then edits it in the same commit, addressing it
  // by its `ref` (its real id doesn't exist yet). The applier must resolve ref, not
  // only id, for move/set_text/delete — else these silently no-op (regression guard).
  it("moves a same-batch element addressed by ref", () => {
    const { elements, created } = applyBoardOps(scene(), [
      { op: "add_node", ref: "n", text: "fresh" },
      { op: "move", ref: "n", x: 33, y: 44 },
    ]);
    expect(find(elements, created[0])).toMatchObject({ x: 33, y: 44 });
  });

  it("rewrites a same-batch element's text addressed by ref", () => {
    const { elements, created } = applyBoardOps(scene(), [
      { op: "add_node", ref: "n", text: "before" },
      { op: "set_text", ref: "n", text: "after" },
    ]);
    expect(find(elements, created[0])?.text).toBe("after");
  });

  it("deletes a same-batch element addressed by ref", () => {
    const { elements, created } = applyBoardOps(scene(), [
      { op: "add_node", ref: "n" },
      { op: "delete", ref: "n" },
    ]);
    expect(created).toHaveLength(1);
    expect(find(elements, created[0])).toBeUndefined();
  });

  it("does not mutate the input array", () => {
    const input = scene();
    applyBoardOps(input, [{ op: "delete", id: "x" }]);
    expect(input).toHaveLength(2);
  });
});

describe("applyBoardOps — group", () => {
  it("stamps a shared groupId on resolvable members (by real id)", () => {
    const { elements } = applyBoardOps(
      [el({ id: "a" }), el({ id: "b" }), el({ id: "c" })],
      [{ op: "group", members: ["a", "b"] }],
    );
    const ga = find(elements, "a")?.groupIds?.[0];
    expect(ga).toBeTruthy();
    expect(find(elements, "b")?.groupIds?.[0]).toBe(ga);
    expect(find(elements, "c")?.groupIds ?? []).toHaveLength(0);
  });

  it("resolves new-node refs to their created ids in the same batch", () => {
    const { elements } = applyBoardOps(
      [],
      [
        { op: "add_node", ref: "a" },
        { op: "add_node", ref: "b" },
        { op: "group", members: ["a", "b"] },
      ],
    );
    const nodes = elements.filter((e) => e.type === "sticky");
    const ga = nodes[0].groupIds?.[0];
    expect(ga).toBeTruthy();
    expect(nodes[1].groupIds?.[0]).toBe(ga);
  });

  it("mixes a new-node ref and an existing id in one group", () => {
    const { elements } = applyBoardOps(
      [el({ id: "real-x" })],
      [
        { op: "add_node", ref: "a" },
        { op: "group", members: ["a", "real-x"] },
      ],
    );
    const created = find(
      elements,
      elements.find((e) => e.type === "sticky")?.id ?? "",
    );
    const ga = created?.groupIds?.[0];
    expect(ga).toBeTruthy();
    expect(find(elements, "real-x")?.groupIds?.[0]).toBe(ga);
  });
});
