import type { RunStatus } from "@/stores/execution";
import { useEffect, useRef, useState } from "react";

const FLASH_MS = 600;
const isTerminal = (s: RunStatus): boolean =>
  s === "completed" || s === "failed";

/**
 * Fire a one-shot flash when a run *transitions* into a terminal state.
 *
 * Returns `true` for {@link FLASH_MS} after the change so the node can play its
 * `graph-node-flash` animation. Guards the initial mount (a node that loads
 * already-finished — e.g. a replayed/closed turn — must not flash), and the
 * timeout (not re-renders) bounds the window, so streaming updates mid-flash
 * never cut it short or retrigger it.
 */
export function useTerminalFlash(status: RunStatus): boolean {
  const [flashing, setFlashing] = useState(false);
  const prev = useRef(status);

  useEffect(() => {
    const was = prev.current;
    prev.current = status;
    if (was === status) return;
    if (isTerminal(status) && !isTerminal(was)) {
      setFlashing(true);
      const t = setTimeout(() => setFlashing(false), FLASH_MS);
      return () => clearTimeout(t);
    }
    // Any other transition (e.g. terminal → running on a retry mid-flash) cancels
    // the flash, so it can't get stuck on and collide with the running pulse.
    setFlashing(false);
  }, [status]);

  return flashing;
}
