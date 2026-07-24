import { describe, expect, it } from "vitest";
import { parseFrontmatterFields } from "../frontmatter";

describe("parseFrontmatterFields", () => {
  it("解析顶层 key: value", () => {
    expect(parseFrontmatterFields("title: Hello\nauthor: Ada")).toEqual([
      { key: "title", value: "Hello" },
      { key: "author", value: "Ada" },
    ]);
  });

  it("数组项折叠成逗号串", () => {
    expect(parseFrontmatterFields("tags:\n  - a\n  - b\n  - c")).toEqual([
      { key: "tags", value: "a, b, c" },
    ]);
  });

  it("缩进续行拼回上一字段", () => {
    expect(parseFrontmatterFields("desc: line1\n  line2")).toEqual([
      { key: "desc", value: "line1 line2" },
    ]);
  });

  it("空行被忽略；空值保留键", () => {
    expect(parseFrontmatterFields("a: 1\n\nb:")).toEqual([
      { key: "a", value: "1" },
      { key: "b", value: "" },
    ]);
  });

  it("含冒号的值只在首个冒号处切分", () => {
    expect(parseFrontmatterFields("time: 12:30:00")).toEqual([
      { key: "time", value: "12:30:00" },
    ]);
  });

  it("无键的散行落为空键行", () => {
    expect(parseFrontmatterFields("just text")).toEqual([
      { key: "", value: "just text" },
    ]);
  });

  it("空 yaml → 空数组", () => {
    expect(parseFrontmatterFields("")).toEqual([]);
  });
});
