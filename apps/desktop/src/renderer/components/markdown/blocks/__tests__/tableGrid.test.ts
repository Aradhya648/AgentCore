import { describe, expect, it } from "vitest";
import { type TableData, parseGfmTable, serializeGfmTable } from "../tableGrid";

describe("GFM 表格 parse/serialize", () => {
  it("解析表头、对齐与数据行", () => {
    const src = ["| a | b | c |", "| :-- | :--: | --: |", "| 1 | 2 | 3 |"].join(
      "\n",
    );
    const data = parseGfmTable(src);
    expect(data).not.toBeNull();
    expect(data?.headers).toEqual(["a", "b", "c"]);
    expect(data?.aligns).toEqual(["left", "center", "right"]);
    expect(data?.rows).toEqual([["1", "2", "3"]]);
  });

  it("补齐缺列、截断超长行到表头列数", () => {
    const src = ["| a | b |", "| --- | --- |", "| 1 |", "| 1 | 2 | 3 |"].join(
      "\n",
    );
    const data = parseGfmTable(src);
    expect(data?.rows).toEqual([
      ["1", ""],
      ["1", "2"],
    ]);
  });

  it("非法表格（缺分隔行）返回 null", () => {
    expect(parseGfmTable("| a | b |\n| 1 | 2 |")).toBeNull();
    expect(parseGfmTable("just text")).toBeNull();
  });

  it("parse → serialize → parse 往返稳定", () => {
    const src = [
      "| 姓名 | 年龄 |",
      "| :-- | --: |",
      "| 张三 | 30 |",
      "| 李四 | 25 |",
    ].join("\n");
    const once = parseGfmTable(src);
    expect(once).not.toBeNull();
    const out = serializeGfmTable(once as TableData);
    const twice = parseGfmTable(out);
    expect(twice).toEqual(once);
  });

  it("序列化保留对齐冒号", () => {
    const data = serializeGfmTable({
      headers: ["x", "y", "z"],
      aligns: ["left", "center", "right"],
      rows: [["1", "2", "3"]],
    });
    const delimLine = data.split("\n")[1];
    expect(delimLine).toContain(":--");
    expect(delimLine).toContain(":-");
    expect(delimLine).toMatch(/-:/);
  });
});
