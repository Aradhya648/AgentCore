import {
  countDescendantFiles,
  stageDirCaption,
  stageDirMeta,
  stageFileLabel,
} from "@/lib/stageDirs";
import { describe, expect, it } from "vitest";

describe("stageDirs", () => {
  it("根级 research/debate 有元信息，普通目录零噪音", () => {
    expect(stageDirMeta("research")?.label).toBe("调研案卷");
    expect(stageDirMeta("debate")?.label).toBe("辩论产物");
    expect(stageDirMeta("src")).toBeNull();
    expect(stageDirMeta("research/notes")).toBeNull();
    expect(stageDirMeta("")).toBeNull();
  });

  it("文件路径打案卷标签；非约定路径无标签", () => {
    expect(stageFileLabel("research/brief.md")).toBe("调研案卷");
    expect(stageFileLabel("debate/round1.md")).toBe("辩论产物");
    expect(stageFileLabel("src/main.ts")).toBeNull();
    expect(stageFileLabel("research")).toBeNull();
  });

  it("副文案含件数", () => {
    const meta = stageDirMeta("research");
    expect(meta).toBeTruthy();
    if (!meta) return;
    expect(stageDirCaption(meta, 3)).toBe("调研案卷 · 3 件");
  });

  it("统计后代文件数（含子目录内文件）", () => {
    const map = new Map<string, { isDir: boolean; path: string }[]>([
      [
        "research",
        [
          { isDir: false, path: "research/a.md" },
          { isDir: true, path: "research/sub" },
        ],
      ],
      ["research/sub", [{ isDir: false, path: "research/sub/b.md" }]],
    ]);
    expect(countDescendantFiles("research", (d) => map.get(d))).toBe(2);
    expect(countDescendantFiles("missing", (d) => map.get(d))).toBe(0);
  });
});
