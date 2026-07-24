/**
 * Keyboard shortcut policy for the whiteboard (AI协作白板.md §六 自研引擎架构).
 *
 * A pure dispatch table lifted out of {@link WhiteboardEngine}: it maps keystrokes onto the
 * {@link KeyCommands} surface (every entry is an existing engine method / tiny hook) and owns
 * `preventDefault` for the shortcuts that must not fall through to the browser. Same nature as
 * the sibling pure modules — no canvas, no engine state, so the shortcut set is a table you can
 * read and unit-test with a fake command object.
 */

import type { Tool } from "./types";

/** The engine capabilities the keyboard layer drives. Each maps 1:1 onto a WhiteboardEngine
 * method or a small state hook (space-to-pan, clear selection). */
export interface KeyCommands {
  hasSelection(): boolean;
  undo(): void;
  redo(): void;
  selectAll(): void;
  copySelection(): void;
  cutSelection(): void;
  duplicateSelected(): void;
  bringToFront(): void;
  sendToBack(): void;
  groupSelected(): void;
  ungroupSelected(): void;
  zoomToSelection(): void;
  deleteSelected(): void;
  nudgeSelected(dx: number, dy: number): void;
  clearSelection(): void;
  setTool(tool: Tool): void;
  /** Hold-Space temporarily switches to the pan cursor/gesture; release restores it. */
  setSpace(down: boolean): void;
}

const NUDGE = 1;
const NUDGE_LARGE = 10;

/** Single-key tool shortcuts (no modifier). `d`/`a` only pick a tool here — Ctrl+D / Ctrl+A
 * are duplicate / select-all, handled before this map is consulted. */
const TOOL_KEYS: Record<string, Tool> = {
  v: "select",
  h: "hand",
  r: "rectangle",
  o: "ellipse",
  d: "diamond",
  s: "sticky",
  t: "text",
  a: "arrow",
  l: "line",
  f: "frame",
  p: "freedraw",
  e: "eraser",
};

/** Whether `target` is a text-input surface we must not hijack (so typing in an overlay input
 * keeps its native keys). */
function isTypingTarget(target: EventTarget | null): boolean {
  const el = target as HTMLElement | null;
  return (
    !!el &&
    (el.tagName === "INPUT" ||
      el.tagName === "TEXTAREA" ||
      el.isContentEditable)
  );
}

/** Route a keydown to a command. Returns true when handled (the engine ignores the result;
 * the boolean exists for tests + future composition). Calls `preventDefault` for the shortcuts
 * that must not reach the browser. */
export function handleKeyDown(e: KeyboardEvent, cmd: KeyCommands): boolean {
  if (isTypingTarget(e.target)) return false;

  const mod = e.ctrlKey || e.metaKey;
  const key = e.key.toLowerCase();

  if (mod) {
    switch (key) {
      case "z":
        e.preventDefault();
        if (e.shiftKey) cmd.redo();
        else cmd.undo();
        return true;
      case "y":
        e.preventDefault();
        cmd.redo();
        return true;
      case "a":
        e.preventDefault();
        cmd.selectAll();
        return true;
      case "c":
        // No preventDefault: harmless if the native copy also fires (nothing selectable in the
        // DOM), and it keeps parity with the pre-extraction behavior.
        cmd.copySelection();
        return true;
      case "x":
        e.preventDefault();
        cmd.cutSelection();
        return true;
      // Ctrl+V is intentionally NOT handled: the window `paste` event is the single paste path,
      // so a system-clipboard image and the internal element clipboard can't both fire.
      case "d":
        e.preventDefault();
        cmd.duplicateSelected();
        return true;
      case "]":
        e.preventDefault();
        cmd.bringToFront();
        return true;
      case "[":
        e.preventDefault();
        cmd.sendToBack();
        return true;
      case "g":
        e.preventDefault();
        if (e.shiftKey) cmd.ungroupSelected();
        else cmd.groupSelected();
        return true;
      case "2":
        e.preventDefault();
        cmd.zoomToSelection();
        return true;
      default:
        return false;
    }
  }

  if (e.key === "Delete" || e.key === "Backspace") {
    if (cmd.hasSelection()) {
      e.preventDefault();
      cmd.deleteSelected();
      return true;
    }
    return false;
  }
  if (e.key.startsWith("Arrow") && cmd.hasSelection()) {
    e.preventDefault();
    const step = e.shiftKey ? NUDGE_LARGE : NUDGE;
    if (e.key === "ArrowLeft") cmd.nudgeSelected(-step, 0);
    else if (e.key === "ArrowRight") cmd.nudgeSelected(step, 0);
    else if (e.key === "ArrowUp") cmd.nudgeSelected(0, -step);
    else if (e.key === "ArrowDown") cmd.nudgeSelected(0, step);
    return true;
  }
  if (e.key === " ") {
    cmd.setSpace(true);
    return true;
  }
  if (e.key === "Escape" && cmd.hasSelection()) {
    cmd.clearSelection();
    return true;
  }
  const toolKey = TOOL_KEYS[key];
  if (toolKey) {
    cmd.setTool(toolKey);
    return true;
  }
  return false;
}

/** Keyup only tracks the space bar (release hold-to-pan). Returns true when handled. */
export function handleKeyUp(e: KeyboardEvent, cmd: KeyCommands): boolean {
  if (e.key === " ") {
    cmd.setSpace(false);
    return true;
  }
  return false;
}
