import { remarkCitations, splitCitationText } from "@/lib/remarkCitations";
import { describe, expect, it } from "vitest";

interface MdNode {
  type: string;
  value?: string;
  url?: string;
  children?: MdNode[];
  data?: {
    hName?: string;
    hProperties?: Record<string, string>;
  };
}

const cite = (n: number): MdNode => ({
  type: "cite",
  data: {
    hName: "citemark",
    hProperties: { dataN: String(n) },
  },
  children: [{ type: "text", value: String(n) }],
});

describe("splitCitationText", () => {
  it("converts in-range markers to citemark nodes and keeps surrounding text", () => {
    expect(splitCitationText("see [1] and [2] here", 2)).toEqual([
      { type: "text", value: "see " },
      cite(1),
      { type: "text", value: " and " },
      cite(2),
      { type: "text", value: " here" },
    ]);
  });

  it("leaves out-of-range markers as literal text", () => {
    // max=1, so [2] is not a real source → stays text.
    expect(splitCitationText("a [1] b [2]", 1)).toEqual([
      { type: "text", value: "a " },
      cite(1),
      { type: "text", value: " b [2]" },
    ]);
  });

  it("returns the value untouched when there is no in-range marker", () => {
    expect(splitCitationText("no markers [0] [9]", 2)).toEqual([
      { type: "text", value: "no markers [0] [9]" },
    ]);
  });

  it("rewrites known #rN ledger ids and leaves unknown as text", () => {
    const known = new Set(["#r1"]);
    const ledgerCite = (id: string): MdNode => ({
      type: "cite",
      data: {
        hName: "citemark",
        hProperties: { dataLedgerId: id },
      },
      children: [{ type: "text", value: id }],
    });
    expect(splitCitationText("见 #r1 与 #r9", 0, known)).toEqual([
      { type: "text", value: "见 " },
      ledgerCite("#r1"),
      { type: "text", value: " 与 #r9" },
    ]);
  });

  it("rewrites consecutive #rN markers without spaces", () => {
    const known = new Set(["#r5", "#r3", "#r11"]);
    const ledgerCite = (id: string): MdNode => ({
      type: "cite",
      data: {
        hName: "citemark",
        hProperties: { dataLedgerId: id },
      },
      children: [{ type: "text", value: id }],
    });
    expect(splitCitationText("#r5#r3#r11", 0, known)).toEqual([
      ledgerCite("#r5"),
      ledgerCite("#r3"),
      ledgerCite("#r11"),
    ]);
  });
});

describe("remarkCitations attacher", () => {
  const run = (tree: MdNode, max: number) => {
    remarkCitations(max)()(tree);
    return tree;
  };

  it("rewrites markers inside paragraph text via hProperties", () => {
    const tree: MdNode = {
      type: "root",
      children: [
        { type: "paragraph", children: [{ type: "text", value: "x [1] y" }] },
      ],
    };
    run(tree, 1);
    expect(tree.children?.[0]?.children).toEqual([
      { type: "text", value: "x " },
      cite(1),
      { type: "text", value: " y" },
    ]);
  });

  it("does not touch markers inside code or existing links", () => {
    const tree: MdNode = {
      type: "root",
      children: [
        { type: "inlineCode", value: "arr[1]" },
        {
          type: "link",
          url: "https://e.com",
          children: [{ type: "text", value: "ref [1]" }],
        },
      ],
    };
    run(tree, 5);
    expect(tree.children?.[0]).toEqual({ type: "inlineCode", value: "arr[1]" });
    expect(tree.children?.[1]?.children).toEqual([
      { type: "text", value: "ref [1]" },
    ]);
  });

  it("is a no-op when there are no sources (max=0)", () => {
    const tree: MdNode = {
      type: "root",
      children: [
        { type: "paragraph", children: [{ type: "text", value: "a [1] b" }] },
      ],
    };
    run(tree, 0);
    expect(tree.children?.[0]?.children).toEqual([
      { type: "text", value: "a [1] b" },
    ]);
  });
});
