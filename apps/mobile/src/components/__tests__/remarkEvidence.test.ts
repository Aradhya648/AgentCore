import { remarkEvidence, splitEvidenceText } from "@/components/remarkEvidence";
import { describe, expect, it } from "vitest";

interface MdNode {
  type: string;
  value?: string;
  url?: string;
  children?: MdNode[];
  data?: { hName?: string; hProperties?: Record<string, string> };
}

const evi = (kind: "verified" | "unverified", note = ""): MdNode => ({
  type: "evidence",
  data: { hName: "evidencemark", hProperties: { dataKind: kind } },
  children: note ? [{ type: "text", value: note }] : [],
});

describe("splitEvidenceText", () => {
  it("splits a verified marker with a ledger id", () => {
    expect(splitEvidenceText("降本【已核实·#e3】约 18%")).toEqual([
      { type: "text", value: "降本" },
      evi("verified", "#e3"),
      { type: "text", value: "约 18%" },
    ]);
  });

  it("keeps dual-write note text whole (phrase + #eN)", () => {
    expect(splitEvidenceText("事实【已核实·街访数据 #e2】。")).toEqual([
      { type: "text", value: "事实" },
      evi("verified", "街访数据 #e2"),
      { type: "text", value: "。" },
    ]);
  });

  it("splits a verified marker with a source out of surrounding text", () => {
    expect(splitEvidenceText("降本【已核实·2024报表】约 18%")).toEqual([
      { type: "text", value: "降本" },
      evi("verified", "2024报表"),
      { type: "text", value: "约 18%" },
    ]);
  });

  it("maps 待核实 to the unverified kind and keeps the note", () => {
    expect(splitEvidenceText("回收约两个季度【待核实·推断】。")).toEqual([
      { type: "text", value: "回收约两个季度" },
      evi("unverified", "推断"),
      { type: "text", value: "。" },
    ]);
  });

  it("handles a bare marker with no source (empty note, no children)", () => {
    expect(splitEvidenceText("这条【待核实】仍不确定")).toEqual([
      { type: "text", value: "这条" },
      evi("unverified"),
      { type: "text", value: "仍不确定" },
    ]);
  });

  it("splits multiple markers of both kinds in one line", () => {
    expect(splitEvidenceText("A【已核实·甲】B【待核实·推断】C")).toEqual([
      { type: "text", value: "A" },
      evi("verified", "甲"),
      { type: "text", value: "B" },
      evi("unverified", "推断"),
      { type: "text", value: "C" },
    ]);
  });

  it("returns the value untouched when there is no marker", () => {
    expect(splitEvidenceText("没有任何标记的一句话")).toEqual([
      { type: "text", value: "没有任何标记的一句话" },
    ]);
  });
});

describe("remarkEvidence attacher", () => {
  const run = (tree: MdNode) => {
    remarkEvidence()()(tree);
    return tree;
  };

  it("rewrites markers inside paragraph text", () => {
    const tree: MdNode = {
      type: "root",
      children: [
        {
          type: "paragraph",
          children: [{ type: "text", value: "先说【已核实·年报】再说别的" }],
        },
      ],
    };
    run(tree);
    expect(tree.children?.[0]?.children).toEqual([
      { type: "text", value: "先说" },
      evi("verified", "年报"),
      { type: "text", value: "再说别的" },
    ]);
  });

  it("does not touch markers inside code or existing links", () => {
    const tree: MdNode = {
      type: "root",
      children: [
        { type: "inlineCode", value: "x【已核实·y】" },
        {
          type: "link",
          url: "https://e.com",
          children: [{ type: "text", value: "见【待核实·推断】" }],
        },
      ],
    };
    run(tree);
    expect(tree.children?.[0]).toEqual({
      type: "inlineCode",
      value: "x【已核实·y】",
    });
    expect(tree.children?.[1]?.children).toEqual([
      { type: "text", value: "见【待核实·推断】" },
    ]);
  });
});
