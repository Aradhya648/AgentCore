import { AbsoluteFill, interpolate, useCurrentFrame } from "remotion";
import { entranceStyle } from "../../../core/motion/primitives";
import { CHAPTERS, type ChapterDef } from "../data/chapters";
import { CHAPTER_FRAMES } from "../timeline";

/*
 * Data-driven act title card. When nested in a Remotion <Sequence>,
 * useCurrentFrame() is chapter-local so entrances reset each act.
 */

export function ChapterTitleCard({ chapter }: { chapter: ChapterDef }) {
  const frame = useCurrentFrame();
  return <ChapterTitleVisual frame={frame} chapter={chapter} />;
}

/** Pure visual — `frame` is chapter-local (0 … CHAPTER_FRAMES). */
export function ChapterTitleVisual({
  frame,
  chapter,
}: {
  frame: number;
  chapter: ChapterDef;
}) {
  const num = entranceStyle(frame, 4, 12);
  const title = entranceStyle(frame, 10, 12);
  const rule = entranceStyle(frame, 16, 10);
  const sub = entranceStyle(frame, 22, 12);
  const glow = interpolate(frame, [0, 20], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const cardOp = interpolate(
    frame,
    [0, 8, CHAPTER_FRAMES - 8, CHAPTER_FRAMES],
    [0, 1, 1, 0],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" },
  );

  return (
    <AbsoluteFill
      className="bg-background"
      style={{
        alignItems: "center",
        justifyContent: "center",
        opacity: cardOp,
      }}
    >
      <div
        style={{
          position: "absolute",
          width: 720,
          height: 720,
          borderRadius: "50%",
          background:
            "radial-gradient(circle, var(--primary) 0%, transparent 64%)",
          opacity: 0.12 * glow,
          filter: "blur(24px)",
        }}
      />

      <div
        style={{
          display: "flex",
          flexDirection: "column",
          alignItems: "flex-start",
          gap: 22,
          minWidth: 520,
        }}
      >
        <div
          className="text-primary"
          style={{
            opacity: num.opacity,
            transform: num.transform,
            fontSize: 28,
            fontWeight: 600,
            letterSpacing: "0.28em",
          }}
        >
          {chapter.num}
        </div>

        <div
          className="text-foreground"
          style={{
            opacity: title.opacity,
            transform: title.transform,
            fontSize: 64,
            fontWeight: 600,
            letterSpacing: "0.02em",
            lineHeight: 1.15,
          }}
        >
          {chapter.title}
        </div>

        <div
          style={{
            width: 220,
            height: 2,
            background: "var(--primary)",
            opacity: 0.55 * rule.opacity,
            transform: rule.transform,
          }}
        />

        <div
          className="text-muted-foreground"
          style={{
            opacity: sub.opacity,
            transform: sub.transform,
            fontSize: 32,
            fontWeight: 500,
            letterSpacing: "0.04em",
          }}
        >
          {chapter.subtitle}
        </div>
      </div>
    </AbsoluteFill>
  );
}

/** Cycles all 7 chapters (Studio standalone / film Sequence content). */
export function ChaptersMain() {
  const frame = useCurrentFrame();
  const idx = Math.min(
    CHAPTERS.length - 1,
    Math.floor(frame / CHAPTER_FRAMES),
  );
  const local = frame - idx * CHAPTER_FRAMES;
  return <ChapterTitleVisual frame={local} chapter={CHAPTERS[idx]} />;
}

/** Single-chapter composition — `chapterIndex` via defaultProps / Studio. */
export function ChapterTitleScene({
  chapterIndex = 0,
}: {
  chapterIndex?: number;
}) {
  const chapter =
    CHAPTERS[Math.max(0, Math.min(CHAPTERS.length - 1, chapterIndex))];
  return (
    <div className="dark h-full w-full">
      <ChapterTitleCard chapter={chapter} />
    </div>
  );
}
