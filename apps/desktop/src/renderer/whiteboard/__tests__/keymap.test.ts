/**
 * Unit tests for the whiteboard keyboard dispatch table (keymap.ts). The shortcut policy is a
 * pure function over a {@link KeyCommands} surface, so a plain fake-event + spy-command harness
 * covers it — no canvas / engine / jsdom needed. Asserts both the routed command AND whether
 * `preventDefault` fired (the browser-fallthrough contract, e.g. Ctrl+C intentionally does not).
 */

import { describe, expect, it, vi } from "vitest";
import { type KeyCommands, handleKeyDown, handleKeyUp } from "../keymap";

function mkCmd() {
  return {
    hasSelection: vi.fn(() => true),
    undo: vi.fn(),
    redo: vi.fn(),
    selectAll: vi.fn(),
    copySelection: vi.fn(),
    cutSelection: vi.fn(),
    duplicateSelected: vi.fn(),
    bringToFront: vi.fn(),
    sendToBack: vi.fn(),
    groupSelected: vi.fn(),
    ungroupSelected: vi.fn(),
    zoomToSelection: vi.fn(),
    deleteSelected: vi.fn(),
    nudgeSelected: vi.fn(),
    clearSelection: vi.fn(),
    setTool: vi.fn(),
    setSpace: vi.fn(),
  } satisfies KeyCommands;
}

function keydown(
  key: string,
  opts: Partial<{
    ctrl: boolean;
    meta: boolean;
    shift: boolean;
    target: EventTarget | null;
  }> = {},
): { e: KeyboardEvent; prevented: () => number } {
  let count = 0;
  const e = {
    key,
    ctrlKey: opts.ctrl ?? false,
    metaKey: opts.meta ?? false,
    shiftKey: opts.shift ?? false,
    target: opts.target ?? null,
    preventDefault: () => {
      count += 1;
    },
  } as unknown as KeyboardEvent;
  return { e, prevented: () => count };
}

describe("keymap — modifier shortcuts", () => {
  it("routes undo / redo (Ctrl+Z, Ctrl+Shift+Z, Ctrl+Y) and preventsDefault", () => {
    const cmd = mkCmd();
    const z = keydown("z", { ctrl: true });
    expect(handleKeyDown(z.e, cmd)).toBe(true);
    expect(cmd.undo).toHaveBeenCalledTimes(1);
    expect(z.prevented()).toBe(1);

    handleKeyDown(keydown("z", { ctrl: true, shift: true }).e, cmd);
    handleKeyDown(keydown("y", { ctrl: true }).e, cmd);
    expect(cmd.redo).toHaveBeenCalledTimes(2);
    expect(cmd.undo).toHaveBeenCalledTimes(1);
  });

  it("Ctrl+C copies WITHOUT preventDefault (native copy may co-fire)", () => {
    const cmd = mkCmd();
    const c = keydown("c", { ctrl: true });
    expect(handleKeyDown(c.e, cmd)).toBe(true);
    expect(cmd.copySelection).toHaveBeenCalledTimes(1);
    expect(c.prevented()).toBe(0);
  });

  it("routes cut / duplicate / z-order / group / zoom via Ctrl", () => {
    const cmd = mkCmd();
    handleKeyDown(keydown("x", { ctrl: true }).e, cmd);
    handleKeyDown(keydown("d", { ctrl: true }).e, cmd);
    handleKeyDown(keydown("]", { ctrl: true }).e, cmd);
    handleKeyDown(keydown("[", { ctrl: true }).e, cmd);
    handleKeyDown(keydown("g", { ctrl: true }).e, cmd);
    handleKeyDown(keydown("g", { ctrl: true, shift: true }).e, cmd);
    handleKeyDown(keydown("2", { ctrl: true }).e, cmd);
    expect(cmd.cutSelection).toHaveBeenCalledTimes(1);
    expect(cmd.duplicateSelected).toHaveBeenCalledTimes(1);
    expect(cmd.bringToFront).toHaveBeenCalledTimes(1);
    expect(cmd.sendToBack).toHaveBeenCalledTimes(1);
    expect(cmd.groupSelected).toHaveBeenCalledTimes(1);
    expect(cmd.ungroupSelected).toHaveBeenCalledTimes(1);
    expect(cmd.zoomToSelection).toHaveBeenCalledTimes(1);
  });

  it("Meta (Cmd) is treated as the modifier too, and select-all routes", () => {
    const cmd = mkCmd();
    expect(handleKeyDown(keydown("a", { meta: true }).e, cmd)).toBe(true);
    expect(cmd.selectAll).toHaveBeenCalledTimes(1);
    expect(cmd.setTool).not.toHaveBeenCalled(); // "a" tool key NOT triggered under a modifier
  });

  it("an unmapped modifier combo is a no-op (Ctrl+V is left to the native paste path)", () => {
    const cmd = mkCmd();
    expect(handleKeyDown(keydown("v", { ctrl: true }).e, cmd)).toBe(false);
    expect(cmd.setTool).not.toHaveBeenCalled();
  });
});

