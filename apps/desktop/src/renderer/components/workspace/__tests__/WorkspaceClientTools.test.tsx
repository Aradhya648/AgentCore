// @vitest-environment jsdom

import { TooltipProvider } from "@/components/ui/tooltip";
import type { FileSource } from "@/lib/fileSource";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { WorkspaceClientTools } from "../WorkspaceClientTools";

function renderTools(source: FileSource | null) {
  return render(
    <TooltipProvider>
      <WorkspaceClientTools source={source} />
    </TooltipProvider>,
  );
}

function mockSource(
  over: Partial<FileSource> & Pick<FileSource, "id" | "label" | "caps">,
): FileSource {
  return {
    listDir: vi.fn(),
    read: vi.fn(),
    createFile: vi.fn(),
    mkdir: vi.fn(),
    move: vi.fn(),
    delete: vi.fn(),
    ...over,
  };
}

describe("WorkspaceClientTools", () => {
  it("renders nothing when source lacks reveal", () => {
    const { container } = renderTools(
      mockSource({
        id: "cloud:1",
        label: "w",
        caps: { watch: false, transfer: true, edit: true, snapshots: true },
        openShellAtPath: vi.fn(),
      }),
    );
    expect(container.firstChild).toBeNull();
  });

  it("opens folder when reveal exists; no title-bar shell button", async () => {
    const reveal = vi.fn().mockResolvedValue(undefined);
    renderTools(
      mockSource({
        id: "local:r1",
        label: "本地",
        caps: { watch: true, transfer: false, edit: true, snapshots: false },
        revealInOsFileManager: reveal,
        openShellAtPath: vi.fn(),
      }),
    );
    fireEvent.click(screen.getByRole("button", { name: "打开此对话文件夹" }));
    expect(reveal).toHaveBeenCalledWith("");
    expect(screen.queryByRole("button", { name: "在终端打开" })).toBeNull();
  });
});
