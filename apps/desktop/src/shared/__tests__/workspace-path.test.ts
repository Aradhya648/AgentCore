import { describe, expect, it } from "vitest";
import { stripRootLabelPrefix, toWorkspaceRelPath } from "../workspace-path";

describe("stripRootLabelPrefix", () => {
  it("rewrites /workspace/… absolutes to relative", () => {
    expect(stripRootLabelPrefix("/workspace/foo/bar.md")).toBe("foo/bar.md");
    expect(stripRootLabelPrefix("/workspace")).toBe(".");
    expect(stripRootLabelPrefix("/workspace/")).toBe(".");
  });

  it("leaves relative and other-root paths unchanged", () => {
    expect(stripRootLabelPrefix("workspace/foo")).toBe("workspace/foo");
    expect(stripRootLabelPrefix("index.html")).toBe("index.html");
    expect(stripRootLabelPrefix("/etc/passwd")).toBe("/etc/passwd");
  });
});

describe("toWorkspaceRelPath", () => {
  it("normalizes sandbox absolutes and drops bare root", () => {
    expect(toWorkspaceRelPath("/workspace/index.html")).toBe("index.html");
    expect(toWorkspaceRelPath("/workspace")).toBe("");
    expect(toWorkspaceRelPath("")).toBe("");
  });
});
