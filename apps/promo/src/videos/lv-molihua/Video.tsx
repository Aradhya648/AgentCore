import type { ReactNode } from "react";
import {
  AbsoluteFill,
  Audio,
  getInputProps,
  interpolate,
  Sequence,
  staticFile,
  useCurrentFrame,
} from "remotion";
import { ColdOpenMain } from "./scenes/ColdOpenScene";
import { ChaptersMain } from "./scenes/ChapterTitleScene";
import { LogoScene } from "./scenes/LogoScene";
import {
  CHAPTERS,
  COLD_OPEN,
  FADE,
  FILM_FRAMES,
  LOGO,
} from "./timeline";

export { FILM_FRAMES };

/*
 * LV 诉茉莉奶白 — hybrid design kit film:
 *   0–15s   cold-open highlight reel
 *   15–29s  7 act title cards
 *   29–32s  Logo + slogan
 *
 * Mid-film product screen recordings are out of scope (edited in later).
 * Dark / tech theme throughout (PromoShell theme="dark" on the graph beat).
 */

const BGM_FILE: string | null = null;

export interface Grade {
  contrast: number;
  saturate: number;
  vignette: number;
}
const DEFAULT_GRADE: Grade = { contrast: 1.04, saturate: 1.08, vignette: 0.14 };

function resolveGrade(): Grade {
  const props = getInputProps() as { grade?: Partial<Grade> };
  return { ...DEFAULT_GRADE, ...(props.grade ?? {}) };
}

function PhaseFade({
  len,
  fadeIn,
  fadeOut,
  children,
}: {
  len: number;
  fadeIn?: boolean;
  fadeOut?: boolean;
  children: ReactNode;
}) {
  const frame = useCurrentFrame();
  const opIn = fadeIn
    ? interpolate(frame, [0, FADE], [0, 1], {
        extrapolateLeft: "clamp",
        extrapolateRight: "clamp",
      })
    : 1;
  const opOut = fadeOut
    ? interpolate(frame, [len, len + FADE], [1, 0], {
        extrapolateLeft: "clamp",
        extrapolateRight: "clamp",
      })
    : 1;
  return (
    <AbsoluteFill style={{ opacity: Math.min(opIn, opOut) }}>
      {children}
    </AbsoluteFill>
  );
}

function Vignette({ alpha }: { alpha: number }) {
  if (alpha <= 0) return null;
  return (
    <AbsoluteFill
      style={{
        pointerEvents: "none",
        background: `radial-gradient(ellipse 75% 75% at 50% 48%, transparent 62%, rgb(0 0 0 / ${alpha}) 100%)`,
      }}
    />
  );
}

export const Video: React.FC = () => {
  const grade = resolveGrade();
  return (
    <AbsoluteFill className="dark bg-background">
      {BGM_FILE && <Audio src={staticFile(BGM_FILE)} volume={0.55} />}

      <AbsoluteFill
        style={{ filter: `contrast(${grade.contrast}) saturate(${grade.saturate})` }}
      >
        <Sequence
          from={COLD_OPEN.from}
          durationInFrames={COLD_OPEN.frames + FADE}
          name="冷开场 0–15s"
        >
          <PhaseFade len={COLD_OPEN.frames} fadeIn fadeOut>
            <ColdOpenMain />
          </PhaseFade>
        </Sequence>

        <Sequence
          from={CHAPTERS.from}
          durationInFrames={CHAPTERS.frames + FADE}
          name="幕标题 15–29s"
        >
          <PhaseFade len={CHAPTERS.frames} fadeIn fadeOut>
            <ChaptersMain />
          </PhaseFade>
        </Sequence>

        <Sequence from={LOGO.from} durationInFrames={LOGO.frames} name="片尾">
          <LogoScene />
        </Sequence>

        <Vignette alpha={grade.vignette} />
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

// ── Standalone Studio wrappers ───────────────────────────────────────────────

export const ColdOpenStandalone: React.FC = () => (
  <AbsoluteFill className="dark bg-background">
    <ColdOpenMain />
  </AbsoluteFill>
);

export const ChaptersStandalone: React.FC = () => (
  <AbsoluteFill className="dark bg-background">
    <ChaptersMain />
  </AbsoluteFill>
);

export const LogoStandalone: React.FC = () => (
  <AbsoluteFill className="dark bg-background">
    <LogoScene />
  </AbsoluteFill>
);
