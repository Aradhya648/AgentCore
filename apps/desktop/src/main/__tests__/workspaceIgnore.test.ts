import { describe, expect, it } from "vitest";
import {
  AGENTCORE_ROOT,
  INDEX_REL,
  LIST_FILES_SKIP_DIRS,
  isInternalZoneRelPath,
  shouldSkipAiNoiseFileName,
  shouldSkipDirName,
  shouldSkipFileName,
  shouldSkipSystemFileName,
  shouldSkipSystemWorkspaceEntry,
  shouldSkipWorkspaceEntry,
} from "../fs/workspaceIgnore";

describe("workspaceIgnore", () => {
  it("skips system and dependency directories (aligned with server IGNORED_DIRS)", () => {
    expect(shouldSkipDirName(".agentcore")).toBe(false);
    expect(shouldSkipDirName(".git")).toBe(true);
    expect(shouldSkipDirName("node_modules")).toBe(true);
    expect(shouldSkipDirName(".mypy_cache")).toBe(true);
    expect(shouldSkipDirName(".turbo")).toBe(true);
    expect(shouldSkipDirName("coverage")).toBe(true);
    expect(shouldSkipDirName(".idea")).toBe(true);
    expect(shouldSkipDirName(".vscode")).toBe(true);
    expect(shouldSkipDirName("src")).toBe(false);
    expect(shouldSkipDirName("index")).toBe(false);
    expect(LIST_FILES_SKIP_DIRS.has(".github")).toBe(false);
    expect(LIST_FILES_SKIP_DIRS.has("index")).toBe(false);
  });

  it("path-aware internal zones under AgentCore only", () => {
    expect(isInternalZoneRelPath(INDEX_REL)).toBe(true);
    expect(isInternalZoneRelPath(`${AGENTCORE_ROOT}/trash/x`)).toBe(true);
    expect(isInternalZoneRelPath(`${AGENTCORE_ROOT}/baselines/m.zip`)).toBe(
      true,
    );
    expect(isInternalZoneRelPath(AGENTCORE_ROOT)).toBe(false);
    expect(isInternalZoneRelPath(`${AGENTCORE_ROOT}/规则/x.md`)).toBe(false);
    expect(shouldSkipDirName("index", AGENTCORE_ROOT)).toBe(true);
    expect(shouldSkipDirName("规则", AGENTCORE_ROOT)).toBe(false);
    expect(shouldSkipDirName("index", "")).toBe(false);
  });

  it("skips system file suffixes (UI + AI)", () => {
    expect(shouldSkipSystemFileName("code_search.db")).toBe(true);
    expect(shouldSkipSystemFileName("CODE_SEARCH.DB")).toBe(true);
    expect(shouldSkipSystemFileName("foo.pyc")).toBe(true);
    expect(shouldSkipSystemFileName("photo.png")).toBe(false);
    expect(shouldSkipSystemFileName("readme.md")).toBe(false);
  });

  it("AI noise covers media/archives; not system .db", () => {
    expect(shouldSkipAiNoiseFileName("hero.png")).toBe(true);
    expect(shouldSkipAiNoiseFileName("out.zip")).toBe(true);
    expect(shouldSkipAiNoiseFileName("code_search.db")).toBe(false);
    expect(shouldSkipFileName("hero.png")).toBe(true);
    expect(shouldSkipFileName("code_search.db")).toBe(true);
  });

  it("workspace entry helpers respect the two tiers", () => {
    expect(shouldSkipWorkspaceEntry(".git", true)).toBe(true);
    expect(shouldSkipWorkspaceEntry("index", true, AGENTCORE_ROOT)).toBe(true);
    expect(shouldSkipWorkspaceEntry("code_search.db", false)).toBe(true);
    expect(shouldSkipWorkspaceEntry("hero.png", false)).toBe(true);
    expect(shouldSkipWorkspaceEntry("notes.md", false)).toBe(false);

    expect(shouldSkipSystemWorkspaceEntry(".git", true)).toBe(true);
    expect(shouldSkipSystemWorkspaceEntry("index", true, AGENTCORE_ROOT)).toBe(
      true,
    );
    expect(shouldSkipSystemWorkspaceEntry("code_search.db", false)).toBe(true);
    expect(shouldSkipSystemWorkspaceEntry("hero.png", false)).toBe(false);
    expect(shouldSkipSystemWorkspaceEntry("notes.md", false)).toBe(false);
  });
});
