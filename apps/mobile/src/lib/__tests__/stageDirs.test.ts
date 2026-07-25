import { describe, expect, it } from "vitest";
import {
  countDescendantFiles,
  stageDirCaption,
  stageDirMeta,
  stageFileLabel,
} from "../stageDirs";

describe("stageDirs", () => {
  it("根级 research/debate 有元信息，普通目录零噪音", () => {
    expect(stageDirMeta("AgentCore/文档/research")?.label).toBe("调研案卷");
    expect(stageDirMeta("AgentCore/文档/debate")?.label).toBe("辩论产物");
    expect(stageDirMeta("src")).toBeNull();
    expect(stageDirMeta("AgentCore/文档/research/notes")).toBeNull();
  });

  it("文件路径打案卷标签；非约定路径无标签", () => {
    expect(stageFileLabel("AgentCore/文档/research/brief.md")).toBe("调研案卷");
    expect(stageFileLabel("AgentCore/文档/debate/round1.md")).toBe("辩论产物");
    expect(stageFileLabel("src/main.ts")).toBeNull();
  });

  it("副文案含件数", () => {
    const meta = stageDirMeta("AgentCore/文档/debate");
    expect(meta).toBeTruthy();
    if (!meta) return;
    expect(stageDirCaption(meta, 1)).toBe("辩论产物 · 1 件");
  });

  it("统计后代文件数", () => {
    const map = new Map([
      [
        "AgentCore/文档/debate",
        [
          { isDir: false, path: "AgentCore/文档/debate/a.md" },
          { isDir: false, path: "AgentCore/文档/debate/b.md" },
        ],
      ],
    ]);
    expect(
      countDescendantFiles("AgentCore/文档/debate", (d) => map.get(d)),
    ).toBe(2);
  });
});
