import { describe, expect, it } from "vitest";
import { compareSemver, isDesktopVersionOutdated } from "../desktopVersion";

describe("compareSemver", () => {
  it("orders major.minor.patch", () => {
    expect(compareSemver("0.6.1", "0.6.5")).toBeLessThan(0);
    expect(compareSemver("0.6.5", "0.6.5")).toBe(0);
    expect(compareSemver("0.7.0", "0.6.5")).toBeGreaterThan(0);
  });

  it("strips pre-release suffix for the numeric core", () => {
    expect(compareSemver("0.6.5-beta", "0.6.5")).toBe(0);
  });
});

describe("isDesktopVersionOutdated", () => {
  it("returns false when min is empty or null", () => {
    expect(isDesktopVersionOutdated("0.6.1", null)).toBe(false);
    expect(isDesktopVersionOutdated("0.6.1", "")).toBe(false);
    expect(isDesktopVersionOutdated("0.6.1", "  ")).toBe(false);
  });

  it("never treats clientVersion()==='dev' as outdated", () => {
    expect(isDesktopVersionOutdated("dev", "0.6.5")).toBe(false);
  });

  it("flags local builds below the soft floor", () => {
    expect(isDesktopVersionOutdated("0.6.1", "0.6.5")).toBe(true);
    expect(isDesktopVersionOutdated("0.6.5", "0.6.5")).toBe(false);
    expect(isDesktopVersionOutdated("0.6.6", "0.6.5")).toBe(false);
  });
});
