import { beforeEach, describe, expect, it } from "vitest";
import { popOverlay, pushOverlay, useOverlayStore } from "../overlay";

const count = () => useOverlayStore.getState().count;

beforeEach(() => {
  useOverlayStore.setState({ count: 0 });
});

describe("overlay obstruction counter（内嵌预览遮挡计数）", () => {
  it("push 累加、pop 递减（支持多层叠加）", () => {
    pushOverlay();
    pushOverlay();
    expect(count()).toBe(2);
    popOverlay();
    expect(count()).toBe(1);
  });

  it("pop 钳非负（防错配下越界为负）", () => {
    popOverlay();
    popOverlay();
    expect(count()).toBe(0);
  });
});
