// @vitest-environment jsdom
/**
 * Render tests for the admin 用户管理 page (AUD-012 测试覆盖补强 · admin 半).
 *
 * UsersPage owns the roster table + row actions (改角色 / 停用·启用 / 注销 / 配额). These pin
 * its happy paths and the key self-guards with the services mocked (no real HTTP) and the
 * not-under-test leaves (UserDetail / QuotaDialog) stubbed, so the test targets the page's
 * own list rendering, self-row guarding, status toggle, empty + error/retry branches. The
 * leading block comment keeps the @vitest-environment directive file-leading.
 */

import { UsersPage } from "@/pages/UsersPage";
import {
  type AdminUser,
  type AdminUserListItem,
  type AdminUserListResponse,
  deleteUser,
  listUsers,
  updateUser,
} from "@/services/adminUsers";
import { ApiError } from "@/services/api";
import { useAuthStore } from "@/stores/auth";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { toast } from "sonner";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/services/adminUsers", () => ({
  listUsers: vi.fn(),
  updateUser: vi.fn(),
  deleteUser: vi.fn(),
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
// Not under test here — stubbed so the roster test never pulls their module graph.
vi.mock("@/components/UserDetail", () => ({
  UserDetail: () => <div data-testid="user-detail" />,
}));
vi.mock("@/components/QuotaDialog", () => ({
  QuotaDialog: () => <div data-testid="quota-dialog" />,
}));

const SELF_ID = "self-id";

beforeEach(() => {
  useAuthStore.setState({
    status: "authenticated",
    user: {
      id: SELF_ID,
      username: "admin",
      displayName: "管理员",
      email: null,
      role: "admin",
      passwordMustChange: false,
    },
  });
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

function userItem(
  p: Partial<AdminUserListItem> & { id: string },
): AdminUserListItem {
  return {
    username: "user",
    display_name: "",
    email: null,
    role: "user",
    status: "active",
    deleted_at: null,
    is_unlimited: false,
    quota_daily_tokens: null,
    quota_daily_requests: null,
    quota_monthly_cost_cny: null,
    quota_daily_cost_cny: null,
    cost_total: 0,
    created_at: "2026-06-01T00:00:00Z",
    ...p,
  };
}

function listResp(
  data: AdminUserListItem[],
  total = data.length,
): AdminUserListResponse {
  return { data, total, page: 1, page_size: 20 };
}

function renderUsers() {
  return render(
    <MemoryRouter initialEntries={["/users"]}>
      <Routes>
        <Route path="/users" element={<UsersPage />} />
        <Route path="/users/:userId" element={<UsersPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("UsersPage", () => {
  it("renders the roster from listUsers (names, self marker, count)", async () => {
    vi.mocked(listUsers).mockResolvedValue(
      listResp(
        [
          userItem({ id: SELF_ID, username: "alice", display_name: "Alice" }),
          userItem({ id: "u2", username: "bob", display_name: "Bob" }),
        ],
        2,
      ),
    );
    renderUsers();
    expect(await screen.findByText("Alice")).toBeTruthy();
    expect(screen.getByText("Bob")).toBeTruthy();
    expect(screen.getByText(/@bob/)).toBeTruthy();
    expect(screen.getByText("(我)")).toBeTruthy(); // the signed-in admin's own row
    expect(screen.getByText(/共 2 个账号/)).toBeTruthy();
  });

  it("guards self-row actions (role select + 停用 disabled for the signed-in admin)", async () => {
    vi.mocked(listUsers).mockResolvedValue(
      listResp([
        userItem({ id: SELF_ID, username: "alice", display_name: "Alice", role: "admin" }),
      ]),
    );
    renderUsers();
    await screen.findByText("Alice");
    expect((screen.getByDisplayValue("admin") as HTMLSelectElement).disabled).toBe(true);
    expect(
      (screen.getByRole("button", { name: "停用" }) as HTMLButtonElement).disabled,
    ).toBe(true);
  });

  it("停用 a non-self user → updateUser + toast + the row flips to 启用", async () => {
    vi.mocked(listUsers).mockResolvedValue(
      listResp(
        [
          userItem({ id: SELF_ID, username: "alice", display_name: "Alice", role: "admin" }),
          userItem({ id: "u2", username: "bob", display_name: "Bob" }),
        ],
        2,
      ),
    );
    vi.mocked(updateUser).mockResolvedValue({
      id: "u2",
      status: "disabled",
    } as unknown as AdminUser);
    renderUsers();
    await screen.findByText("Bob");
    // alice (self) 停用 is disabled; bob's is the enabled one.
    const enabled = screen
      .getAllByRole("button", { name: "停用" })
      .find((b) => !(b as HTMLButtonElement).disabled);
    fireEvent.click(enabled as HTMLButtonElement);
    await waitFor(() =>
      expect(updateUser).toHaveBeenCalledWith("u2", { status: "disabled" }),
    );
    expect(toast.success).toHaveBeenCalledWith("账号已停用");
    expect(await screen.findByRole("button", { name: "启用" })).toBeTruthy();
  });

  it("shows the empty state when no users match", async () => {
    vi.mocked(listUsers).mockResolvedValue(listResp([], 0));
    renderUsers();
    expect(await screen.findByText("没有匹配的用户")).toBeTruthy();
    expect(deleteUser).not.toHaveBeenCalled();
  });

  it("surfaces a load error then recovers on 重试", async () => {
    vi.mocked(listUsers)
      .mockRejectedValueOnce(
        new ApiError(500, JSON.stringify({ error: { message: "服务器开小差" } })),
      )
      .mockResolvedValue(listResp([userItem({ id: "u2", display_name: "Bob" })], 1));
    renderUsers();
    expect(await screen.findByText("服务器开小差")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "重试" }));
    expect(await screen.findByText("Bob")).toBeTruthy();
  });
});
