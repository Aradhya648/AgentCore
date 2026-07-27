// @vitest-environment jsdom
import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryUpdateCard } from "../MemoryUpdateCard";

const navigate = vi.fn();

vi.mock("@/stores/disclosure", () => ({
  usePersistentDisclosure: () => [true, vi.fn()],
}));

vi.mock("@/hooks/useConversations", () => ({
  getConversations: () => [{ id: "c1", folderId: "F99", title: "t" }],
}));

vi.mock("@/hooks/useFolders", () => ({
  getFolders: () => [{ id: "F99", name: "白板" }],
}));

vi.mock("@/stores/conversation", async () => {
  const actual = await vi.importActual<typeof import("@/stores/conversation")>(
    "@/stores/conversation",
  );
  return {
    ...actual,
    useConversationStore: (
      sel: (s: { currentConversationId: string }) => unknown,
    ) => sel({ currentConversationId: "c1" }),
  };
});

vi.mock("react-router-dom", async () => {
  const actual =
    await vi.importActual<typeof import("react-router-dom")>(
      "react-router-dom",
    );
  return {
    ...actual,
    useNavigate: () => navigate,
  };
});

describe("MemoryUpdateCard", () => {
  beforeEach(() => {
    navigate.mockClear();
  });

  it("renders episodic light tip from summary", () => {
    render(
      <MemoryRouter>
        <MemoryUpdateCard
          update={{
            id: "e1",
            createdAt: "2026-07-19T12:00:00Z",
            kind: "episodic",
            summary: "本场讨论了用 pnpm 管理依赖。",
            items: [],
          }}
        />
      </MemoryRouter>,
    );
    expect(screen.getByText("已记下本场摘要")).toBeTruthy();
    expect(screen.getByText(/pnpm/)).toBeTruthy();
  });

  it("renders semantic diff card with scope overview and project pill", () => {
    render(
      <MemoryRouter>
        <MemoryUpdateCard
          update={{
            id: "s1",
            createdAt: "2026-07-19T12:00:00Z",
            kind: "semantic",
            items: [
              {
                action: "add",
                file: "画像",
                section: "关于用户的事实",
                scope: "global",
                content: "倾向使用 bun",
                target: "global/profile",
              },
              {
                action: "add",
                file: "画像",
                section: "技术栈与工具",
                scope: "project",
                content: "本项目用 Vite",
                target: "project/F99/profile",
                projectId: "F99",
              },
            ],
          }}
        />
      </MemoryRouter>,
    );
    expect(screen.getByText(/记忆已更新 · 全局 \+ 本项目 · 白板/)).toBeTruthy();
    expect(screen.getByText("2 项")).toBeTruthy();
    expect(screen.getByText("本项目 · 白板")).toBeTruthy();
    expect(screen.getByText("移到本项目")).toBeTruthy();
    expect(screen.getByText("移到全局")).toBeTruthy();
  });

  it("falls back to projectId when target does not encode folderId", () => {
    render(
      <MemoryRouter>
        <MemoryUpdateCard
          update={{
            id: "s2",
            createdAt: "2026-07-19T12:00:00Z",
            kind: "semantic",
            items: [
              {
                action: "add",
                file: "画像",
                section: "关于用户的事实",
                scope: "project",
                content: "本项目用 React",
                target: "broken-target",
                projectId: "F99",
              },
            ],
          }}
        />
      </MemoryRouter>,
    );
    fireEvent.click(screen.getByTitle("在「AI 记忆」中打开画像"));
    expect(navigate).toHaveBeenCalledWith("/files", {
      state: {
        openMemoryLeaf: {
          path: "broken-target",
          name: "画像.md",
          projectId: "F99",
        },
        focusWsId: "folder:F99",
      },
    });
  });
});