describe("keymap — delete / nudge / escape / space", () => {
  it("Delete + Backspace delete only when something is selected", () => {
    const cmd = mkCmd();
    handleKeyDown(keydown("Delete").e, cmd);
    handleKeyDown(keydown("Backspace").e, cmd);
    expect(cmd.deleteSelected).toHaveBeenCalledTimes(2);

    const empty = mkCmd();
    empty.hasSelection.mockReturnValue(false);
    expect(handleKeyDown(keydown("Delete").e, empty)).toBe(false);
    expect(empty.deleteSelected).not.toHaveBeenCalled();
  });

  it("arrow keys nudge by 1, or 10 with Shift", () => {
    const cmd = mkCmd();
    handleKeyDown(keydown("ArrowLeft").e, cmd);
    handleKeyDown(keydown("ArrowRight", { shift: true }).e, cmd);
    handleKeyDown(keydown("ArrowUp").e, cmd);
    handleKeyDown(keydown("ArrowDown", { shift: true }).e, cmd);
    expect(cmd.nudgeSelected.mock.calls).toEqual([
      [-1, 0],
      [10, 0],
      [0, -1],
      [0, 10],
    ]);
  });

  it("Escape clears the selection only when there is one", () => {
    const cmd = mkCmd();
    expect(handleKeyDown(keydown("Escape").e, cmd)).toBe(true);
    expect(cmd.clearSelection).toHaveBeenCalledTimes(1);

    const empty = mkCmd();
    empty.hasSelection.mockReturnValue(false);
    expect(handleKeyDown(keydown("Escape").e, empty)).toBe(false);
    expect(empty.clearSelection).not.toHaveBeenCalled();
  });

  it("Space toggles the pan hint on keydown / keyup", () => {
    const cmd = mkCmd();
    handleKeyDown(keydown(" ").e, cmd);
    handleKeyUp(keydown(" ").e, cmd);
    expect(cmd.setSpace.mock.calls).toEqual([[true], [false]]);
  });
});

describe("keymap — tool keys + typing guard", () => {
  it("single keys pick tools (case-insensitive)", () => {
    const cmd = mkCmd();
    handleKeyDown(keydown("r").e, cmd);
    handleKeyDown(keydown("V").e, cmd);
    handleKeyDown(keydown("e").e, cmd);
    expect(cmd.setTool.mock.calls).toEqual([
      ["rectangle"],
      ["select"],
      ["eraser"],
    ]);
  });

  it("ignores everything while typing in an input / textarea / contenteditable", () => {
    const cmd = mkCmd();
    const input = { tagName: "INPUT" } as unknown as EventTarget;
    const editable = {
      tagName: "DIV",
      isContentEditable: true,
    } as unknown as EventTarget;
    expect(handleKeyDown(keydown("r", { target: input }).e, cmd)).toBe(false);
    expect(
      handleKeyDown(keydown("z", { ctrl: true, target: editable }).e, cmd),
    ).toBe(false);
    expect(cmd.setTool).not.toHaveBeenCalled();
    expect(cmd.undo).not.toHaveBeenCalled();
  });
});
