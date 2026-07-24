export type OnboardingPreviewScene = {
  id: string;
  title: string;
  intent: string;
  /** Draft empty-state kind or composer generating variant. */
  kind:
    | "empty-starter-chips"
    | "empty-returning"
    | "composer-generating-bar"
    | "composer-generating-card";
};

export const ONBOARDING_PREVIEW_SCENES: readonly OnboardingPreviewScene[] = [
  {
    id: "empty-starter-chips",
    title: "空态 · 首启任务",
    intent: "问候 + chips + 输入框居中成一体",
    kind: "empty-starter-chips",
  },
  {
    id: "empty-returning",
    title: "空态 · 老用户",
    intent: "单句问候 + 输入框居中成一体",
    kind: "empty-returning",
  },
  {
    id: "composer-generating-bar",
    title: "生成中 · 底部条插话",
    intent: "回合执行中：发送=插话，停止键并存（bar 单行）",
    kind: "composer-generating-bar",
  },
  {
    id: "composer-generating-card",
    title: "生成中 · 画布栏插话",
    intent: "回合执行中：画布命令栏（card）同样可插话",
    kind: "composer-generating-card",
  },
];
