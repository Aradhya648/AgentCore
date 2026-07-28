// @vitest-environment jsdom
import { RECONNECT_BANNER } from "@/services/turns/helpers";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { RetryBanner } from "../RetryBanner";

const clearError = vi.fn();
const retry = vi.fn();
let error: string | null = null;
let hasRetry = true;

vi.mock("@/stores/conversation", () => ({
  useActiveError: () => error,
  useActiveRetry: () => (hasRetry ? retry : null),
  useActiveErrorAction: () => null,
  useConversationStore: (
    sel: (s: { clearError: typeof clearError }) => unknown,
  ) => sel({ clearError }),
}));

vi.mock("react-router-dom", () => ({
  useNavigate: () => vi.fn(),
}));

afterEach(() => {
  cleanup();
  clearError.mockReset();
  retry.mockReset();
  error = null;
  hasRetry = true;
});

describe("RetryBanner reconnect label", () => {
  it("shows 重连 when the banner is the reconnect drop copy", () => {
    error = RECONNECT_BANNER;
    render(<RetryBanner />);
    expect(screen.getByRole("button", { name: "重连" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "重试" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "重连" }));
    expect(retry).toHaveBeenCalledOnce();
  });

  it("keeps 重试 for other retryable failures", () => {
    error = "发送失败，请稍后重试";
    render(<RetryBanner />);
    expect(screen.getByRole("button", { name: "重试" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "重连" })).toBeNull();
  });
});
