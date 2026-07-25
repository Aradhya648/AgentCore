import { FileTreeRow } from "@/components/files/FileTreeRow";
import { TooltipProvider } from "@/components/ui/tooltip";
import type { FileNode, FileSource } from "@/lib/fileSource";
// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/components/files/FileTreeRowMenu", () => ({
  FileTreeRowMenu: () => null,
}));

function noop() {}

function renderDir(path: string, name: string, fileCount: number) {
  const children = Array.from({ length: fileCount }, (_, i) => ({
    path: `${path}/f${i}.md`,
    name: `f${i}.md`,
    isDir: false,
  }));
  const map = new Map<string, FileNode[]>([[path, children]]);
  const source = {
    id: "test",
    caps: { watch: false, transfer: false, edit: false, snapshots: false },
  } as unknown as FileSource;
  const data = {
    childrenOf: (dir: string) => map.get(dir),
    statusOf: () => "ready" as const,
    ensureDir: noop,
    reload: noop,
  };
  const base = {
    depth: 0,
    indentBase: 0,
    source,
    data,
    expanded: new Set<string>(),
    activePath: null,
    creating: null,
    renaming: null,
    dropTarget: null,
    selectedPath: null,
    cutPath: null,
    hasClipboard: false,
    onToggle: noop,
    onOpenFile: noop,
    onSelect: noop,
    onContextCreate: noop,
    onStartRename: noop,
    onSubmitRename: noop,
    onCancelRename: noop,
    onSubmitCreate: noop,
    onCancelCreate: noop,
    onDelete: noop,
    onCopy: noop,
    onCut: noop,
    onPaste: noop,
    onMoveInto: noop,
    onUpload: noop,
    onDropTarget: noop,
    onReloadDir: noop,
  };
  return render(
    <TooltipProvider>
      <ul>
        <FileTreeRow {...base} node={{ path, name, isDir: true }} />
      </ul>
    </TooltipProvider>,
  );
}

describe("FileTreeRow stage dir badges", () => {
  it("AgentCore/文档/research/debate 显示徽章副文案，普通目录零噪音", () => {
    const { unmount } = renderDir("AgentCore/文档/research", "research", 2);
    expect(screen.getByText("调研案卷 · 2 件")).toBeTruthy();
    unmount();

    renderDir("AgentCore/文档/debate", "debate", 1);
    expect(screen.getByText("辩论产物 · 1 件")).toBeTruthy();
    // 同屏再渲普通目录不应出徽章
    renderDir("src", "src", 3);
    expect(screen.queryByText(/src ·/)).toBeNull();
    expect(screen.getByText("src")).toBeTruthy();
    expect(screen.queryByText("调研案卷 · 3 件")).toBeNull();
  });
});
