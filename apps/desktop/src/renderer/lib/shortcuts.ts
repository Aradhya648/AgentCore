import { startNewConversation } from "@/lib/newConversation";
import { isMac } from "@/lib/platform";
import { openCurrentConversationTerminal } from "@/services/terminalActions";
import { useSidebarStore } from "@/stores/sidebar";
import { useUIStore } from "@/stores/ui";
import type { NavigateFunction } from "react-router-dom";

function keyLabel(key: string): string {
  return key === "\\" ? "\\" : key.toUpperCase();
}

/** Render a modifier chord the way the host OS shows it (⌘K on macOS, Ctrl+K
 * elsewhere). `key` is the lowercased `e.key` value (e.g. "k", "\\"). Shared by
 * the command palette hints and the shortcuts settings page so the displayed
 * chord never drifts from what the handler actually matches. */
export function chord(key: string): string {
  return isMac ? `⌘${keyLabel(key)}` : `Ctrl+${keyLabel(key)}`;
}

export interface GlobalShortcut {
  id: string;
  /** Human-facing action label (used by the shortcuts settings page). */
  label: string;
  /** Lowercased `e.key` values that fire it (with the platform mod key); the
   * first is canonical, any others are accepted alternates. */
  keys: string[];
  run: (navigate: NavigateFunction) => void;
}

/**
 * Single source of truth for the app's global modifier-chord shortcuts.
 *
 * The AppShell keydown handler dispatches off this table (mod + a matching key),
 * and the 快捷键 settings page renders from it — so adding a global shortcut is a
 * one-line edit here, with no drift between behavior and the documented chord.
 * Plain keys handled elsewhere (e.g. Esc closing the dialog, owned by Radix) are
 * not registered here.
 */
export const GLOBAL_SHORTCUTS: GlobalShortcut[] = [
  {
    id: "command-palette",
    label: "命令面板 / 全局搜索",
    keys: ["k"],
    run: () => useUIStore.getState().toggleSearch(),
  },
  {
    id: "new-conversation",
    label: "新建对话",
    keys: ["n"],
    run: (navigate) => startNewConversation(navigate),
  },
  {
    id: "toggle-sidebar",
    label: "收起 / 展开侧栏",
    keys: ["b", "\\"],
    run: () => useSidebarStore.getState().toggleCollapsed(),
  },
  {
    id: "open-workspace-terminal",
    label: "在终端打开工作区",
    keys: ["`"],
    run: () => {
      void openCurrentConversationTerminal();
    },
  },
];

/** Display chords for a shortcut (canonical first, then any alternates). */
export function shortcutChords(s: GlobalShortcut): string[] {
  return s.keys.map(chord);
}
