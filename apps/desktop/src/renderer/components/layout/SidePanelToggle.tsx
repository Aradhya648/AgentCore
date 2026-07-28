import { IconButton } from "@/components/ui";
import { SimpleTooltip } from "@/components/ui/tooltip";
import { useSidePanelStore } from "@/stores/sidePanel";
import { PanelRight } from "lucide-react";

/**
 * Closed-dock open affordance — floats on the main content top-right.
 * While the dock is open, the same PanelRight glyph lives in the SidePanel
 * header (replacing X); this control must not render then.
 */
export function SidePanelToggle({
  className,
}: {
  className?: string;
}) {
  const pendingBadge = useSidePanelStore((s) => s.pendingBadge);
  const togglePanel = useSidePanelStore((s) => s.togglePanel);

  return (
    <SimpleTooltip label="侧面板 (Ctrl/Cmd+I)">
      <IconButton
        size="md"
        onClick={togglePanel}
        aria-label="侧面板"
        className={`relative border border-border bg-card/80 backdrop-blur ${className ?? ""}`}
      >
        <PanelRight size={16} />
        {pendingBadge > 0 && (
          <span className="absolute -right-1 -top-1 flex h-4 min-w-4 items-center justify-center rounded-full bg-primary px-1 text-xs font-medium text-primary-foreground">
            {pendingBadge > 9 ? "9+" : pendingBadge}
          </span>
        )}
      </IconButton>
    </SimpleTooltip>
  );
}
