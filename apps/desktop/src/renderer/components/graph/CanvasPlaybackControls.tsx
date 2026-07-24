import { Button, IconButton } from "@/components/ui";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import {
  describeFrame,
  execRuntime,
  useActiveExecField,
  useExecutionScope,
  useExecutionStore,
} from "@/stores/execution";
import { Pause, Play, Radio } from "lucide-react";
import { useEffect, useRef, useState } from "react";

const STEP_INTERVAL_MS = 450;

/**
 * Floating playback trigger for the 放大态 collaboration graph — matches the
 * {@link CanvasZoomControls} pill (bottom-left HUD). Live: one icon + tooltip;
 * click opens a popover with the full frame scrubber. The chat「回放」entry
 * (`autoPlay`) opens the popover and starts from frame 0.
 */
export function CanvasPlaybackControls({
  autoPlay = false,
}: { autoPlay?: boolean } = {}) {
  const messageId = useExecutionScope();
  const plan = useActiveExecField((rt) => rt.plan);
  const frames = useActiveExecField((rt) => rt.frames);
  const playhead = useActiveExecField((rt) => rt.playhead);
  const setPlayhead = useExecutionStore((s) => s.setPlayhead);
  const goLive = useExecutionStore((s) => s.goLive);
  const [playing, setPlaying] = useState(false);
  const [open, setOpen] = useState(false);

  const total = frames.length;
  const pos = playhead ?? total;
  const isLive = playhead === null;

  useEffect(() => {
    if (!playing || !messageId) return;
    const id = setInterval(() => {
      const state = useExecutionStore.getState();
      const rt = execRuntime(state, messageId);
      const count = rt.frames.length;
      const cur = rt.playhead ?? count;
      const next = cur + 1;
      if (next >= count) {
        state.goLive(messageId);
        setPlaying(false);
      } else {
        state.setPlayhead(next, messageId);
      }
    }, STEP_INTERVAL_MS);
    return () => clearInterval(id);
  }, [playing, messageId]);

  const autoStartedRef = useRef(false);
  useEffect(() => {
    if (!autoPlay || autoStartedRef.current || !messageId) return;
    if (frames.length === 0) return;
    autoStartedRef.current = true;
    setPlayhead(0, messageId);
    setPlaying(true);
    setOpen(true);
  }, [autoPlay, messageId, frames.length, setPlayhead]);

  if (!plan || total === 0 || !messageId) return null;

  const currentFrame = pos > 0 ? frames[pos - 1] : null;
  const description = currentFrame
    ? describeFrame(currentFrame, plan)
    : "等待执行开始…";

  const onTogglePlay = () => {
    if (!playing && (playhead === null || pos >= total)) {
      setPlayhead(0, messageId);
    }
    setPlaying((p) => !p);
  };

  const onScrub = (value: number) => {
    setPlaying(false);
    if (value >= total) goLive(messageId);
    else setPlayhead(value, messageId);
  };

  const triggerLabel = isLive
    ? playing
      ? "回放中…"
      : `实时 · ${description}`
    : playing
      ? "回放中…"
      : `回放 ${pos}/${total} · ${description}`;

  const triggerIcon = playing ? (
    <Pause size={14} />
  ) : isLive ? (
    <Radio size={14} />
  ) : (
    <Play size={14} />
  );

  const triggerTone =
    isLive && !playing
      ? "bg-primary/10 text-primary hover:bg-primary/10 hover:text-primary"
      : !isLive || playing
        ? "bg-accent text-foreground hover:bg-accent hover:text-foreground"
        : undefined;

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <div className="rounded-lg border border-border bg-card/90 p-1 shadow-sm backdrop-blur">
          <IconButton
            aria-label={triggerLabel}
            title={triggerLabel}
            className={triggerTone}
          >
            {triggerIcon}
          </IconButton>
        </div>
      </PopoverTrigger>
      <PopoverContent
        side="top"
        align="start"
        className="w-[min(360px,calc(100vw-2rem))] p-3"
      >
        <div className="flex flex-col gap-2">
          <div className="flex items-center gap-2">
            <IconButton
              onClick={onTogglePlay}
              aria-label={playing ? "暂停回放" : "回放"}
              title={playing ? "暂停回放" : "回放"}
            >
              {playing ? <Pause size={15} /> : <Play size={15} />}
            </IconButton>

            <input
              type="range"
              min={0}
              max={total}
              value={pos}
              onChange={(e) => onScrub(Number(e.target.value))}
              className="h-1 min-w-0 flex-1 cursor-pointer appearance-none rounded-full bg-muted accent-primary"
            />

            <span className="shrink-0 text-xs tabular-nums text-muted-foreground">
              {pos}/{total}
            </span>

            <Button
              variant="ghost"
              size="sm"
              onClick={() => {
                setPlaying(false);
                goLive(messageId);
              }}
              icon={<Radio size={13} />}
              className={
                isLive
                  ? "shrink-0 bg-primary/10 text-primary hover:bg-primary/10 hover:text-primary"
                  : "shrink-0"
              }
            >
              实时
            </Button>
          </div>

          <p className="truncate text-xs text-muted-foreground">
            {description}
          </p>
        </div>
      </PopoverContent>
    </Popover>
  );
}
