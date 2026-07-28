// @vitest-environment jsdom
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { LoginPage } from "../LoginPage";

const login = vi.fn();
const register = vi.fn();
const setAuthenticated = vi.fn();
const cacheShellMeta = vi.fn();
const persistAgentTownSession = vi.fn();

vi.mock("@/services/auth", () => ({
  login: (...args: unknown[]) => login(...args),
  register: (...args: unknown[]) => register(...args),
}));

vi.mock("@/services/agentTownSession", () => ({
  persistAgentTownSession: (...args: unknown[]) =>
    persistAgentTownSession(...args),
}));

vi.mock("@/services/offlineCache", () => ({
  cacheShellMeta: (...args: unknown[]) => cacheShellMeta(...args),
}));

vi.mock("@/stores/auth", () => ({
  useAuthStore: (
    sel: (s: { setAuthenticated: typeof setAuthenticated }) => unknown,
  ) => sel({ setAuthenticated }),
}));

afterEach(cleanup);

describe("LoginPage legal gates", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("requires age and agreement checkboxes before register submit enables", () => {
    render(<LoginPage />);

    fireEvent.click(screen.getByRole("button", { name: "注册" }));
    fireEvent.change(screen.getByPlaceholderText("用户名"), {
      target: { value: "alice" },
    });
    fireEvent.change(screen.getByPlaceholderText("密码（至少 8 位）"), {
      target: { value: "password1" },
    });

    const submit = screen.getByRole("button", { name: "注册并登录" });
    expect(submit).toHaveProperty("disabled", true);

    const checks = screen.getAllByRole("checkbox");
    expect(checks).toHaveLength(2);
    fireEvent.click(checks[0]);
    expect(submit).toHaveProperty("disabled", true);
    fireEvent.click(checks[1]);
    expect(submit).toHaveProperty("disabled", false);
  });

  it("opens user agreement pane from footer", () => {
    render(<LoginPage />);

    fireEvent.click(screen.getByRole("button", { name: "用户协议" }));
    expect(screen.getByRole("heading", { name: "用户服务协议" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /返回/ }));
    expect(screen.getByPlaceholderText("用户名")).toBeTruthy();
  });

  it("writes offline shell user via cacheShellMeta after password login", async () => {
    const user = {
      id: "u1",
      username: "alice",
      displayName: "Alice",
      email: null,
      role: "user",
      avatarUrl: null,
    };
    login.mockResolvedValue(user);

    render(<LoginPage />);
    fireEvent.change(screen.getByPlaceholderText("用户名"), {
      target: { value: "alice" },
    });
    fireEvent.change(screen.getByPlaceholderText("密码"), {
      target: { value: "secret" },
    });
    const form = screen.getByPlaceholderText("用户名").closest("form");
    expect(form).not.toBeNull();
    if (!form) throw new Error("expected login form");
    fireEvent.submit(form);

    await waitFor(() => {
      expect(setAuthenticated).toHaveBeenCalledWith(user);
      expect(cacheShellMeta).toHaveBeenCalledWith({ user });
    });
  });
});
