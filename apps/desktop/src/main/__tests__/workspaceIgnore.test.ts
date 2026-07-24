import { describe, expect, it } from "vitest";
import {
  AI_NOISE_FILE_SUFFIXES,
  LIST_FILES_SKIP_DIRS,
  SYSTEM_IGNORED_FILE_SUFFIXES,
  shouldSkipAiNoiseFileName,
  shouldSkipDirName,
  shouldSkipFileName,
  shouldSkipSystemFileName,
  shouldSkipSystemWorkspaceEntry,
  shouldSkipWorkspaceEntry,
} from "../fs/workspaceIgnore";

describe("workspaceIgnore", () => {
  it("skips system and dependency directories (aligned with server IGNORED_DIRS)", () => {
    expect(shouldSkipDirName(".agentcore")).toBe(true);
    expect(shouldSkipDirName(".git")).toBe(true);
    expect(shouldSkipDirName("node_modules")).toBe(true);
    expect(shouldSkipDirName(".mypy_cache")).toBe(true);
    expect(shouldSkipDirName(".turbo")).toBe(true);
    expect(shouldSkipDirName("coverage")).toBe(true);
    expect(shouldSkipDirName(".idea")).toBe(true);
    expect(shouldSkipDirName(".vscode")).toBe(true);
    expect(shouldSkipDirName("src")).toBe(false);
    expect(LIST_FILES_SKIP_DIRS.has(".github")).toBe(false);
  });

  it("system suffixes hide from UI and AI", () => {
    expect(SYSTEM_IGNORED_FILE_SUFFIXES).toContain(".db");
    expect(SYSTEM_IGNORED_FILE_SUFFIXES).toContain(".sqlite");
    expect(shouldSkipSystemFileName("code_search.db")).toBe(true);
    expect(shouldSkipSystemFileName("CODE_SEARCH.DB")).toBe(true);
    expect(shouldSkipSystemFileName("foo.pyc")).toBe(true);
    expect(shouldSkipSystemFileName("photo.png")).toBe(false);
    expect(shouldSkipSystemFileName("readme.md")).toBe(false);
  });

  it("AI noise covers media/archives/binaries but not system indexes", () => {
    expect(AI_NOISE_FILE_SUFFIXES).toContain(".png");
    expect(AI_NOISE_FILE_SUFFIXES).toContain(".zip");
    expect(AI_NOISE_FILE_SUFFIXES).toContain(".pack");
    expect(shouldSkipAiNoiseFileName("photo.PNG")).toBe(true);
    expect(shouldSkipAiNoiseFileName("out.zip")).toBe(true);
    expect(shouldSkipAiNoiseFileName("code_search.db")).toBe(false);
    expect(shouldSkipAiNoiseFileName("report.pdf")).toBe(false);
  });

  it("AI combined skip includes both tiers", () => {
    expect(shouldSkipFileName("code_search.db")).toBe(true);
    expect(shouldSkipFileName("foo.pyc")).toBe(true);
    expect(shouldSkipFileName("photo.png")).toBe(true);
    expect(shouldSkipFileName("readme.md")).toBe(false);
    expect(shouldSkipFileName("data.json")).toBe(false);
  });

  it("dispatches UI vs AI entry helpers", () => {
    expect(shouldSkipWorkspaceEntry(".agentcore", true)).toBe(true);
    expect(shouldSkipWorkspaceEntry("code_search.db", false)).toBe(true);
    expect(shouldSkipWorkspaceEntry("hero.png", false)).toBe(true);
    expect(shouldSkipWorkspaceEntry("notes.md", false)).toBe(false);

    expect(shouldSkipSystemWorkspaceEntry(".agentcore", true)).toBe(true);
    expect(shouldSkipSystemWorkspaceEntry("code_search.db", false)).toBe(true);
    expect(shouldSkipSystemWorkspaceEntry("hero.png", false)).toBe(false);
    expect(shouldSkipSystemWorkspaceEntry("notes.md", false)).toBe(false);
  });
});
