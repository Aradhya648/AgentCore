import type { SceneElement } from "@/whiteboard";
import { parseScene, serializeScene } from "@/whiteboard";
import { describe, expect, it } from "vitest";

const image: SceneElement = {
  id: "img1",
  type: "image",
  x: 5,
  y: 6,
  width: 100,
  height: 80,
  src: "data:image/png;base64,QUJD",
  schemaVersion: 1,
};

describe("serializeScene / parseScene", () => {
  it("round-trips an image element's src (the persisted scene keeps the picture)", () => {
    const { elements } = parseScene(serializeScene([image]));
    expect(elements).toHaveLength(1);
    expect(elements[0].type).toBe("image");
    expect(elements[0].src).toBe("data:image/png;base64,QUJD");
  });

  it("round-trips stroke width + dash style", () => {
    const styled: SceneElement = {
      id: "r1",
      type: "rectangle",
      x: 0,
      y: 0,
      width: 50,
      height: 30,
      strokeWidth: 7,
      strokeStyle: "dashed",
      schemaVersion: 1,
    };
    const { elements } = parseScene(serializeScene([styled]));
    expect(elements[0]).toMatchObject({
      strokeWidth: 7,
      strokeStyle: "dashed",
    });
  });

  it("ignores an invalid strokeStyle value", () => {
    const blob = serializeScene([image]);
    const raw = {
      ...blob,
      elements: [{ ...blob.elements[0], strokeStyle: "wavy" }] as unknown[],
    };
    const { elements } = parseScene(raw);
    expect(elements[0].strokeStyle).toBeUndefined();
  });

  it("drops a now-unknown element type but keeps the image", () => {
    const blob = serializeScene([image]);
    const raw = {
      ...blob,
      elements: [
        ...blob.elements,
        { id: "x", type: "briefRegion", x: 0, y: 0, width: 1, height: 1 },
      ] as unknown[],
    };
    const { elements } = parseScene(raw);
    expect(elements.map((e) => e.id)).toEqual(["img1"]);
  });
});
