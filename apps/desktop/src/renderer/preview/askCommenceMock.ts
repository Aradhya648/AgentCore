import type { AskUserContent } from "@/components/chat/ask/AskUserFields";

/**
 * Shared mock for preview 开工提案 layout variants.
 * Mirrors a rich kickoff ask_user payload (起步计划 + 编号题 + 推荐/默认 + 风格).
 * Production kickoff uses the same V2 Brief + Choose body ({@link AskCommenceKickoffBody}).
 */
export const ASK_COMMENCE_MOCK: AskUserContent = {
  question: "按这版起步计划开做可以吗？有两处想先跟你对齐。",
  context:
    "需求能做，但方向还差两处对齐。\n先按可执行起步计划开做\n确认后立刻动手，途中可再改",
  assumptions: [
    { id: "a0", label: "交付物", value: "响应式落地页（单页）+ 基础 SEO" },
    { id: "a1", label: "部署", value: "纯静态，托管到现有 CDN" },
    {
      id: "a2",
      label: "首版范围",
      value: "Hero / 卖点 / 案例 / CTA，不含后台",
    },
    { id: "a3", label: "工期假设", value: "先出可上线稿，再迭代动效与文案" },
  ],
  questions: [
    {
      id: "q0",
      prompt: "主要给谁看？",
      kind: "choice",
      options: [
        {
          label: "潜在客户",
          detail: "偏转化：卖点清晰、CTA 突出",
          recommended: true,
        },
        { label: "投资人", detail: "偏叙事：愿景与里程碑优先" },
        { label: "内部评审", detail: "偏完整：信息密度更高" },
      ],
      multiple: false,
      default: "潜在客户",
    },
    {
      id: "q1",
      prompt: "首版要不要双语？",
      kind: "choice",
      options: [
        { label: "只要中文", recommended: true },
        { label: "中英双语", detail: "文案量约翻倍，首版会慢半拍" },
      ],
      multiple: false,
      default: "只要中文",
    },
  ],
  styleOptions: [
    { id: "s0", label: "克制专业" },
    { id: "s1", label: "活泼产品感" },
    { id: "s2", label: "深色科技" },
  ],
};

export type AskCommenceVariantId =
  | "ask-commence-v1"
  | "ask-commence-v2"
  | "ask-commence-v3"
  | "ask-commence-v4";

export interface AskCommenceScene {
  id: AskCommenceVariantId;
  /** Short label in the scene list. */
  title: string;
  /** One-line design intent for the product owner. */
  intent: string;
  /** Industry paradigm this layout borrows from. */
  paradigm: string;
}
