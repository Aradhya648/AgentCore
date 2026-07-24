import { describe, expect, it } from "vitest";
import { rehypeCodeMeta } from "../rehypeCodeMeta";

/** 构造一棵 `<pre><code class=...>` 的最小 hast 树。 */
function codeTree(className: unknown) {
  const code = {
    type: "element",
    tagName: "code",
    properties: { className } as Record<string, unknown>,
    children: [{ type: "text", value: "x = 1" }],
  };
  const tree = {
    type: "root",
    children: [{ type: "element", tagName: "pre", children: [code] }],
  };
  return { tree, code };
}

describe("rehypeCodeMeta", () => {
  it("把 lang:path 改写成可高亮的 language-lang 并存 dataFile", () => {
    const { tree, code } = codeTree(["language-ts:src/foo.ts"]);
    rehypeCodeMeta()(tree);
    expect(code.properties.className).toEqual(["language-ts"]);
    expect(code.properties.dataFile).toBe("src/foo.ts");
  });

  it("路径含多个冒号时只按首个冒号切分", () => {
    const { tree, code } = codeTree(["language-bash:scripts/a:b.sh"]);
    rehypeCodeMeta()(tree);
    expect(code.properties.className).toEqual(["language-bash"]);
    expect(code.properties.dataFile).toBe("scripts/a:b.sh");
  });

  it("缺语言只给路径时回落为 language-text", () => {
    const { tree, code } = codeTree(["language-:notes/readme.md"]);
    rehypeCodeMeta()(tree);
    expect(code.properties.className).toEqual(["language-text"]);
    expect(code.properties.dataFile).toBe("notes/readme.md");
  });

  it("普通 language-xxx（无冒号）保持不变、不加 dataFile", () => {
    const { tree, code } = codeTree(["language-python"]);
    rehypeCodeMeta()(tree);
    expect(code.properties.className).toEqual(["language-python"]);
    expect(code.properties.dataFile).toBeUndefined();
  });

  it("无语言类名的 code 不受影响", () => {
    const { tree, code } = codeTree(undefined);
    rehypeCodeMeta()(tree);
    expect(code.properties.className).toBeUndefined();
    expect(code.properties.dataFile).toBeUndefined();
  });

  it("冒号后为空（lang:）不当作路径", () => {
    const { tree, code } = codeTree(["language-ts:"]);
    rehypeCodeMeta()(tree);
    // 没有真实路径 → 不改写、不加 dataFile
    expect(code.properties.className).toEqual(["language-ts:"]);
    expect(code.properties.dataFile).toBeUndefined();
  });
});
