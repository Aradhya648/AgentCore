// @vitest-environment jsdom
import { ServiceUnavailablePage } from "@/pages/ServiceUnavailablePage";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@/components/brand/BrandMark", () => ({
  BrandMark: () => <div data-testid="brand" />,
}));

afterEach(() => cleanup());

describe("ServiceUnavailablePage", () => {
  it("说明会自动重试，并保留手动重试", () => {
    const onRetry = vi.fn();
    render(<ServiceUnavailablePage reason="后端未启动" onRetry={onRetry} />);
    expect(screen.getByText("服务暂时不可用")).toBeTruthy();
    expect(screen.getByText(/正在自动重试，服务恢复后会自动进入/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "重试" }));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });
});
