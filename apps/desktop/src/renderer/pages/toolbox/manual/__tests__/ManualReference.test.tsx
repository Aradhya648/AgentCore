// @vitest-environment jsdom
import { ManualReference } from "@/pages/toolbox/manual/ManualReference";
import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it } from "vitest";

afterEach(cleanup);

function renderReference(initial = "/toolbox/manual/reference") {
  return render(
    <MemoryRouter initialEntries={[initial]}>
      <ManualReference />
    </MemoryRouter>,
  );
}

describe("ManualReference", () => {
  it("renders Phase 2 workspace dual-mode copy", () => {
    renderReference();
    expect(screen.getByText("工作区与文件")).toBeTruthy();
    expect(screen.getByText(/绑本地文件夹/)).toBeTruthy();
    expect(screen.getByText(/不绑 → 云端项目/)).toBeTruthy();
    expect(screen.getByText(/模式条/)).toBeTruthy();
    expect(screen.getAllByText(/项目即工作区/).length).toBeGreaterThan(0);
    expect(screen.getByText(/右坞终端/)).toBeTruthy();
  });

  it("renders Git boundary table in FAQ", () => {
    renderReference();
    expect(screen.getByText("Agent 对 Git / 代码能做什么？")).toBeTruthy();
    expect(screen.getByText("会做")).toBeTruthy();
    expect(screen.getByText("需你放行")).toBeTruthy();
    expect(screen.getByText("不会做")).toBeTruthy();
    expect(screen.getByText("读文件；git status / diff / log")).toBeTruthy();
    expect(screen.getByText(/force push/)).toBeTruthy();
  });

  it("renders feedback FAQ and privacy context", () => {
    renderReference();
    expect(screen.getByText("怎么给产品提意见？")).toBeTruthy();
    expect(screen.getByText(/不含工作区里的文件内容/)).toBeTruthy();
    expect(screen.getByText("反馈附带的上下文")).toBeTruthy();
  });

  it("exposes preview markers for section deep links", () => {
    const { container } = renderReference(
      "/toolbox/manual/reference?s=workspace",
    );
    const root = container.querySelector(
      '[data-preview-manual="manual-reference"]',
    );
    expect(root?.getAttribute("data-preview-section")).toBe("workspace");
  });

  it("marks upcoming tools and BYOK model FAQ", () => {
    renderReference();
    expect(screen.getByText(/MCP（规划中）/)).toBeTruthy();
    expect(screen.getByText(/A2A（规划中）/)).toBeTruthy();
    expect(screen.getByText(/其他创作工具（即将上线）/)).toBeTruthy();
    expect(screen.getByText(/白板（已可用）/)).toBeTruthy();
    expect(screen.getByText("用的什么模型？")).toBeTruthy();
    expect(screen.getByText(/OpenAI \/ DeepSeek \/ Kimi \/ 智谱/)).toBeTruthy();
    expect(screen.getByText("画布和白板有什么区别？")).toBeTruthy();
  });

  it("links duplicate FAQ answers to collaboration chapter", () => {
    renderReference();
    expect(screen.getByText("怎么强制多人干？")).toBeTruthy();
    expect(screen.getByText("怎么下任务")).toBeTruthy();
    expect(screen.getByText("检查点怎么答？")).toBeTruthy();
    expect(screen.getByText("检查点与审批")).toBeTruthy();
    expect(screen.getByText("跑偏了 / 中途想改方向？")).toBeTruthy();
    expect(screen.getByText("中途接管")).toBeTruthy();
  });

  it("renders settings rows including memory and autonomy", () => {
    renderReference();
    expect(screen.getByText("AI 记忆")).toBeTruthy();
    expect(screen.getAllByText("自主度").length).toBeGreaterThanOrEqual(1);
  });

  it("renders glossary terms aligned with product glossary", () => {
    renderReference();
    expect(screen.getByText("队员")).toBeTruthy();
    expect(screen.getByText("放行")).toBeTruthy();
    expect(screen.getByText("已停止")).toBeTruthy();
    expect(screen.getByText("重新生成")).toBeTruthy();
    expect(screen.getByText("带现场续派（同人接续）")).toBeTruthy();
    expect(screen.getByText("辩论室")).toBeTruthy();
    expect(screen.getByText("接续链")).toBeTruthy();
    expect(screen.getByText("站队")).toBeTruthy();
    expect(screen.getAllByText("画布").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("白板").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("自主度").length).toBeGreaterThanOrEqual(1);
  });
});
