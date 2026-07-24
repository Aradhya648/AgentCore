import { parseScene, serializeScene } from "@/whiteboard";
import { describe, expect, it } from "vitest";
import { WHITEBOARD_SCENES, fileArtifactKindOf } from "../whiteboardScenes";

describe("WHITEBOARD_SCENES", () => {
  it("exposes scenes with unique ids and non-empty elements", () => {
    expect(WHITEBOARD_SCENES.length).toBeGreaterThan(0);
    const ids = WHITEBOARD_SCENES.map((s) => s.id);
    expect(new Set(ids).size).toBe(ids.length);
    for (const s of WHITEBOARD_SCENES) {
      expect(s.elements.length).toBeGreaterThan(0);
    }
  });

  it("each scene is an exportable board vector (round-trips through serialize/parse)", () => {
    for (const s of WHITEBOARD_SCENES) {
      const parsed = parseScene(serializeScene(s.elements));
      expect(parsed.elements.length).toBe(s.elements.length);
    }
  });

  it("crystallized team scene carries agent nodes + a product card (real projector)", () => {
    const scene = WHITEBOARD_SCENES.find(
      (s) => s.id === "board_crystallized_team",
    );
    expect(scene).toBeDefined();
    expect(scene?.elements.some((e) => e.type === "agentNode")).toBe(true);
    expect(scene?.elements.some((e) => e.type === "artifactCard")).toBe(true);
  });

  it("progress overlay scene projects status-bearing cards", () => {
    const scene = WHITEBOARD_SCENES.find(
      (s) => s.id === "board_progress_overlay",
    );
    expect(scene?.elements.some((e) => e.runStatus != null)).toBe(true);
  });

  it("file artifact scene keeps artifactKind=file with a ref (WB-003)", () => {
    const scene = WHITEBOARD_SCENES.find((s) => s.id === "board_file_artifact");
    expect(scene).toBeDefined();
    if (scene) expect(fileArtifactKindOf(scene)).toBe("file");
    const card = scene?.elements.find(
      (e) => e.type === "artifactCard" && e.ref,
    );
    expect(card?.ref).toContain("竞品分析.md");
  });

  it("rotation scene has a rotated, preselected element (WB-007)", () => {
    const scene = WHITEBOARD_SCENES.find((s) => s.id === "board_rotation");
    const rotated = scene?.elements.find((e) => (e.rotation ?? 0) !== 0);
    expect(rotated).toBeDefined();
    expect(scene?.selectedIds).toContain(rotated?.id);
  });

  it("dagre scene spreads chained nodes left-to-right (real layout)", () => {
    const scene = WHITEBOARD_SCENES.find((s) => s.id === "board_dagre_layout");
    const boxes = (scene?.elements ?? []).filter((e) => e.type === "rectangle");
    const xs = new Set(boxes.map((b) => Math.round(b.x)));
    // A layered layout puts nodes at multiple x ranks (not all stacked at one x).
    expect(xs.size).toBeGreaterThan(1);
  });
});
