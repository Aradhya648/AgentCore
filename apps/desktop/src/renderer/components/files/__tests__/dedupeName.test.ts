import { dedupeName } from "@/components/files/dedupeName";
import { describe, expect, it } from "vitest";

describe("dedupeName（复制-粘贴的去重命名）", () => {
  it("名字不冲突时原样返回", () => {
    expect(dedupeName("a.txt", new Set(["b.txt"]))).toBe("a.txt");
    expect(dedupeName("docs", new Set())).toBe("docs");
  });

  it("冲突时追加「 副本」并保留扩展名", () => {
    expect(dedupeName("a.txt", new Set(["a.txt"]))).toBe("a 副本.txt");
  });

  it("无扩展名的文件/目录在末尾追加「 副本」", () => {
    expect(dedupeName("report", new Set(["report"]))).toBe("report 副本");
  });

  it("「 副本」也已存在时递增编号", () => {
    const existing = new Set(["a.txt", "a 副本.txt", "a 副本 2.txt"]);
    expect(dedupeName("a.txt", existing)).toBe("a 副本 3.txt");
  });

  it("前导点文件按整体处理（不把 .env 当扩展名）", () => {
    expect(dedupeName(".env", new Set([".env"]))).toBe(".env 副本");
  });

  it("多扩展名只在最后一个点前插入「 副本」", () => {
    expect(dedupeName("a.tar.gz", new Set(["a.tar.gz"]))).toBe("a.tar 副本.gz");
  });
});
