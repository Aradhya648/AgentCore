import {
  type AutonomyRecipe,
  type PermissionAxes,
  RECIPE_AXES,
  RECIPE_LABELS,
  RECIPE_ORDER,
  axesEqual,
  axesShortLabel,
  isIllegalAxes,
  matchRecipe,
  needsAutoCommandConfirm,
  normalizeAxes,
  permissionAxesShortLabel,
  recipeToAxes,
} from "@/services/permissionAxes";
import { describe, expect, it } from "vitest";

describe("permissionAxes mapping", () => {
  it("maps recipes ↔ axes", () => {
    expect(recipeToAxes("cautious")).toEqual(RECIPE_AXES.cautious);
    expect(recipeToAxes("write_code")).toEqual(RECIPE_AXES.write_code);
    expect(recipeToAxes("less_interrupt")).toEqual(RECIPE_AXES.less_interrupt);
    expect(recipeToAxes("managed")).toEqual(RECIPE_AXES.managed);
    expect(RECIPE_AXES.cautious.host).toBe("off");
    expect(RECIPE_AXES.write_code.host).toBe("ask");
    expect(RECIPE_AXES.less_interrupt.host).toBe("ask");
    expect(RECIPE_AXES.managed.host).toBe("session");
  });

  it("matches recipes and reports custom", () => {
    expect(matchRecipe(RECIPE_AXES.write_code)).toBe("write_code");
    expect(matchRecipe(RECIPE_AXES.managed)).toBe("managed");
    expect(
      matchRecipe({
        file_write: "session",
        command: "ask",
        team_kickoff: "rules",
        host: "ask",
      }),
    ).toBe("custom");
  });

  it("rejects illegal auto+ask", () => {
    expect(
      isIllegalAxes({
        file_write: "ask",
        command: "auto",
        team_kickoff: "skip",
        host: "ask",
      }),
    ).toBe(true);
    expect(isIllegalAxes(RECIPE_AXES.managed)).toBe(false);
    expect(
      normalizeAxes({
        file_write: "ask",
        command: "auto",
        team_kickoff: "skip",
        host: "ask",
      }),
    ).toEqual(RECIPE_AXES.write_code);
  });

  it("flags auto-command confirm only on enter", () => {
    expect(
      needsAutoCommandConfirm(RECIPE_AXES.write_code, RECIPE_AXES.managed),
    ).toBe(true);
    expect(
      needsAutoCommandConfirm(RECIPE_AXES.managed, RECIPE_AXES.managed),
    ).toBe(false);
    expect(
      needsAutoCommandConfirm(RECIPE_AXES.managed, RECIPE_AXES.write_code),
    ).toBe(false);
  });

  it("resolves short labels for chip / 系统行", () => {
    expect(axesShortLabel(RECIPE_AXES.cautious)).toBe("谨慎");
    expect(axesShortLabel(RECIPE_AXES.write_code)).toBe("写代码");
    expect(axesShortLabel(RECIPE_AXES.less_interrupt)).toBe("少打断");
    expect(axesShortLabel(RECIPE_AXES.managed)).toBe("托管");
    expect(
      axesShortLabel({
        file_write: "session",
        command: "ask",
        team_kickoff: "always",
        host: "ask",
      }),
    ).toBe("信任 · 每次 · 总挂 · 本机问");
    expect(
      permissionAxesShortLabel({
        file_write: "session",
        command: "ask",
        team_kickoff: "always",
        host: "ask",
      }),
    ).toBe("信任 · 每次 · 总挂 · 本机问");
    expect(permissionAxesShortLabel(RECIPE_AXES.write_code)).toBe("写代码");
    expect(permissionAxesShortLabel("write_code")).toBe("写代码");
    expect(permissionAxesShortLabel("workspace")).toBe("写代码");
    // Turn snapshot may store axes as json.dumps string — parse, don't echo JSON.
    expect(
      permissionAxesShortLabel(
        '{"file_write":"session","command":"auto","team_kickoff":"skip","host":"session"}',
      ),
    ).toBe("托管");
    expect(
      permissionAxesShortLabel(
        '{"file_write":"session","command":"kickoff","team_kickoff":"rules"}',
      ),
    ).toBe("写代码");
    expect(permissionAxesShortLabel("{not-json")).toBeNull();
    expect(permissionAxesShortLabel("bogus")).toBeNull();
    expect(permissionAxesShortLabel(null)).toBeNull();
    expect(permissionAxesShortLabel(42)).toBeNull();
  });

  it("recipe order covers all labels", () => {
    for (const id of RECIPE_ORDER) {
      expect(RECIPE_LABELS[id as AutonomyRecipe].short.length).toBeGreaterThan(
        0,
      );
      expect(axesEqual(recipeToAxes(id), RECIPE_AXES[id])).toBe(true);
    }
  });

  it("normalize fills defaults including missing host → ask", () => {
    const a: PermissionAxes = normalizeAxes({});
    expect(a).toEqual(RECIPE_AXES.write_code);
    expect(
      normalizeAxes({
        file_write: "session",
        command: "kickoff",
        team_kickoff: "rules",
      }),
    ).toEqual(RECIPE_AXES.write_code);
    expect(
      normalizeAxes({
        file_write: "ask",
        command: "ask",
        team_kickoff: "rules",
        host: "off",
      }),
    ).toEqual(RECIPE_AXES.cautious);
  });
});
