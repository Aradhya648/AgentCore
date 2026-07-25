// @vitest-environment jsdom
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { FileBrowser } from "../FileBrowser";

vi.mock("@/api/client", () => ({
  getTokens: () => ({ access: "t" }),
}));

describe("FileBrowser stage dir badges", () => {
  it("约定案卷目录显示徽章，普通目录零噪音", async () => {
    const source = {
      list: async () => [
        { path: "AgentCore", is_dir: true },
        { path: "AgentCore/文档", is_dir: true },
        { path: "AgentCore/文档/research", is_dir: true },
        { path: "AgentCore/文档/research/a.md", is_dir: false },
        { path: "AgentCore/文档/research/b.md", is_dir: false },
        { path: "AgentCore/文档/debate", is_dir: true },
        { path: "AgentCore/文档/debate/x.md", is_dir: false },
        { path: "src", is_dir: true },
      ],
      download: vi.fn(),
    };
    render(
      <MemoryRouter>
        <FileBrowser
          source={source}
          cwd="AgentCore/文档"
          onCwdChange={() => {}}
        />
      </MemoryRouter>,
    );
    await waitFor(() => {
      expect(screen.getByText("调研案卷 · 2 件")).toBeTruthy();
      expect(screen.getByText("辩论产物 · 1 件")).toBeTruthy();
    });
    expect(screen.queryByText(/src.*件/)).toBeNull();
  });
});
