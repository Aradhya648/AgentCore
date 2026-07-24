import { describe, expect, it } from "vitest";
import { splitMarkdownBlocks } from "../streamingMarkdown";

/** 测试用：冻结前缀 + 尾块两分视图（生产只导出 {@link splitMarkdownBlocks}）。 */
function splitStreamingMarkdown(content: string): {
  stable: string;
  tail: string;
} {
  const blocks = splitMarkdownBlocks(content);
  if (blocks.length <= 1) return { stable: "", tail: content };
  const tail = blocks[blocks.length - 1];
  return { stable: blocks.slice(0, -1).join(""), tail };
}

/** 不变量：切分必须无损（stable + tail 等于原文）。 */
function expectLossless(content: string): {
  stable: string;
  tail: string;
} {
  const split = splitStreamingMarkdown(content);
  expect(split.stable + split.tail).toBe(content);
  return split;
}

/** 不变量：逐块切分必须无损（各块拼接等于原文）。 */
function expectBlocksLossless(content: string): string[] {
  const blocks = splitMarkdownBlocks(content);
  expect(blocks.join("")).toBe(content);
  return blocks;
}

describe("splitStreamingMarkdown", () => {
  it("没有空行时整体落入尾块（无可冻结前缀）", () => {
    const { stable, tail } = expectLossless("一个还在写的段落，没有任何空行");
    expect(stable).toBe("");
    expect(tail).toBe("一个还在写的段落，没有任何空行");
  });

  it("空串返回两个空串", () => {
    const { stable, tail } = expectLossless("");
    expect(stable).toBe("");
    expect(tail).toBe("");
  });

  it("两段之间的空行处切分：首段冻结、次段为尾", () => {
    const { stable, tail } = expectLossless("第一段。\n\n第二段还在写");
    expect(stable).toBe("第一段。\n\n");
    expect(tail).toBe("第二段还在写");
  });

  it("取最后一个块边界：只把最末一块留作尾", () => {
    const { stable, tail } = expectLossless("# 标题\n\n段落一。\n\n段落二");
    expect(stable).toBe("# 标题\n\n段落一。\n\n");
    expect(tail).toBe("段落二");
  });

  it("松散列表（项间有空行）整体不被劈开", () => {
    const content = "- 第一项\n\n- 第二项\n\n- 第三项";
    const { stable, tail } = expectLossless(content);
    // 下一非空行都是列表项（续行）→ 不切，整列表留在尾块
    expect(stable).toBe("");
    expect(tail).toBe(content);
  });

  it("段落后的松散列表：在段落与列表之间不切，保持列表完整", () => {
    const content = "引子段落。\n\n- 项一\n\n- 项二";
    const { stable, tail } = expectLossless(content);
    // 空行后是列表项 → 保守不切；整体留尾块（终态会整篇渲染）
    expect(stable).toBe("");
    expect(tail).toBe(content);
  });

  it("列表写完后接普通段落：在列表与段落之间切", () => {
    const content = "- 项一\n- 项二\n\n收尾段落";
    const { stable, tail } = expectLossless(content);
    expect(stable).toBe("- 项一\n- 项二\n\n");
    expect(tail).toBe("收尾段落");
  });

  it("栅栏代码块内部的空行不触发切分", () => {
    const content = "```py\na = 1\n\nb = 2\n```\n\n后文";
    const { stable, tail } = expectLossless(content);
    // 代码块内的空行被忽略；只在代码块结束后的空行处切
    expect(stable).toBe("```py\na = 1\n\nb = 2\n```\n\n");
    expect(tail).toBe("后文");
  });

  it("未闭合的栅栏代码块：整体留尾块（不在块内切）", () => {
    const content = "前言。\n\n```py\nx = 1\n\ny = 2";
    const { stable, tail } = expectLossless(content);
    // 代码块从 ``` 起一直未闭合 → 边界只能停在它之前
    expect(stable).toBe("前言。\n\n");
    expect(tail).toBe("```py\nx = 1\n\ny = 2");
  });

  it("多行引用块整体不被劈开", () => {
    const content = "> 引用第一行\n\n> 引用第二行\n\n正文";
    const { stable, tail } = expectLossless(content);
    // 空行后是 '>' 续行 → 引用组保持完整；最终边界落在引用与正文之间
    expect(stable).toBe("> 引用第一行\n\n> 引用第二行\n\n");
    expect(tail).toBe("正文");
  });

  it("末尾多余空行不产生越界边界", () => {
    const content = "完整段落。\n\n";
    const { stable, tail } = expectLossless(content);
    // 空行之后没有内容 → 不切，整体仍是尾（无可冻结的『下一块』）
    expect(stable).toBe("");
    expect(tail).toBe(content);
  });

  it("缩进续行（列表项的二级内容）不被劈开", () => {
    const content = "- 项一：\n\n    缩进的续行内容\n\n普通段落";
    const { stable, tail } = expectLossless(content);
    // 第一个空行后是缩进续行 → 不切；第二个空行后是普通段落 → 切
    expect(stable).toBe("- 项一：\n\n    缩进的续行内容\n\n");
    expect(tail).toBe("普通段落");
  });
});

