import { describe, expect, it } from "vitest";
import {
  argumentTitle,
  parseSpeechArguments,
  rehydrateArgumentTitles,
  summarizeText,
} from "../parseSpeechArguments";

describe("summarizeText", () => {
  it("returns short text unchanged", () => {
    expect(summarizeText("短句", 30)).toBe("短句");
  });

  it("truncates long text with ellipsis", () => {
    const long = "这是一段很长的论述内容用于测试截断逻辑是否正常工作";
    const out = summarizeText(long, 12);
    expect(out.length).toBeLessThanOrEqual(13);
    expect(out.endsWith("…")).toBe(true);
  });
});

describe("argumentTitle", () => {
  it("extracts colon-prefixed label", () => {
    expect(
      argumentTitle(
        "支持理由：收益可量化——首年可降本约 18%，回收周期约两个季度。",
      ),
    ).toContain("支持理由");
  });

  it("uses first sentence for plain text", () => {
    expect(argumentTitle("第一点很重要。后面是补充。")).toBe("第一点很重要");
  });
});

describe("parseSpeechArguments", () => {
  it("parses numbered list", () => {
    const args = parseSpeechArguments(
      "1. 成本可控\n2. 风险有兜底\n3. 收益可量化",
    );
    expect(args).toHaveLength(3);
    expect(args[0].title).toContain("成本");
  });

  it("parses bullet list", () => {
    const args = parseSpeechArguments("- 论点甲\n- 论点乙");
    expect(args).toHaveLength(2);
  });

  it("parses markdown headers", () => {
    const args = parseSpeechArguments(
      "## 成本优势\n降本 18% 可核实。\n\n## 风险可控\n熔断兜底。",
    );
    expect(args).toHaveLength(2);
    expect(args[0].title).toContain("成本优势");
    expect(args[0].body).toContain("降本");
  });

  it("parses paragraph blocks", () => {
    const args = parseSpeechArguments("第一段立论。\n\n第二段补充。");
    expect(args).toHaveLength(2);
  });

  it("wraps single paragraph as one argument", () => {
    const text =
      "反对理由：风险缺兜底——迁移期存在双写不一致窗口，尾部故障率恐被低估。";
    const args = parseSpeechArguments(text);
    expect(args).toHaveLength(1);
    expect(args[0].body).toBe(text);
    expect(args[0].title).toContain("反对理由");
  });

  it("keeps first block as an argument (no preamble stripping)", () => {
    // 前端不再剥除过程句——两阶段成稿契约保证发言正文干净；若正文含引导句则如实切段。
    const args = parseSpeechArguments(
      "以下是正方的立论。\n\n成本可控，回收周期短。\n\n风险有明确兜底。",
    );
    expect(args).toHaveLength(3);
    expect(args[0].body).toContain("以下是");
  });

  it("pins skeleton-compliant speech: ### titles without body title echo", () => {
    // 产出端骨架契约样本（首行即 ###、无总标题/加粗伪标题）——钉住接缝两端：
    // prompt 纪律 ↔ parseSpeechArguments 切段。
    const speech = [
      "### 成本可控可回收",
      "首年可降本约 18%【已核实·内部测算】，回收周期约两个季度。",
      "",
      "### 风险有明确兜底",
      "迁移期双写窗口设熔断，尾部故障率有上限【待核实·推断】。",
      "",
      "### 收益可量化对比",
      "与维持现状相比，净现值在三年内转正。",
    ].join("\n");
    const args = parseSpeechArguments(speech);
    expect(args).toHaveLength(3);
    expect(args[0].title).toBe("成本可控可回收");
    expect(args[1].title).toBe("风险有明确兜底");
    expect(args[2].title).toBe("收益可量化对比");
    // 展开正文不含标题重复（titleFromHeaderBlock 剥掉 ### 行）
    expect(args[0].body).not.toContain("###");
    expect(args[0].body).not.toMatch(/^成本可控可回收/);
    expect(args[0].body).toContain("首年可降本");
    expect(args[1].body).toContain("熔断");
  });

  it("keeps full long ### titles (LV tape semantics; no data-layer ellipsis)", () => {
    const t1 = "论点一：四叶花卉是公共元素，但LV的Monogram是独创作品";
    const t2 = "论点二：LV四叶花图案经长期使用已获得“第二含义”";
    const speech = [
      `### ${t1}`,
      "正文说明公共元素与独创作品的界限。",
      "",
      `### ${t2}`,
      "正文说明第二含义的认定路径。",
    ].join("\n");
    const args = parseSpeechArguments(speech);
    expect(args).toHaveLength(2);
    expect(args[0].title).toBe(t1);
    expect(args[1].title).toBe(t2);
    expect(args[0].title.endsWith("…")).toBe(false);
    expect(args[1].title.endsWith("…")).toBe(false);
    expect(args[0].title.length).toBeGreaterThan(30);
  });
});

describe("rehydrateArgumentTitles", () => {
  const t1 = "论点一：四叶花卉是公共元素，但LV的Monogram是独创作品";
  const t2 = "论点二：LV四叶花图案经长期使用已获得“第二含义”";
  const output = [
    `### ${t1}`,
    "结构化 body 甲（应保留）。",
    "",
    `### ${t2}`,
    "结构化 body 乙（应保留）。",
  ].join("\n");

  it("overlays full titles from output onto truncated structured args by index", () => {
    const structured = [
      {
        id: "backend-a",
        title: "论点一：四叶花卉是公共元素，但LV的Monogram是…",
        body: "落盘 body 甲",
      },
      {
        id: "backend-b",
        title: "论点二：LV四叶花图案经长期使用已获得…",
        body: "落盘 body 乙",
      },
    ];
    const out = rehydrateArgumentTitles(structured, output);
    expect(out).toHaveLength(2);
    expect(out[0].id).toBe("backend-a");
    expect(out[0].body).toBe("落盘 body 甲");
    expect(out[0].title).toBe(t1);
    expect(out[0].title).toContain("独创作品");
    expect(out[1].id).toBe("backend-b");
    expect(out[1].body).toBe("落盘 body 乙");
    expect(out[1].title).toBe(t2);
    expect(out[1].title).toContain("第二含义");
  });

  it("prefers stable id match when ids align with parseSpeechArguments", () => {
    const structured = [
      { id: "arg-1", title: "截断…", body: "body-1" },
      { id: "arg-0", title: "另一截断…", body: "body-0" },
    ];
    const out = rehydrateArgumentTitles(structured, output);
    // id 命中优先于 index：arg-0 → 第一段，arg-1 → 第二段
    expect(out[0].title).toBe(t2);
    expect(out[0].body).toBe("body-1");
    expect(out[1].title).toBe(t1);
    expect(out[1].body).toBe("body-0");
  });

  it("keeps structured titles when output is empty", () => {
    const structured = [{ id: "a", title: "截断标题…", body: "body" }];
    expect(rehydrateArgumentTitles(structured, "")).toEqual(structured);
    expect(rehydrateArgumentTitles(structured, "   ")).toEqual(structured);
  });

  it("is a no-op when structured titles are already complete", () => {
    const structured = [
      { id: "a", title: t1, body: "body-a" },
      { id: "b", title: t2, body: "body-b" },
    ];
    const out = rehydrateArgumentTitles(structured, output);
    expect(out).toEqual(structured);
  });
});
