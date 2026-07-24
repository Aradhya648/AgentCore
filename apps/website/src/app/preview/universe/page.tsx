import type { Metadata } from "next";
import UniverseExperience from "@/components/universe/UniverseExperience";

/**
 * 方案 C「3D 沉浸宇宙」概念预览页（未挂到任何导航，不影响现首页）。
 * 打磨满意后再决定是否升格为正式首页。
 */

export const metadata: Metadata = {
  title: "AgentCore — 协作宇宙（3D 概念预览）",
  description:
    "滚动穿越一支 AI 团队的诞生：委派、并行、辩论、互审、裁决——协作，是更高级的智能。",
  robots: { index: false },
};

export default function UniversePreviewPage() {
  return <UniverseExperience />;
}
