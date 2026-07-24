/**
 * 应用内路由常量 —— 手册内容源 / SettingsTable / 深链唯一真相源。
 * 手册内禁止手写路由字符串，一律 import 本文件。
 */

export const APP_PATHS = {
  toolbox: {
    tools: "/toolbox/tools",
    manual: {
      root: "/toolbox/manual",
      intro: "/toolbox/manual/intro",
      collaboration: "/toolbox/manual/collaboration",
      mechanism: "/toolbox/manual/mechanism",
      reference: "/toolbox/manual/reference",
    },
  },
  more: {
    model: "/more/model",
    memory: "/more/memory",
    autonomy: "/more/autonomy",
    usage: "/more/usage",
    appearance: "/more/appearance",
    shortcuts: "/more/shortcuts",
    feedback: "/more/feedback",
    about: "/more/about",
    legal: {
      terms: "/more/legal/terms",
      privacy: "/more/legal/privacy",
      notice: "/more/legal/notice",
    },
  },
} as const;

export type ManualChapterId =
  | "intro"
  | "collaboration"
  | "mechanism"
  | "reference";

export const MANUAL_CHAPTER_PATHS: Record<ManualChapterId, string> = {
  intro: APP_PATHS.toolbox.manual.intro,
  collaboration: APP_PATHS.toolbox.manual.collaboration,
  mechanism: APP_PATHS.toolbox.manual.mechanism,
  reference: APP_PATHS.toolbox.manual.reference,
};
