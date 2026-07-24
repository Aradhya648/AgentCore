import { AbsoluteFill } from "remotion";
import { PromoCanvas } from "../../core/chrome/PromoCanvas";
import { PromoShell } from "../../core/chrome/PromoShell";
import { DEMO_TASK } from "../../videos/brand-30s/data/demo";
import { buildBrandGraphState } from "../../videos/brand-30s/data/graphSpec";
import { DEMO_LAYOUT } from "../../videos/brand-30s/data/layout";
import { BRAND_SHELL_RECENT } from "../../videos/brand-30s/shellRecent";

/*
 * 领衔 promo still: the full desktop shell (TitleBar + Sidebar) with the product's
 * 对话级画布 (Canvas view) running inside the main area — the one image that says both
 * "this is a real product" and "a real team is alive in it", shown through the actual
 * Canvas UX (turn spine + a focused turn expanded into its live worker DAG + the 常驻
 * 命令栏). Reuses the real chrome pieces: PromoShell + PromoCanvas (which embeds the
 * real GraphStage butterfly), frozen at a settled mid-run frame.
 */

// 4:3 desktop window (unified promo ratio): 1920×1440. The shell is responsive, so a
// taller window is a faithful screenshot — it just gives the Canvas spine more room.
export const APPSHELL_W = 1920;
export const APPSHELL_H = 1440;

/** demo butterfly at the 辩论对射 beat (research done, debate live) */
const SPINE_FROZEN = 240;
const FPS = 30;

export function AppShellStill() {
  const { nodes, edges, debate } = buildBrandGraphState(SPINE_FROZEN, FPS);
  return (
    <AbsoluteFill className="bg-background">
      <PromoShell recent={BRAND_SHELL_RECENT} theme="light">
        <PromoCanvas
          taskTitle={DEMO_TASK}
          graphW={DEMO_LAYOUT.width}
          graphH={DEMO_LAYOUT.height}
          nodes={nodes}
          edges={edges}
          debate={debate}
          frame={SPINE_FROZEN}
        />
      </PromoShell>
    </AbsoluteFill>
  );
}
