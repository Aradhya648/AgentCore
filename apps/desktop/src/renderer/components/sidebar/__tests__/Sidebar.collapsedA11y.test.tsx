// @vitest-environment jsdom
import { TooltipProvider } from "@/components/ui/tooltip";
import { useSidebarStore } from "@/stores/sidebar";
import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Sidebar } from "../Sidebar";

vi.mock("@/lib/newConversation", () => ({
  startNewConversation: vi.fn(),
}));

vi.mock("@/stores/messaging", () => ({
  useUnreadTotal: () => 0,
}));

vi.mock("../RecentConversations", () => ({
  RecentConversations: () => null,
  ViewAllConversations: () => null,
}));

vi.mock("../WorkspaceGroups", () => ({
  WorkspaceGroups: () => null,
}));

vi.mock("../UserMenu", () => ({
  UserMenu: () => <div data-testid="user-menu" />,
}));

vi.mock("@/lib/capabilities", () => ({
  isWebClient: () => false,
}));

function renderSidebar() {
  return render(
    <MemoryRouter>
      <TooltipProvider>
        <Sidebar />
      </TooltipProvider>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  useSidebarStore.setState({ collapsed: false });
});

afterEach(() => {
  cleanup();
});

describe("Sidebar · 折叠导航可达性", () => {
  it("折叠态主导航按钮带 aria-label", () => {
    useSidebarStore.setState({ collapsed: true });
    renderSidebar();

    expect(screen.getByRole("button", { name: "新对话" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "文件" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "消息" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "工具箱" })).toBeTruthy();
  });
});
