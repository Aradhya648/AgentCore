// @vitest-environment jsdom
/**
 * Soft drop-error lifecycle: auto-dismiss must survive parent re-renders
 * (the old TurnComposer effect cleared the timer whenever `drop` identity changed).
 */

import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/capabilities", () => ({
  hasLocalFiles: () => true,
}));

vi.mock("../resideAttachment", () => ({
  stageDroppedFileAttachment: vi.fn(),
}));

import { stageDroppedFileAttachment } from "../resideAttachment";
import { useComposerDrop } from "../useComposerDrop";

const stageMock = vi.mocked(stageDroppedFileAttachment);

function fileNamed(name: string): File {
  return new File(["x"], name, { type: "text/plain" });
}

describe("useComposerDrop dropError lifecycle", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    stageMock.mockReset();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("auto-dismisses soft drop errors after 4s (not stuck across re-renders)", async () => {
    stageMock.mockResolvedValue({
      ok: false,
      reason: "无法读取拖入的文件，请改用回形针选择",
    });
    const setAttachments = vi.fn();
    const { result, rerender } = renderHook(() =>
      useComposerDrop(false, [], setAttachments, null),
    );

    const dropEvent = {
      dataTransfer: {
        types: ["Files"],
        items: [
          {
            kind: "file",
            webkitGetAsEntry: () => ({ isDirectory: false }),
            getAsFile: () => fileNamed("a.txt"),
          },
        ],
        files: [fileNamed("a.txt")],
      },
      preventDefault: vi.fn(),
    } as unknown as React.DragEvent;

    await act(async () => {
      await result.current.handleDrop(dropEvent);
    });
    expect(result.current.dropError).toBe(
      "无法读取拖入的文件，请改用回形针选择",
    );

    // Simulate parent re-render (new drop object identity) — must NOT cancel timer.
    rerender();
    expect(result.current.dropError).toBe(
      "无法读取拖入的文件，请改用回形针选择",
    );

    await act(async () => {
      vi.advanceTimersByTime(4000);
    });
    expect(result.current.dropError).toBeNull();
  });

  it("clearDropError dismisses immediately", async () => {
    stageMock.mockResolvedValue({ ok: false, reason: "失败" });
    const { result } = renderHook(() =>
      useComposerDrop(false, [], vi.fn(), null),
    );
    const dropEvent = {
      dataTransfer: {
        types: ["Files"],
        items: [],
        files: [fileNamed("b.txt")],
      },
      preventDefault: vi.fn(),
    } as unknown as React.DragEvent;

    await act(async () => {
      await result.current.handleDrop(dropEvent);
    });
    expect(result.current.dropError).toBe("失败");

    act(() => {
      result.current.clearDropError();
    });
    expect(result.current.dropError).toBeNull();
  });
});
