import { IconButton } from "@/components/ui";
import { Maximize, Minus, Plus } from "lucide-react";

/**
 * Shared zoom cluster for the canvas surfaces (统一观感, 前端UX设计.md §六). The 总览态
 * ({@link import("./ConversationCanvas")}) and the 放大态 ({@link import("./GraphView")}
 * non-embedded) both float this vertical 放大 / 缩小 / 适应 pill bottom-left, stacked
 * under {@link CanvasPlaybackControls} when frames exist. Each surface wires its own
 * surfaces read as one design system instead of two one-off control clusters. Each
 * surface wires its own ReactFlow instance through the callbacks. (Fit moved here from
 * 放大态's GraphToolbar, which now selects layout only — zoom + fit live together.)
 */
export function CanvasZoomControls({
  onZoomIn,
  onZoomOut,
  onFit,
  fitLabel = "适应画布",
}: {
  onZoomIn: () => void;
  onZoomOut: () => void;
  onFit: () => void;
  /** Fit button tooltip — the 放大态 adds its「(F)」hotkey hint. */
  fitLabel?: string;
}) {
  return (
    <div className="flex flex-col gap-0.5 rounded-lg border border-border bg-card/90 p-1 shadow-sm backdrop-blur">
      <IconButton onClick={onZoomIn} aria-label="放大" title="放大">
        <Plus size={14} />
      </IconButton>
      <IconButton onClick={onZoomOut} aria-label="缩小" title="缩小">
        <Minus size={14} />
      </IconButton>
      <IconButton onClick={onFit} aria-label="适应画布" title={fitLabel}>
        <Maximize size={14} />
      </IconButton>
    </div>
  );
}
