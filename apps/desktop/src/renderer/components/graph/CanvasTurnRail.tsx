import type { ExecutionStatus } from "@/stores/execution";
import { useEffect, useRef } from "react";

/**
 * 回合轨道（前端UX设计.md §六）: a slim 1-D status index docked on the canvas's right
 * edge for LONG conversations. The overview is a single pannable vertical spine; once
 * it grows past a few turns it no longer fits on screen, and there is no「我在哪 / 跳到第
 * N 回合」affordance. This rail is that affordance — one tick per turn, top→bottom in
 * spine order, colored by attention/status, with the focused turn enlarged + ringed.
 *
 * Deliberately NOT a minimap: §六 dropped the minimap because a vertical spine's 2-D
 * map is low-value clutter. This is a 1-D index (ticks, not a scaled graph), so it adds
 * the「扫视 + 跳转」value without re-introducing the clutter the minimap was cut for. It
 * indexes the loaded message window (the canvas does not page older history on pan —
 * that is a separate, larger feature), which for most conversations is the whole thread.
 */

export interface TurnRailItem {
  id: string;
  kind: "team" | "simple";
  /** Projected execution status for a team turn; null for a simple Q&A turn. */
  status: ExecutionStatus | null;
  running: boolean;
  /** 待你拍板 count on this turn — drives the primary tone (outranks run state). */
  pendingDecisions: number;
  /** 待救火 — drives the destructive tone (outranks run state, under 待你拍板). */
  recoverable: boolean;
  /** Task summary / prompt, for the tick's hover title + a11y label. */
  label: string;
}

/** Minimum turns before the rail appears — a short spine fits on screen, so an index
 * would just be noise. The rail earns its keep only once the spine is long enough to
 * lose track of (kept conservative to honor「简单回合保持干净」). */
const RAIL_MIN_TURNS = 5;

/** Tick tone + size. Attention (待你拍板 → 待救火) outranks run state, mirroring the
 * folded summary node's chip priority so the rail never disagrees with the spine. */
function dotClass(t: TurnRailItem, focused: boolean): string {
  const tone =
    t.pendingDecisions > 0
      ? "bg-primary"
      : t.recoverable
        ? "bg-destructive"
        : t.running
          ? "bg-primary"
          : t.status === "completed"
            ? "bg-success"
            : t.status === "failed"
              ? "bg-destructive"
              : "bg-muted-foreground/50";
  // Focused tick reads larger + ringed; team ticks sit a touch bigger than the quieter
  // simple-turn ticks so real teamwork stands out on the index.
  const size = focused
    ? "size-3 ring-2 ring-primary"
    : t.kind === "team"
      ? "size-2.5"
      : "size-2";
  return `${tone} ${size}`;
}

export function CanvasTurnRail({
  items,
  focusedId,
  onSelect,
}: {
  items: TurnRailItem[];
  focusedId: string | null;
  onSelect: (id: string, kind: "team" | "simple") => void;
}) {
  // Keep the active tick in view on a long, internally-scrolling rail (re-runs when
  // the focused turn changes — focusedId is read so it counts as a real dependency).
  const focusedRef = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (focusedId) focusedRef.current?.scrollIntoView({ block: "nearest" });
  }, [focusedId]);

  if (items.length < RAIL_MIN_TURNS) return null;

  return (
    <div className="pointer-events-auto absolute right-2 top-1/2 z-10 flex max-h-[72%] -translate-y-1/2 flex-col items-center gap-1 overflow-y-auto rounded-full border border-border bg-card/80 px-1.5 py-2 shadow-sm backdrop-blur">
      {items.map((t, i) => {
        const focused = t.id === focusedId;
        return (
          <button
            key={t.id}
            ref={focused ? focusedRef : undefined}
            type="button"
            onClick={() => onSelect(t.id, t.kind)}
            aria-current={focused ? "true" : undefined}
            aria-label={`回合 ${i + 1}${t.label ? `：${t.label}` : ""}`}
            title={`回合 ${i + 1}${t.label ? ` · ${t.label}` : ""}`}
            className="flex size-3.5 shrink-0 items-center justify-center rounded-full outline-none focus-visible:ring-2 focus-visible:ring-primary/60"
          >
            <span
              className={`rounded-full transition-all ${dotClass(t, focused)}`}
            />
          </button>
        );
      })}
    </div>
  );
}
