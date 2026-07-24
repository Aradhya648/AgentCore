// @vitest-environment jsdom

import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/capabilities", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/capabilities")>();
  return {
    ...actual,
    hasTerminalRun: vi.fn(() => true),
  };
});

import { hasTerminalRun } from "@/lib/capabilities";
import { useRunConfirmStore } from "@/stores/runConfirm";
import { CodeBlock } from "../CodeBlock";

const hasTerminalRunMock = vi.mocked(hasTerminalRun);

function mockTerminalApi(
  over?: Partial<{
    runBash: ReturnType<typeof vi.fn>;
    openShellAtRoot: ReturnType<typeof vi.fn>;
  }>,
) {
  return {
    runBash: vi.fn(async () => ({ ok: true as const })),
    openShellAtRoot: vi.fn(async () => ({ ok: true as const })),
    ...over,
  };
}

function renderBashBlock(code = "echo hello") {
  return render(
    <CodeBlock>
      <code className="language-bash">{code}</code>
    </CodeBlock>,
  );
}

beforeEach(() => {
  hasTerminalRunMock.mockReturnValue(true);
  useRunConfirmStore.getState().reset();
  window.terminalApi = mockTerminalApi();
});

afterEach(() => {
  cleanup();
  window.terminalApi = undefined;
  useRunConfirmStore.getState().reset();
});

describe("CodeBlock bash run action", () => {
  it("shows 在终端运行 for bash blocks when terminal capability is available", () => {
    renderBashBlock();
    expect(screen.getByRole("button", { name: "在终端运行" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "复制代码" })).toBeTruthy();
  });

  it("hides 在终端运行 for non-bash languages", () => {
    render(
      <CodeBlock>
        <code className="language-python">print(1)</code>
      </CodeBlock>,
    );
    expect(screen.queryByRole("button", { name: "在终端运行" })).toBeNull();
  });

  it("hides 在终端运行 when terminal capability is unavailable", () => {
    hasTerminalRunMock.mockReturnValue(false);
    renderBashBlock();
    expect(screen.queryByRole("button", { name: "在终端运行" })).toBeNull();
  });

  it("invokes terminalApi.runBash with rendererConfirmed after RunConfirm", async () => {
    const runBash = vi.fn(async () => ({ ok: true as const }));
    window.terminalApi = mockTerminalApi({ runBash });
    useRunConfirmStore.getState().markSessionAllowed();
    renderBashBlock("pnpm test");
    screen.getByRole("button", { name: "在终端运行" }).click();
    await waitFor(() => {
      expect(runBash).toHaveBeenCalledWith({
        command: "pnpm test",
        rendererConfirmed: true,
      });
    });
  });
});
