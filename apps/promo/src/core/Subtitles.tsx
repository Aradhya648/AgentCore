import { AbsoluteFill, interpolate, useCurrentFrame } from "remotion";

/*
 * Parameterized subtitle track. The core owns the chrome; each video package
 * passes its cue list (typically aligned to that package's timeline.ts).
 */

export interface SubtitleCue {
  from: number;
  to: number;
  text: string;
}

const FADE = 8;

export function Subtitles({ cues }: { cues: SubtitleCue[] }) {
  const frame = useCurrentFrame();
  const cue = cues.find((c) => frame >= c.from && frame < c.to);
  if (!cue) return null;

  const opacity = interpolate(
    frame,
    [cue.from, cue.from + FADE, cue.to - FADE, cue.to],
    [0, 1, 1, 0],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" },
  );

  return (
    <AbsoluteFill style={{ pointerEvents: "none" }}>
      <div
        style={{
          position: "absolute",
          left: 0,
          right: 0,
          bottom: 96,
          display: "flex",
          justifyContent: "center",
          opacity,
        }}
      >
        <div
          className="rounded-2xl bg-background/70 px-7 py-3 text-3xl font-medium text-foreground"
          style={{
            backdropFilter: "blur(8px)",
            WebkitBackdropFilter: "blur(8px)",
            boxShadow: "0 4px 24px rgb(0 0 0 / 0.08)",
            letterSpacing: "0.01em",
          }}
        >
          {cue.text}
        </div>
      </div>
    </AbsoluteFill>
  );
}
