import { describe, expect, it, vi } from "vitest";
import { buildPaletteCommands, commandMatches } from "../paletteCommands";

vi.mock("@/services/demoTape", () => ({
  prepareDemoTapeAndOpen: vi.fn(),
  startDemoTapeAndOpen: vi.fn(),
}));

vi.mock("@/lib/newConversation", () => ({
  startNewConversation: vi.fn(),
}));

vi.mock("@/services/conversations", () => ({
  exportConversation: vi.fn(),
}));

vi.mock("@/services/terminalActions", () => ({
  openCurrentConversationTerminal: vi.fn(),
}));

vi.mock("@/lib/toast", () => ({
  notifyError: vi.fn(),
  notifySuccess: vi.fn(),
}));

vi.mock("@/lib/capabilities", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../capabilities")>();
  return { ...actual, hasLocalFiles: vi.fn(() => false) };
});

vi.mock("@/lib/grantReadonlyFolder", () => ({
  pickAndGrantReadonlyFolder: vi.fn(),
}));

const baseCtx = {
  navigate: vi.fn(),
  theme: "system" as const,
  diagnosticMode: false,
  sidebarCollapsed: false,
  openBookmarksInPalette: vi.fn(),
};

describe("paletteCommands demo tape gate", () => {
  it("hides demo-tape commands when catalog is empty", () => {
    const cmds = buildPaletteCommands(baseCtx);
    expect(cmds.some((c) => c.id.startsWith("demo-tape-"))).toBe(false);
  });

  it("injects prepare + autostart commands when server catalog is present", () => {
    const cmds = buildPaletteCommands({
      ...baseCtx,
      demoTapes: [
        {
          id: "lv-molihua-trademark",
          title: "LV诉茉莉奶白商标侵权案",
          user_prompt: "搜索下…",
          turn_count: 1,
        },
      ],
    });
    const prepare = cmds.find((c) => c.id === "demo-tape-lv-molihua-trademark");
    const autostart = cmds.find(
      (c) => c.id === "demo-tape-lv-molihua-trademark-autostart",
    );
    expect(prepare).toBeTruthy();
    expect(autostart).toBeTruthy();
    if (!prepare || !autostart) return;
    expect(prepare.title).toContain("演示回放");
    expect(prepare.title).not.toContain("立即开播");
    expect(prepare.hint).toContain("准备");
    expect(autostart.title).toContain("立即开播");
    expect(autostart.hint).toContain("一键");
    expect(commandMatches(prepare, "演示回放")).toBe(true);
    expect(commandMatches(prepare, "huifang")).toBe(true);
    expect(commandMatches(autostart, "立即开播")).toBe(true);
  });
});

describe("paletteCommands · 前往发现性", () => {
  it("includes 白板 /whiteboard and excludes /explore placeholder", () => {
    const cmds = buildPaletteCommands(baseCtx);
    const board = cmds.find((c) => c.id === "nav-whiteboard");
    expect(board).toBeTruthy();
    expect(board?.title).toBe("白板");
    expect(board?.category).toBe("前往");
    if (!board) return;
    expect(commandMatches(board, "baiban")).toBe(true);

    board?.run();
    expect(baseCtx.navigate).toHaveBeenCalledWith("/whiteboard");

    expect(cmds.some((c) => c.id.includes("explore"))).toBe(false);
    expect(
      cmds.some(
        (c) =>
          c.title.includes("探索") ||
          (c.keywords ?? []).some((k) => k.includes("explore")),
      ),
    ).toBe(false);
  });
});

describe("paletteCommands · 区外只读授权", () => {
  it("hides grant command without local FS", async () => {
    const { hasLocalFiles } = await import("../capabilities");
    vi.mocked(hasLocalFiles).mockReturnValue(false);
    const cmds = buildPaletteCommands(baseCtx);
    expect(cmds.some((c) => c.id === "grant-readonly-folder")).toBe(false);
  });

  it("injects grant command on desktop FS", async () => {
    const { hasLocalFiles } = await import("../capabilities");
    vi.mocked(hasLocalFiles).mockReturnValue(true);
    const cmds = buildPaletteCommands(baseCtx);
    const grant = cmds.find((c) => c.id === "grant-readonly-folder");
    expect(grant).toBeTruthy();
    expect(grant?.title).toContain("授权本机目录");
    if (!grant) return;
    expect(commandMatches(grant, "zhuomian")).toBe(true);
  });
});
