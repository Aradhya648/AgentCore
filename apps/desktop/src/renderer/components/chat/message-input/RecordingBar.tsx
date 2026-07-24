import { IconButton } from "@/components/ui";
import { X } from "lucide-react";

function formatDuration(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return `${m}:${String(s).padStart(2, "0")}`;
}

function WaveformBars() {
  return (
    <div className="flex h-4 items-end gap-0.5" aria-hidden>
      {[0, 1, 2, 3, 4].map((i) => (
        <div
          key={i}
          className="w-0.5 rounded-full bg-destructive voice-wave-bar"
          style={{ animationDelay: `${i * 0.15}s` }}
        />
      ))}
    </div>
  );
}

export function RecordingBar({
  duration,
  onCancel,
}: {
  duration: number;
  onCancel: () => void;
}) {
  return (
    <div className="flex items-center gap-3 px-4 pt-2">
      <span className="size-2 shrink-0 animate-pulse rounded-full bg-destructive" />
      <span className="text-xs font-medium tabular-nums text-destructive">
        {formatDuration(duration)}
      </span>
      <WaveformBars />
      <div className="flex-1" />
      <IconButton
        size="sm"
        onClick={onCancel}
        aria-label="取消录音"
        className="text-muted-foreground"
      >
        <X size={14} />
      </IconButton>
    </div>
  );
}
