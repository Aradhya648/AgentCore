// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ConversationHydrateOverlay } from "../ConversationHydrateOverlay";

afterEach(cleanup);

describe("ConversationHydrateOverlay", () => {
  it("renders nothing when ready", () => {
    const { container } = render(
      <ConversationHydrateOverlay phase="ready" />,
    );
    expect(container.firstChild).toBeNull();
  });

  it("shows loading skeleton while hydrating", () => {
    render(<ConversationHydrateOverlay phase="loading" />);
    expect(screen.getByRole("status", { name: "正在加载对话" })).toBeTruthy();
    expect(screen.getByText("正在加载对话…")).toBeTruthy();
  });

  it("shows error + retry when hydrate failed", () => {
    const onRetry = vi.fn();
    render(
      <ConversationHydrateOverlay phase="error" onRetry={onRetry} />,
    );
    expect(screen.getByRole("alert")).toBeTruthy();
    expect(screen.getByText("对话加载失败")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "重试" }));
    expect(onRetry).toHaveBeenCalledOnce();
  });
});
