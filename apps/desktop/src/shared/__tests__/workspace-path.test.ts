import { describe, expect, it } from "vitest";
import {
  normalizeWorkspacePath,
  stripRootLabelPrefix,
  toWorkspaceRelPath,
} from "../workspace-path";

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

describe("normalizeWorkspacePath", () => {
  it("maps bare root aliases to .", () => {
    expect(normalizeWorkspacePath("/")).toBe(".");
    expect(normalizeWorkspacePath("\\")).toBe(".");
    expect(normalizeWorkspacePath("")).toBe(".");
    expect(normalizeWorkspacePath(".")).toBe(".");
  });

  it("strips root label and rejects other absolutes verbatim", () => {
    expect(normalizeWorkspacePath("/workspace/foo.md")).toBe("foo.md");
    expect(normalizeWorkspacePath("/etc/passwd")).toBe("/etc/passwd");
  });
});

describe("toWorkspaceRelPath", () => {
  it("normalizes sandbox absolutes and drops bare root", () => {
    expect(toWorkspaceRelPath("/workspace/index.html")).toBe("index.html");
    expect(toWorkspaceRelPath("/workspace")).toBe("");
    expect(toWorkspaceRelPath("/")).toBe("");
    expect(toWorkspaceRelPath("")).toBe("");
  });
});
