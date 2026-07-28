// @vitest-environment jsdom
import { TooltipProvider } from "@/components/ui/tooltip";
import { useAuthStore } from "@/stores/auth";
import { useSidebarStore } from "@/stores/sidebar";
import { useUserStore } from "@/stores/user";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { UserMenu } from "../UserMenu";

vi.mock("@/services/auth", () => ({
  logout: vi.fn().mockResolvedValue(undefined),
}));

function renderMenu() {
  return render(
    <MemoryRouter>
      <TooltipProvider>
        <UserMenu />
      </TooltipProvider>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  useSidebarStore.setState({ collapsed: false });
  useUserStore.setState({
    profile: {
      displayName: "测试用户",
      avatarUrl: null,
    } as ReturnType<typeof useUserStore.getState>["profile"],
  });
  useAuthStore.setState({
    user: {
      id: "u1",
      username: "tester",
      displayName: "测试用户",
      avatarUrl: null,
    } as ReturnType<typeof useAuthStore.getState>["user"],
  });
});

afterEach(() => {
  cleanup();
});

describe("UserMenu · 折叠可达性", () => {
  it("折叠态头像打开含设置 / 登出的菜单", async () => {
    useSidebarStore.setState({ collapsed: true });
    renderMenu();

    const trigger = screen.getByRole("button", { name: "账户菜单" });
    fireEvent.pointerDown(trigger);
    fireEvent.click(trigger);

    expect(await screen.findByText("设置")).toBeTruthy();
    expect(await screen.findByText("登出")).toBeTruthy();
  });

  it("展开态仍保留独立登出按钮", () => {
    useSidebarStore.setState({ collapsed: false });
    renderMenu();
    expect(screen.getByRole("button", { name: "登出" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "更多" })).toBeTruthy();
  });
});
