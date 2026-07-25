import { describe, expect, it } from "vitest";
import {
  hasSearchHits,
  parseSearchHits,
  searchHitFileName,
  searchHitPathLabel,
} from "../parseSearchHits";

describe("parseSearchHits · grep", () => {
  it("parses path:line: text hits and leaves summary plain", () => {
    const text = [
      "2 处匹配，分布在 1 个文件中（/Foo/）",
      "src/a.ts:10: const Foo = 1",
      "src/a.ts:20: export { Foo }",
      "[结果已截断——请收窄 path/glob 或细化 pattern]",
    ].join("\n");
    const segs = parseSearchHits(text, "grep");
    expect(segs).toEqual([
      { type: "plain", text: "2 处匹配，分布在 1 个文件中（/Foo/）" },
      {
        type: "hit",
        path: "src/a.ts",
        line: 10,
        rest: ": const Foo = 1",
      },
      {
        type: "hit",
        path: "src/a.ts",
        line: 20,
        rest: ": export { Foo }",
      },
      {
        type: "plain",
        text: "[结果已截断——请收窄 path/glob 或细化 pattern]",
      },
    ]);
    expect(hasSearchHits(segs)).toBe(true);
  });

  it("keeps empty-result tip as plain (no hits)", () => {
    const text =
      "本次 grep 未匹配 /Nope/。不要据此断定代码不存在。可执行下一步：① 收窄或放宽 path/glob；";
    const segs = parseSearchHits(text, "grep");
    expect(hasSearchHits(segs)).toBe(false);
    expect(segs).toEqual([{ type: "plain", text }]);
  });

  it("does not treat files_only `path: count` as hits", () => {
    const segs = parseSearchHits("src/a.ts: 3\nsrc/b.ts: 1", "grep");
    expect(hasSearchHits(segs)).toBe(false);
  });
});

describe("parseSearchHits · code_search", () => {
  it("parses path:start-end headers; snippet/score stay plain", () => {
    const text = [
      "lib/util.py:12-40  helper (function) (python)",
      "  def helper():",
      "      return 1",
      "  score=0.91",
      "",
      "（共 1 条结果；用 file_read path offset/limit 查看全文）",
    ].join("\n");
    const segs = parseSearchHits(text, "code_search");
    expect(segs[0]).toEqual({
      type: "hit",
      path: "lib/util.py",
      line: 12,
      endLine: 40,
      rest: "  helper (function) (python)",
    });
    expect(segs[1]).toEqual({ type: "plain", text: "  def helper():" });
    expect(hasSearchHits(segs)).toBe(true);
    expect(
      searchHitPathLabel(segs[0] as Extract<(typeof segs)[0], { type: "hit" }>),
    ).toBe("lib/util.py:12-40");
  });

  it("keeps empty-result tip as plain", () => {
    const text =
      "本次 code_search 未命中任何代码块。不要据此断定代码不存在。可执行下一步：① 收窄或放宽 path_prefix；";
    expect(hasSearchHits(parseSearchHits(text, "code_search"))).toBe(false);
  });
});

describe("searchHitFileName", () => {
  it("returns basename", () => {
    expect(searchHitFileName("src/deep/a.ts")).toBe("a.ts");
    expect(searchHitFileName("a.ts")).toBe("a.ts");
  });
});
