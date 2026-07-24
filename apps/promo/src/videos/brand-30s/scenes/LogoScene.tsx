import { AbsoluteFill, interpolate, useCurrentFrame } from "remotion";
import { entranceStyle } from "../../../core/motion/primitives";

/*
 * 27–30s end card (scene-local 0–90 @30fps): brand lockup, no CTA
 * (apps/promo/README.md). A small collaboration-network glyph, the AgentCore
 * wordmark, then the slogan「协作，是更高级的智能」— each easing up in sequence
 * over a soft primary glow.
 */

// A tiny collaboration network: a hub linked to three peers (the team motif).
const NODES = [
  { x: 60, y: 60, r: 11 },
  { x: 16, y: 26, r: 7 },
  { x: 108, y: 22, r: 7 },
  { x: 100, y: 104, r: 7 },
];
const LINKS = [
  [0, 1],
  [0, 2],
  [0, 3],
  [1, 2],
];

export function LogoScene() {
  const frame = useCurrentFrame();

  const glyph = entranceStyle(frame, 4, 16);
  const word = entranceStyle(frame, 16, 16);
  const slogan = entranceStyle(frame, 30, 16);
  const glyphScale = interpolate(frame, [4, 24], [0.82, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const glowOpacity = interpolate(frame, [0, 30], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const cardOpacity = interpolate(frame, [0, 12], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  return (
    <AbsoluteFill
      className="bg-background"
      style={{
        alignItems: "center",
        justifyContent: "center",
        opacity: cardOpacity,
      }}
    >
      <div
        style={{
          position: "absolute",
          width: 900,
          height: 900,
          borderRadius: "50%",
          background:
            "radial-gradient(circle, var(--primary) 0%, transparent 62%)",
          opacity: 0.1 * glowOpacity,
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
        <div
          style={{
            opacity: glyph.opacity,
            transform: `${glyph.transform} scale(${glyphScale})`,
          }}
        >
          <svg width={132} height={132} viewBox="0 0 132 132" role="presentation">
            <g transform="translate(6 6)">
              {LINKS.map(([a, b]) => (
                <line
                  key={`${a}-${b}`}
                  x1={NODES[a].x}
                  y1={NODES[a].y}
                  x2={NODES[b].x}
                  y2={NODES[b].y}
                  stroke="var(--primary)"
                  strokeWidth={2.5}
                  opacity={0.5}
                />
              ))}
              {NODES.map((n, i) => (
                <circle
                  key={i}
                  cx={n.x}
                  cy={n.y}
                  r={n.r}
                  fill="var(--primary)"
                  opacity={i === 0 ? 1 : 0.85}
                />
              ))}
            </g>
          </svg>
        </div>

        <div
          className="text-foreground"
          style={{
            opacity: word.opacity,
            transform: word.transform,
            fontSize: 76,
            fontWeight: 600,
            letterSpacing: "-0.01em",
          }}
        >
          AgentCore
        </div>

        <div
          className="text-muted-foreground"
          style={{
            opacity: slogan.opacity,
            transform: slogan.transform,
            fontSize: 30,
            fontWeight: 500,
            letterSpacing: "0.04em",
          }}
        >
          协作，是更高级的智能
        </div>
      </div>
    </AbsoluteFill>
  );
}
