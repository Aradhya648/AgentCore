import type { ReactNode } from "react";
import { AbsoluteFill, interpolate, useCurrentFrame, useVideoConfig } from "remotion";
import { mainBox, PromoShell } from "../../../core/chrome/PromoShell";
import { GraphStage } from "../../../core/graph/GraphStage";
import { entranceStyle } from "../../../core/motion/primitives";
import { DEBATE_SNIPPETS, OVERLAYS } from "../data/coldOpen";
import { buildLvDebateGraph, DEBATE_LAYOUT } from "../data/debateGraph";
import { LV_SHELL_RECENT } from "../shellRecent";
import { COLD_CUT, COLD_HOOK } from "../timeline";
import { DecisionBriefCard, ScorePanelCard } from "./HighlightCards";

/*
 * ~15s cold-open highlight reel (scene-local):
 *   cut 0  协作图 + 辩论对射 + 「两个 AI，一场庭审」
 *   cut 1  辩论正文特写（无字幕）
 *   cut 2  末轮评分简化卡（无字幕）
 *   cut 3  决策简报简化卡 + 「20 分钟，一句话触发」
 *   hook   「AI 组团打了一场模拟庭审」
 */

function cutOpacity(local: number, cutLen: number): number {
  return interpolate(local, [0, 6, cutLen - 8, cutLen], [0, 1, 1, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
}

function BigOverlay({ text, frame, enterAt }: { text: string; frame: number; enterAt: number }) {
  const style = entranceStyle(frame, enterAt, 12);
  return (
    <div
      style={{
        position: "absolute",
        left: 0,
        right: 0,
        bottom: 72,
        display: "flex",
        justifyContent: "center",
        zIndex: 5,
        opacity: style.opacity,
        transform: style.transform,
        pointerEvents: "none",
      }}
    >
      <div
        className="rounded-2xl bg-background/75 px-8 py-3.5 text-4xl font-semibold text-foreground"
        style={{
          backdropFilter: "blur(10px)",
          WebkitBackdropFilter: "blur(10px)",
          letterSpacing: "0.02em",
          boxShadow: "0 8px 40px rgb(0 0 0 / 0.35)",
        }}
      >
        {text}
      </div>
    </div>
  );
}

function ShotShell({
  opacity,
  children,
}: {
  opacity: number;
  children: ReactNode;
}) {
  return (
    <AbsoluteFill style={{ opacity }}>
      {children}
    </AbsoluteFill>
  );
}

function ShotGraph({ frame }: { frame: number }) {
  const { width, height } = useVideoConfig();
  const { width: boxWidth, height: boxHeight } = mainBox(width, height);
  const { nodes, edges, debate } = buildLvDebateGraph(frame);
  return (
    <GraphStage
      nodes={nodes}
      edges={edges}
      debate={debate}
      frame={frame}
      cinematic
      boxWidth={boxWidth}
      boxHeight={boxHeight}
      graphW={DEBATE_LAYOUT.width}
      graphH={DEBATE_LAYOUT.height}
      padX={100}
      padY={120}
      showBackground
    />
  );
}

function ShotDebateText({ local }: { local: number }) {
  // Two snippets visible at a time; swap mid-cut for density.
  const phase = local < COLD_CUT / 2 ? 0 : 1;
  const a = DEBATE_SNIPPETS[phase * 2];
  const b = DEBATE_SNIPPETS[phase * 2 + 1];
  const fade = entranceStyle(local, phase === 0 ? 4 : 4, 10);

  return (
    <div
      className="flex h-full w-full items-center justify-center px-16"
      style={{ opacity: fade.opacity }}
    >
      <div className="flex w-full max-w-5xl flex-col gap-5">
        <SnippetCard side={a.side} stance={a.stance} text={a.text} />
        <SnippetCard side={b.side} stance={b.stance} text={b.text} />
      </div>
    </div>
  );
}

function SnippetCard({
  side,
  stance,
  text,
}: {
  side: string;
  stance: "pro" | "con";
  text: string;
}) {
  const sideTone = stance === "pro" ? "text-primary" : "text-success";
  const barTone = stance === "pro" ? "border-l-primary" : "border-l-success";
  return (
    <div
      className={`rounded-xl border border-border border-l-4 bg-card/90 px-6 py-5 shadow-md ${barTone}`}
    >
      <div className={`mb-2 text-sm font-medium tracking-wide ${sideTone}`}>
        {side}
      </div>
      <div className="text-2xl leading-relaxed text-foreground">{text}</div>
    </div>
  );
}

function ShotCentered({ children }: { children: ReactNode }) {
  return (
    <div className="flex h-full w-full items-center justify-center">{children}</div>
  );
}

function HookBeat({ local }: { local: number }) {
  const style = entranceStyle(local, 6, 14);
  const scale = interpolate(local, [6, 30], [0.94, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  return (
    <AbsoluteFill
      className="bg-background"
      style={{
        alignItems: "center",
        justifyContent: "center",
      }}
    >
      <div
        className="text-foreground"
        style={{
          opacity: style.opacity,
          transform: `${style.transform} scale(${scale})`,
          fontSize: 56,
          fontWeight: 600,
          letterSpacing: "0.02em",
          textAlign: "center",
          maxWidth: 1200,
          lineHeight: 1.35,
        }}
      >
        {OVERLAYS.hook}
      </div>
    </AbsoluteFill>
  );
}

export function ColdOpenMain() {
  const frame = useCurrentFrame();
  const cutIdx = Math.min(3, Math.floor(frame / COLD_CUT));
  const inHook = frame >= COLD_CUT * 4;
  const local = inHook ? frame - COLD_CUT * 4 : frame - cutIdx * COLD_CUT;

  if (inHook) {
    const op = interpolate(local, [0, 8, COLD_HOOK - 6, COLD_HOOK], [0, 1, 1, 1], {
      extrapolateLeft: "clamp",
      extrapolateRight: "clamp",
    });
    return (
      <ShotShell opacity={op}>
        <HookBeat local={local} />
      </ShotShell>
    );
  }

  const op = cutOpacity(local, COLD_CUT);

  if (cutIdx === 0) {
    return (
      <ShotShell opacity={op}>
        <PromoShell recent={LV_SHELL_RECENT} theme="dark">
          <ShotGraph frame={frame} />
        </PromoShell>
        <BigOverlay text={OVERLAYS.shot1} frame={local} enterAt={10} />
      </ShotShell>
    );
  }
  if (cutIdx === 1) {
    return (
      <ShotShell opacity={op}>
        <ShotDebateText local={local} />
      </ShotShell>
    );
  }
  if (cutIdx === 2) {
    const card = entranceStyle(local, 8, 12);
    return (
      <ShotShell opacity={op}>
        <ShotCentered>
          <div style={{ opacity: card.opacity, transform: card.transform }}>
            <ScorePanelCard />
          </div>
        </ShotCentered>
      </ShotShell>
    );
  }
  // cut 3 — decision brief
  const card = entranceStyle(local, 8, 12);
  return (
    <ShotShell opacity={op}>
      <ShotCentered>
        <div style={{ opacity: card.opacity, transform: card.transform }}>
          <DecisionBriefCard />
        </div>
      </ShotCentered>
      <BigOverlay text={OVERLAYS.shot4} frame={local} enterAt={18} />
    </ShotShell>
  );
}
