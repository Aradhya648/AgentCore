import type { CapabilityPack } from "@/services/capabilities";

export type CapabilityPackPreviewScene = {
  id: string;
  title: string;
  intent: string;
  pack: CapabilityPack;
};

const LEGAL_SKILL = {
  name: "contract_review",
  summary: "审查合同风险条款与合规要点",
  body: "# 合同审查\n\n逐步核对违约、管辖与保密条款。",
};

/** Offline fixtures for `#/preview/capability-packs` + `pnpm shoot:capability-packs`. */
export const CAPABILITY_PACK_PREVIEW_SCENES: readonly CapabilityPackPreviewScene[] =
  [
    {
      id: "pack-listed",
      title: "能力包 · 已上架",
      intent: "法律能力包纯展示：名称 / 简介 / 包内技能，无交互",
      pack: {
        id: "legal",
        name: "法律能力",
        summary: "为你的 AI 团队补齐合同审查、法规检索与合规把关。",
        skills: [LEGAL_SKILL],
      },
    },
  ];