describe("splitMarkdownBlocks", () => {
  it("空串返回空数组", () => {
    expect(expectBlocksLossless("")).toEqual([]);
  });

  it("没有空行时整体是唯一一块", () => {
    expect(expectBlocksLossless("一个还在写的段落，没有任何空行")).toEqual([
      "一个还在写的段落，没有任何空行",
    ]);
  });

  it("多段：每段（含其后空行）各自成块，末段为在写尾块", () => {
    // 逐块化的核心收益：# 标题 / 段落一 各自只解析一次，段落二是在写尾块。
    expect(expectBlocksLossless("# 标题\n\n段落一。\n\n段落二")).toEqual([
      "# 标题\n\n",
      "段落一。\n\n",
      "段落二",
    ]);
  });

  it("两段之间的空行处切分为两块", () => {
    expect(expectBlocksLossless("第一段。\n\n第二段还在写")).toEqual([
      "第一段。\n\n",
      "第二段还在写",
    ]);
  });

  it("松散列表（项间有空行）整体不被劈开，仍是一块", () => {
    const content = "- 第一项\n\n- 第二项\n\n- 第三项";
    expect(expectBlocksLossless(content)).toEqual([content]);
  });

  it("列表写完后接普通段落：列表与段落各自成块", () => {
    expect(expectBlocksLossless("- 项一\n- 项二\n\n收尾段落")).toEqual([
      "- 项一\n- 项二\n\n",
      "收尾段落",
    ]);
  });

  it("栅栏代码块内部的空行不触发切分", () => {
    expect(expectBlocksLossless("```py\na = 1\n\nb = 2\n```\n\n后文")).toEqual([
      "```py\na = 1\n\nb = 2\n```\n\n",
      "后文",
    ]);
  });

  it("未闭合的栅栏代码块整体留在最后一块", () => {
    expect(expectBlocksLossless("前言。\n\n```py\nx = 1\n\ny = 2")).toEqual([
      "前言。\n\n",
      "```py\nx = 1\n\ny = 2",
    ]);
  });

  it("多行引用块整体不被劈开，与其后正文各自成块", () => {
    expect(
      expectBlocksLossless("> 引用第一行\n\n> 引用第二行\n\n正文"),
    ).toEqual(["> 引用第一行\n\n> 引用第二行\n\n", "正文"]);
  });

  it("末尾多余空行不产生越界边界（整体仍是一块）", () => {
    const content = "完整段落。\n\n";
    expect(expectBlocksLossless(content)).toEqual([content]);
  });

  it("连续多个空行只产生一个边界（不生成空块）", () => {
    const blocks = expectBlocksLossless("第一段。\n\n\n\n第二段");
    expect(blocks).toEqual(["第一段。\n\n\n\n", "第二段"]);
    expect(blocks.some((b) => b === "")).toBe(false);
  });

  it("splitStreamingMarkdown 的尾块与逐块切分的末块一致", () => {
    const content = "# 标题\n\n段落一。\n\n段落二";
    const blocks = splitMarkdownBlocks(content);
    const { stable, tail } = splitStreamingMarkdown(content);
    expect(tail).toBe(blocks[blocks.length - 1]);
    expect(stable).toBe(blocks.slice(0, -1).join(""));
  });
});
