import { AbsoluteFill } from "remotion";
import { CHAPTERS } from "./data/chapters";
import { DecisionBriefCard, ScorePanelCard } from "./scenes/HighlightCards";
import { ChapterTitleVisual } from "./scenes/ChapterTitleScene";
import { SLOGAN } from "./scenes/LogoScene";

/*
 * Static QA stills for hybrid package self-check (fonts / key data / titles).
 * Each freezes a representative beat so `pnpm render -- <id> out/x.png --still`
 * can be read back without scrubbing the full film.
 */

export function StillDecisionBrief() {
  return (
    <AbsoluteFill className="dark bg-background">
      <div className="flex h-full w-full items-center justify-center">
        <DecisionBriefCard />
      </div>
    </AbsoluteFill>
  );
}

export function StillScorePanel() {
  return (
    <AbsoluteFill className="dark bg-background">
      <div className="flex h-full w-full items-center justify-center">
        <ScorePanelCard />
      </div>
    </AbsoluteFill>
  );
}

export function StillChapter06() {
  return (
    <AbsoluteFill className="dark bg-background">
      <ChapterTitleVisual frame={30} chapter={CHAPTERS[5]} />
    </AbsoluteFill>
  );
}

/** Frozen end-card lockup (no entrance animation — stills render at frame 0). */
export function StillLogo() {
  return (
    <AbsoluteFill
      className="dark bg-background"
      style={{ alignItems: "center", justifyContent: "center" }}
    >
      <div
        style={{
          position: "absolute",
          width: 900,
          height: 900,
          borderRadius: "50%",
          background:
            "radial-gradient(circle, var(--primary) 0%, transparent 62%)",
          opacity: 0.14,
          filter: "blur(20px)",
        }}
      />
      <div
        style={{
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          gap: 28,
        }}
      >
        <svg width={132} height={132} viewBox="0 0 132 132" role="presentation">
          <g transform="translate(6 6)">
            <line x1={60} y1={60} x2={16} y2={26} stroke="var(--primary)" strokeWidth={2.5} opacity={0.5} />
            <line x1={60} y1={60} x2={108} y2={22} stroke="var(--primary)" strokeWidth={2.5} opacity={0.5} />
            <line x1={60} y1={60} x2={100} y2={104} stroke="var(--primary)" strokeWidth={2.5} opacity={0.5} />
            <line x1={16} y1={26} x2={108} y2={22} stroke="var(--primary)" strokeWidth={2.5} opacity={0.5} />
            <circle cx={60} cy={60} r={11} fill="var(--primary)" />
            <circle cx={16} cy={26} r={7} fill="var(--primary)" opacity={0.85} />
            <circle cx={108} cy={22} r={7} fill="var(--primary)" opacity={0.85} />
            <circle cx={100} cy={104} r={7} fill="var(--primary)" opacity={0.85} />
          </g>
        </svg>
        <div
          className="text-foreground"
          style={{ fontSize: 76, fontWeight: 600, letterSpacing: "-0.01em" }}
        >
          AgentCore
        </div>
        <div
          className="text-muted-foreground"
          style={{ fontSize: 30, fontWeight: 500, letterSpacing: "0.04em" }}
        >
          {SLOGAN}
        </div>
      </div>
    </AbsoluteFill>
  );
}
