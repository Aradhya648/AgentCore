/**
 * Pins FILE_OP_TOOLS membership to backend ``approval_class_tool_names()``
 * （文件改动五工具 ∪ {git}）——「本轮内所有文件改动」类授权两端对齐。
 */
import { FILE_OP_TOOLS } from "@/components/PauseCard";
import { describe, expect, it } from "vitest";

describe("FILE_OP_TOOLS (aligned with backend approval_class_tool_names)", () => {
  it("covers the five file-mutation tools plus git", () => {
    expect([...FILE_OP_TOOLS].sort()).toEqual(
      [
        "file_append",
        "file_delete",
        "file_move",
        "file_write",
        "git",
        "str_replace",
      ].sort(),
    );
  });

  it("excludes execution-class tools", () => {
    expect(FILE_OP_TOOLS.has("code_execute")).toBe(false);
    expect(FILE_OP_TOOLS.has("test_run")).toBe(false);
    expect(FILE_OP_TOOLS.has("terminal")).toBe(false);
  });
});
