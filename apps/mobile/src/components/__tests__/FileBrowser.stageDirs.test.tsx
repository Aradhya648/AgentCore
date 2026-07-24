// @vitest-environment jsdom
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { FileBrowser } from "../FileBrowser";

vi.mock("@/api/client", () => ({
  getTokens: () => ({ access: "t" }),
}));

describe("FileBrowser stage dir badges", () => {
  it("根级 research/debate 显示徽章，普通目录零噪音", async () => {
    const source = {
      list: async () => [
        { path: "research", is_dir: true },
        { path: "research/a.md", is_dir: false },
        { path: "research/b.md", is_dir: false },
        { path: "debate", is_dir: true },
        { path: "debate/x.md", is_dir: false },
        { path: "src", is_dir: true },
      ],
      download: vi.fn(),
    };
    render(
      <MemoryRouter>
        <FileBrowser source={source} cwd="" onCwdChange={() => {}} />
      </MemoryRouter>,
    );
    await waitFor(() => {
      expect(screen.getByText("调研案卷 · 2 件")).toBeTruthy();
      expect(screen.getByText("辩论产物 · 1 件")).toBeTruthy();
    });
    expect(screen.queryByText(/src.*件/)).toBeNull();
    expect(screen.getByText("src")).toBeTruthy();
  });
});
