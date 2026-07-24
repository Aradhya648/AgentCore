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
