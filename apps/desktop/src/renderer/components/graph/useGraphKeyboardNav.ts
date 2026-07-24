/**
 * Keyboard navigation among a turn's agent nodes — the single implementation.
 * Arrow keys move focus along `navigableNodeIds`, Enter activates, Escape clears.
 * Owns `keyboardFocusId`; the host wires the window keydown listener and paints
 * the `graph-keyboard-focus` class on the matching node.
 */

import { useCallback, useState } from "react";

const ARROWS = ["ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight"];

export function useGraphKeyboardNav({
  navigableNodeIds,
  onActivate,
}: {
  navigableNodeIds: string[];
  onActivate: (id: string) => void;
}): {
  keyboardFocusId: string | null;
  setKeyboardFocusId: (id: string | null) => void;
  handleKeyboardNav: (key: string) => boolean;
} {
  const [keyboardFocusId, setKeyboardFocusId] = useState<string | null>(null);

  const handleKeyboardNav = useCallback(
    (key: string): boolean => {
      if (navigableNodeIds.length === 0) return false;
      if (key === "Escape") {
        setKeyboardFocusId(null);
        return true;
      }
      if (key === "Enter" && keyboardFocusId) {
        onActivate(keyboardFocusId);
        return true;
      }
      if (!ARROWS.includes(key)) return false;
      const idx = keyboardFocusId
        ? navigableNodeIds.indexOf(keyboardFocusId)
        : -1;
      let next = idx;
      if (key === "ArrowDown" || key === "ArrowRight") {
        next = idx < 0 ? 0 : Math.min(idx + 1, navigableNodeIds.length - 1);
      } else {
        next = idx < 0 ? 0 : Math.max(idx - 1, 0);
      }
      setKeyboardFocusId(navigableNodeIds[next] ?? null);
      return true;
    },
    [navigableNodeIds, keyboardFocusId, onActivate],
  );

  return { keyboardFocusId, setKeyboardFocusId, handleKeyboardNav };
}
