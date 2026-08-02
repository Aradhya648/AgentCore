import { useWorkspaceChannelStore } from "@/stores/workspaceChannel";
// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { WorkspaceChannelBanner } from "../WorkspaceChannelBanner";

beforeEach(() => {
  useWorkspaceChannelStore.setState({ notReady: true });
});

afterEach(() => {
  cleanup();
  useWorkspaceChannelStore.setState({ notReady: false });
});

describe("WorkspaceChannelBanner", () => {
  it("renders soft hint when channel not ready", () => {
    render(<WorkspaceChannelBanner />);
    expect(screen.getByText(/本地文件通道未就绪/)).toBeTruthy();
    expect(screen.getByText(/重新打开应用/)).toBeTruthy();
  });

  it("hides when ready", () => {
    useWorkspaceChannelStore.setState({ notReady: false });
    const { container } = render(<WorkspaceChannelBanner />);
    expect(container.firstChild).toBeNull();
  });

  it("hides after dismiss", () => {
    render(<WorkspaceChannelBanner />);
    fireEvent.click(screen.getByRole("button", { name: "关闭" }));
    expect(screen.queryByText(/本地文件通道未就绪/)).toBeNull();
  });
});
