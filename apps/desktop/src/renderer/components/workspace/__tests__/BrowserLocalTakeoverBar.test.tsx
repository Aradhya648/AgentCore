// @vitest-environment jsdom
/**
 * Local 接管条：有 sessionId 点「接管」→ start 带 session_id；「归还控制」→ end；
 * 乐观并入 takeover store；pending browserLogin 归还提示对齐 EscalationCard。
 */

import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/services/browserTakeover", async (importOriginal) => {
  const actual =
    await importOriginal<typeof import("@/services/browserTakeover")>();
  return {
    ...actual,
    startBrowserTakeover: vi.fn(),
    endBrowserTakeover: vi.fn(),
  };
});

import {
  endBrowserTakeover,
  startBrowserTakeover,
} from "@/services/browserTakeover";
import { useBrowserTakeoverStore } from "@/stores/browserTakeover";
import { useConversationStore } from "@/stores/conversation";
import { useExecutionStore } from "@/stores/execution";
import { BrowserLocalTakeoverBar } from "../BrowserLocalTakeoverBar";

const mockStart = vi.mocked(startBrowserTakeover);
const mockEnd = vi.mocked(endBrowserTakeover);

beforeEach(() => {
  mockStart.mockReset().mockResolvedValue({
    active: true,
    reason: "started",
  });
  mockEnd.mockReset().mockResolvedValue(undefined);
  useBrowserTakeoverStore.setState({ byConversation: {} });
  useExecutionStore.setState({ byId: {} });
  useConversationStore.setState({
    currentConversationId: null,
    byId: {},
  });
});

afterEach(cleanup);

async function clickAsync(label: string): Promise<void> {
  await act(async () => {
    fireEvent.click(screen.getByText(label));
  });
}

describe("BrowserLocalTakeoverBar", () => {
  it("calls start with session_id on 接管", async () => {
    render(
      <BrowserLocalTakeoverBar
        conversationId="conv-1"
        sessionId="sess-local"
      />,
    );
    expect(screen.getByText("接管")).toBeTruthy();
    await clickAsync("接管");
    await waitFor(() => {
      expect(mockStart).toHaveBeenCalledWith("conv-1", {
        sessionId: "sess-local",
      });
    });
    expect(screen.getByText("归还控制")).toBeTruthy();
    expect(screen.queryByText("接管")).toBeNull();
  });

  it("calls end with session_id on 归还控制 and merges store", async () => {
    render(
      <BrowserLocalTakeoverBar
        conversationId="conv-1"
        sessionId="sess-local"
      />,
    );
    await clickAsync("接管");
    await waitFor(() => expect(screen.getByText("归还控制")).toBeTruthy());
    await clickAsync("归还控制");
    await waitFor(() => {
      expect(mockEnd).toHaveBeenCalledWith("conv-1", {
        sessionId: "sess-local",
      });
    });
    expect(screen.queryByText("归还控制")).toBeNull();
    expect(screen.getByText("控制已归还")).toBeTruthy();
    const records =
      useBrowserTakeoverStore.getState().byConversation["conv-1"] ?? [];
    expect(records).toHaveLength(1);
    expect(records[0]!.endedAt).toBeTruthy();
  });
});
