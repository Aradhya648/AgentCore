import { describe, expect, it } from "vitest";
import { fitToWorkArea } from "../window-frame";

describe("fitToWorkArea", () => {
  it("returns the same size when it already fits", () => {
    expect(fitToWorkArea(1280, 720, { width: 1920, height: 1080 })).toEqual({
      width: 1280,
      height: 720,
    });
  });

  it("scales down proportionally when larger than the work area", () => {
    const fitted = fitToWorkArea(1920, 1080, { width: 1366, height: 768 });
    expect(fitted.width).toBeLessThanOrEqual(1366);
    expect(fitted.height).toBeLessThanOrEqual(768);
    expect(fitted.width / fitted.height).toBeCloseTo(16 / 9, 2);
  });
});
