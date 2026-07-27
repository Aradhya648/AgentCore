import { describe, expect, it, vi } from "vitest";
import {
  canMoveMemoryItem,
  memoryScopeOverview,
  memoryScopePillLabel,
} from "../MemoryUpdateItemRow";

vi.mock("@/hooks/useFolders", () => ({
  getFolders: () => [{ id: "F1", name: "AgentCore" }],
}));

describe("memory scope labels", () => {
  it("labels global and named project", () => {
    expect(memoryScopePillLabel("global")).toBe("全局");
    expect(memoryScopePillLabel("project", "F1")).toBe("本项目 · AgentCore");
    expect(memoryScopePillLabel("project", "missing")).toBe("本项目");
  });

  it("builds card scope overview across layers", () => {
    expect(
      memoryScopeOverview([
        { scope: "global" },
        { scope: "project", projectId: "F1" },
      ]),
    ).toBe("全局 + 本项目 · AgentCore");
  });
});

describe("canMoveMemoryItem", () => {
  const base = {
    action: "add",
    file: "画像",
    section: "关于用户的事实",
    content: "事实",
    target: "global/profile",
    scope: "global",
  };

  it("allows global→project for movable profile facts", () => {
    expect(canMoveMemoryItem(base, "to_project", "F1")).toBe(true);
  });

  it("blocks 纠正记录 / 偏好 / remove / missing project", () => {
    expect(
      canMoveMemoryItem(
        { ...base, section: "纠正记录" },
        "to_project",
        "F1",
      ),
    ).toBe(false);
    expect(
      canMoveMemoryItem({ ...base, file: "偏好" }, "to_project", "F1"),
    ).toBe(false);
    expect(
      canMoveMemoryItem({ ...base, action: "remove" }, "to_project", "F1"),
    ).toBe(false);
    expect(canMoveMemoryItem(base, "to_project", null)).toBe(false);
  });

  it("blocks 项目约束 → global", () => {
    expect(
      canMoveMemoryItem(
        {
          ...base,
          scope: "project",
          section: "项目约束",
          projectId: "F1",
          target: "project/F1/profile",
        },
        "to_global",
        "F1",
      ),
    ).toBe(false);
  });
});
