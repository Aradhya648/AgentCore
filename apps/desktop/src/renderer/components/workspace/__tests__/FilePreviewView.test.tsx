// @vitest-environment jsdom

import { TooltipProvider } from "@/components/ui/tooltip";
import type { FileSource } from "@/lib/fileSource";
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

// 只桩掉会拉真实服务/store 的邻居；视图本体（源码渲染 + 横幅递进 + 图标门控）用真的。
vi.mock("@/stores/conversation", () => ({
  useConversationStore: (
    sel: (s: { currentConversationId: string | null }) => unknown,
  ) => sel({ currentConversationId: "c1" }),
}));
vi.mock("@/hooks/useFileAudit", () => ({
  useFileAudit: () => ({ status: "idle" as const }),
}));
vi.mock("@/components/audit/FileAuditTrail", () => ({
  FileAuditSection: () => <div data-testid="file-audit" />,
}));
// md 预览复用聊天 Markdown 渲染器；桩成可断言的叶子，避免在 jsdom 里拉整条 remark 管线。
vi.mock("@/components/chat/Markdown", () => ({
  Markdown: ({ content }: { content: string }) => (
    <div data-testid="md-render">{content}</div>
  ),
}));

import { FilePreviewView } from "@/components/workspace/FilePreviewView";

const HTML_TEXT = "<html><body><script>x</script>hi</body></html>";

function makeSource(overrides: Partial<FileSource> = {}): FileSource {
  return {
    id: "workspace:c1",
    label: "工作区",
    caps: { watch: false, transfer: true, edit: true, snapshots: true },
    listDir: async () => [],
    read: async () => ({ kind: "text", text: HTML_TEXT, truncated: false }),
    createFile: async () => {},
    mkdir: async () => {},
    move: async () => {},
    delete: async () => {},
    writeBytes: async () => {},
    download: async () => {},
    ...overrides,
  } as FileSource;
}

function renderView(source: FileSource, name = "index.html") {
  return render(
    <TooltipProvider>
      <FilePreviewView
        source={source}
        path={name}
        name={name}
        onClose={vi.fn()}
      />
    </TooltipProvider>,
  );
}

/** 横幅容器 =「完整交互效果」说明所在行（与标题栏图标区分作用域）。 */
function banner(): HTMLElement {
  const el = screen.getByText(/这是网页文件的源码/).parentElement;
  if (!el) throw new Error("banner not found");
  return el;
}

describe("FilePreviewView — HTML 源码视图（静态快照已取消）", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("HTML 与普通文本一致显示源码，不再渲染快照 iframe，也无「预览/源码」切换", async () => {
    const { container } = renderView(makeSource());
    await screen.findByText(/这是网页文件的源码/);
    expect(container.querySelector("iframe")).toBeNull();
    expect(container.querySelector("pre")?.textContent).toBe(HTML_TEXT);
    expect(screen.queryByRole("button", { name: "查看源码" })).toBeNull();
    expect(screen.queryByRole("button", { name: "预览效果" })).toBeNull();
  });

  it("编辑与审计回归：HTML 可编辑（铅笔入口）、FileAuditSection 出现", async () => {
    renderView(makeSource());
    await screen.findByText(/这是网页文件的源码/);
    expect(screen.getByRole("button", { name: "编辑" })).toBeTruthy();
    expect(screen.getByTestId("file-audit")).toBeTruthy();
  });

  it("横幅 CTA 最高档：有 openInAppPreview →「打开完整预览」，点击路由到位", async () => {
    const openInAppPreview = vi.fn().mockResolvedValue(undefined);
    const openInBrowser = vi.fn().mockResolvedValue(undefined);
    renderView(makeSource({ openInAppPreview, openInBrowser }));
    await screen.findByText(/完整交互效果可打开完整预览/);

    await act(async () => {
      fireEvent.click(
        within(banner()).getByRole("button", { name: "打开完整预览" }),
      );
    });
    expect(openInAppPreview).toHaveBeenCalledWith("index.html");
    expect(openInBrowser).not.toHaveBeenCalled();
    // 标题栏图标同套门控：完整预览 + 在浏览器打开都在。
    expect(screen.getByRole("button", { name: "完整预览" })).toBeTruthy();
  });

  it("横幅 CTA 次档：无 openInAppPreview 有 openInBrowser →「在浏览器打开」", async () => {
    const openInBrowser = vi.fn().mockResolvedValue(undefined);
    renderView(makeSource({ openInBrowser }));
    await screen.findByText(/完整交互效果请在浏览器打开/);

    await act(async () => {
      fireEvent.click(
        within(banner()).getByRole("button", { name: "在浏览器打开" }),
      );
    });
    expect(openInBrowser).toHaveBeenCalledWith("index.html");
  });

  it("横幅 CTA 兜底（web）：两出口都无 → 指「下载」", async () => {
    const download = vi.fn().mockResolvedValue(undefined);
    renderView(makeSource({ download }));
    await screen.findByText(/完整交互效果请下载后在浏览器打开/);

    await act(async () => {
      fireEvent.click(within(banner()).getByRole("button", { name: "下载" }));
    });
    expect(download).toHaveBeenCalledWith("index.html", "index.html");
  });

  it("非 HTML 文本不出横幅", async () => {
    renderView(makeSource(), "notes.txt");
    expect(await screen.findByText(HTML_TEXT)).toBeTruthy();
    expect(screen.queryByText(/这是网页文件的源码/)).toBeNull();
  });
});

describe("FilePreviewView — Markdown 默认渲染预览（阅读优先）", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("md 点开默认渲染预览，而非源码 pre", async () => {
    const md = "# 标题\n\n正文段落";
    const { container } = renderView(
      makeSource({
        read: async () => ({ kind: "text", text: md, truncated: false }),
      }),
      "notes.md",
    );
    const rendered = await screen.findByTestId("md-render");
    expect(rendered.textContent).toBe(md);
    expect(container.querySelector("pre")).toBeNull(); // 不落源码视图
  });

  it("截断的 md 回落源码 + 截断提示（避免半截 markdown 渲染错乱）", async () => {
    const { container } = renderView(
      makeSource({
        read: async () => ({
          kind: "text",
          text: "# 很长的文档",
          truncated: true,
        }),
      }),
      "big.md",
    );
    await screen.findByText(/内容较大/);
    expect(container.querySelector("pre")).toBeTruthy();
    expect(screen.queryByTestId("md-render")).toBeNull();
  });
});
