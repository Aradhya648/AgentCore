import { ViewportPortal } from "@xyflow/react";
import { Fragment } from "react";
import type { WaveBand } from "./scene";

interface WaveLanesProps {
  waves: WaveBand[];
}

export function WaveLanes({ waves }: WaveLanesProps) {
  if (waves.length === 0) return null;
  return (
    <ViewportPortal>
      {waves.map((w) => (
        <Fragment key={w.id}>
          <div
            className="rounded-xl border border-border/30 bg-muted/15"
            style={{
              position: "absolute",
              transform: `translate(${w.x}px, ${w.y}px)`,
              width: w.w,
              height: w.h,
              zIndex: -1,
              pointerEvents: "none",
            }}
          />
          <div
            className="rounded-full bg-muted/60 px-2 py-0.5 text-xs text-muted-foreground"
            style={{
              position: "absolute",
              transform: `translate(${w.labelX}px, ${w.labelY}px)`,
              zIndex: 1,
              pointerEvents: "none",
              whiteSpace: "nowrap",
            }}
          >
            {w.label}
          </div>
        </Fragment>
      ))}
    </ViewportPortal>
  );
}
