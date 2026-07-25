import { describe, expect, it } from "vitest";
import { compareSemver, isAndroidVersionOutdated } from "../semver";

describe("compareSemver", () => {
  it("orders major.minor.patch", () => {
    expect(compareSemver("0.3.1", "0.3.6")).toBeLessThan(0);
    expect(compareSemver("0.3.6", "0.3.6")).toBe(0);
    expect(compareSemver("0.4.0", "0.3.6")).toBeGreaterThan(0);
  });

  it("strips pre-release suffix for the numeric core", () => {
    expect(compareSemver("0.3.6-beta", "0.3.6")).toBe(0);
  });
});

describe("isAndroidVersionOutdated", () => {
  it("returns false when remote is empty or null", () => {
    expect(isAndroidVersionOutdated("0.3.1", null)).toBe(false);
    expect(isAndroidVersionOutdated("0.3.1", "")).toBe(false);
    expect(isAndroidVersionOutdated("0.3.1", "  ")).toBe(false);
  });

  it("never treats clientVersion()==='dev' as outdated", () => {
    expect(isAndroidVersionOutdated("dev", "0.3.6")).toBe(false);
  });

  it("flags local builds below the published APK version", () => {
    expect(isAndroidVersionOutdated("0.3.1", "0.3.6")).toBe(true);
    expect(isAndroidVersionOutdated("0.3.6", "0.3.6")).toBe(false);
    expect(isAndroidVersionOutdated("0.3.7", "0.3.6")).toBe(false);
  });
});
