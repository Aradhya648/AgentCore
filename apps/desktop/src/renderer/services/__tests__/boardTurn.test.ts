import {
  describeSelection,
  implementSelectionPrompt,
  iterateArtifactPrompt,
  organizeSelectionPrompt,
  partitionSelection,
} from "@/services/boardTurn";
import type { SceneElement } from "@/whiteboard";
import { describe, expect, it } from "vitest";

const el = (p: Partial<SceneElement> & { id: string }): SceneElement => ({
  type: "rectangle",
  x: 0,
  y: 0,
  width: 100,
  height: 60,
  schemaVersion: 1,
  ...p,
});

const scene: SceneElement[] = [
  el({ id: "a", type: "rectangle", x: 10.4, y: 20.6, text: "登录" }),
  el({ id: "b", type: "ellipse", x: 100, y: 200 }),
  el({ id: "c", type: "text", x: 0, y: 0, text: "  说明  " }),
];

describe("describeSelection", () => {
  it("renders one line per selected element with id, shape, rounded pos, and text", () => {
    const out = describeSelection(scene, ["a"]);
    expect(out).toBe("- [a] rectangle @(10,21)：“登录”");
  });

  it("omits text when an element has none", () => {
    expect(describeSelection(scene, ["b"])).toBe("- [b] ellipse @(100,200)");
  });

  it("trims surrounding whitespace from text", () => {
    expect(describeSelection(scene, ["c"])).toBe("- [c] text @(0,0)：“说明”");
  });

  it("skips selection ids not present in the scene (stale selection)", () => {
    const out = describeSelection(scene, ["ghost", "b"]);
    expect(out).toBe("- [b] ellipse @(100,200)");
  });

  it("joins multiple selected elements with newlines", () => {
    const out = describeSelection(scene, ["a", "b"]);
    expect(out.split("\n")).toHaveLength(2);
  });

  it("returns an empty string when nothing resolves", () => {
    expect(describeSelection(scene, ["x", "y"])).toBe("");
  });
});

const mixedScene: SceneElement[] = [
  el({ id: "a", type: "rectangle", x: 10, y: 20, text: "登录" }),
  el({ id: "d", type: "freedraw", x: 5, y: 6 }),
  el({
    id: "img",
    type: "image",
    x: 0,
    y: 0,
    src: "data:image/png;base64,AAA",
  }),
];

describe("partitionSelection", () => {
  it("routes freedraw + image to visual, everything else to structured", () => {
    const { structuredIds, visualIds } = partitionSelection(mixedScene, [
      "a",
      "d",
      "img",
    ]);
    expect(structuredIds).toEqual(["a"]);
    expect(visualIds).toEqual(["d", "img"]);
  });

  it("drops stale ids not present in the scene", () => {
    const { structuredIds, visualIds } = partitionSelection(mixedScene, [
      "a",
      "ghost",
    ]);
    expect(structuredIds).toEqual(["a"]);
    expect(visualIds).toEqual([]);
  });
});

describe("organizeSelectionPrompt", () => {
  it("structured-only: asks for board_ops, embeds the description, no board_read", () => {
    const prompt = organizeSelectionPrompt(scene, ["a"]);
    expect(prompt).toContain("board_ops");
    expect(prompt).toContain("真实 id");
    expect(prompt).toContain("- [a] rectangle @(10,21)：“登录”");
    expect(prompt).not.toContain("board_read");
  });

  it("mixed: tells the CEO to board_read the visual ids (手绘+图片), still describes structured", () => {
    const prompt = organizeSelectionPrompt(mixedScene, ["a", "d", "img"]);
    expect(prompt).toContain("board_read");
    expect(prompt).toContain("d、img"); // the visual ids, listed for the tool call
    expect(prompt).toContain("- [a] rectangle @(10,20)：“登录”"); // structured part kept
  });

  it("pure visual: board_read instruction with no structured section", () => {
    const prompt = organizeSelectionPrompt(mixedScene, ["d", "img"]);
    expect(prompt).toContain("board_read");
    expect(prompt).not.toContain("结构化元素");
  });
});

describe("implementSelectionPrompt", () => {
  it("frames the selection as a brief and asks the CEO to lead the team + implement", () => {
    const prompt = implementSelectionPrompt(scene, ["a"]);
    expect(prompt).toContain("brief");
    expect(prompt).toContain("团队");
    expect(prompt).toContain("CEO");
    // structured element is embedded as a real-id requirement line
    expect(prompt).toContain("- [a] rectangle @(10,21)：“登录”");
    expect(prompt).toContain("需求要点");
    // no visual ids → no board_read instruction
    expect(prompt).not.toContain("board_read");
  });

  it("mixed: tells the CEO to board_read the visual ids before acting, keeps structured", () => {
    const prompt = implementSelectionPrompt(mixedScene, ["a", "d", "img"]);
    expect(prompt).toContain("board_read");
    expect(prompt).toContain("d、img");
    expect(prompt).toContain("- [a] rectangle @(10,20)：“登录”");
  });

  it("pure visual: board_read instruction with no structured requirement section", () => {
    const prompt = implementSelectionPrompt(mixedScene, ["d", "img"]);
    expect(prompt).toContain("board_read");
    expect(prompt).not.toContain("需求要点");
  });
});

const artifactScene: SceneElement[] = [
  el({
    id: "art1",
    type: "artifactCard",
    x: 0,
    y: 0,
    title: "工程师 · 产物",
    text: "v1 内容",
  }),
  el({ id: "note", type: "text", x: 300, y: 0, text: "把标题改大" }),
  el({ id: "draw", type: "freedraw", x: 0, y: 0 }),
];

describe("iterateArtifactPrompt", () => {
  it("feeds the previous product back and asks for a new version, not an overwrite", () => {
    const prompt = iterateArtifactPrompt(artifactScene, ["art1"]);
    expect(prompt).toContain("上一版产物");
    expect(prompt).toContain("工程师 · 产物");
    expect(prompt).toContain("v1 内容");
    expect(prompt).toContain("别覆盖旧版");
    // artifactCard alone → no annotations → the self-judge fallback line
    expect(prompt).toContain("没给额外批注");
  });

  it("includes structured annotations as the change request", () => {
    const prompt = iterateArtifactPrompt(artifactScene, ["art1", "note"]);
    expect(prompt).toContain("修改意见");
    expect(prompt).toContain("- [note] text @(300,0)：“把标题改大”");
    expect(prompt).not.toContain("没给额外批注");
  });

  it("routes hand-drawn annotations through board_read", () => {
    const prompt = iterateArtifactPrompt(artifactScene, ["art1", "draw"]);
    expect(prompt).toContain("board_read");
    expect(prompt).toContain("draw");
    expect(prompt).not.toContain("没给额外批注");
  });

  it("feeds back multiple previous products", () => {
    const scene2: SceneElement[] = [
      el({ id: "art1", type: "artifactCard", title: "A", text: "x" }),
      el({ id: "art2", type: "artifactCard", title: "B", text: "y" }),
    ];
    const prompt = iterateArtifactPrompt(scene2, ["art1", "art2"]);
    expect(prompt).toContain("【A】");
    expect(prompt).toContain("【B】");
  });
});
