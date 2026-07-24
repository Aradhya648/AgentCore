import { ViewportPortal } from "@xyflow/react";
import type { WaveBand } from "./scene";

interface DebateStageBandsProps {
  bands: WaveBand[];
}

/**
 * 辩论阶段标签（协作图）：每一阶段（第 N 轮 / 结辩）顶部一枚胶囊标签，无阶段填充/边框。
 * 纯装饰层（ViewportPortal，pointer-events:none），不参与布局 / 交互。
 * 坐标为 flow 坐标（{@link WaveBand} 的 labelX/labelY）。
 */
export function DebateStageBands({ bands }: DebateStageBandsProps) {
  if (bands.length === 0) return null;
  return (
    <ViewportPortal>
      {bands.map((b) => (
        <div
          key={b.id}
          className="rounded-full border border-primary/30 bg-background px-2.5 py-0.5 text-xs font-medium text-primary shadow-sm"
          style={{
            position: "absolute",
            transform: `translate(${b.labelX}px, ${b.labelY}px) translate(-50%, -50%)`,
            zIndex: 1,
            pointerEvents: "none",
            whiteSpace: "nowrap",
          }}
        >
          {b.label}
        </div>
      ))}
    </ViewportPortal>
  );
}
