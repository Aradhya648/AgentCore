/**
 * 手册节 ID 集中注册表 —— 功能现场深链 / JumpLink / 内容源共用。
 *
 * 目标信息架构（后续三章子代理只填 content/*.ts，不改本文件与 Shell）：
 * - intro: what / mindset / quickstart
 * - collaboration: collab-overview / briefing / roles / progress / checkpoint /
 *   control / debate / continuation / memory（另保留 autonomy）
 * - mechanism: live / legend / panorama / turnflow / scenarios
 * - reference: chat / tools / workspace / settings / faq / troubleshooting /
 *   privacy / glossary
 */

import { MANUAL_CHAPTER_PATHS, type ManualChapterId } from "./paths";

export const MANUAL_SECTION_IDS = {
  intro: {
    what: "what",
    mindset: "mindset",
    quickstart: "quickstart",
  },
  collaboration: {
    "collab-overview": "collab-overview",
    briefing: "briefing",
    roles: "roles",
    progress: "progress",
    checkpoint: "checkpoint",
    control: "control",
    debate: "debate",
    continuation: "continuation",
    memory: "memory",
    /** 权限配方（徽章「设为新会话默认」；手机设置） */
    autonomy: "autonomy",
  },
  mechanism: {
    live: "live",
    legend: "legend",
    panorama: "panorama",
    turnflow: "turnflow",
    scenarios: "scenarios",
  },
  reference: {
    chat: "chat",
    tools: "tools",
    workspace: "workspace",
    settings: "settings",
    faq: "faq",
    troubleshooting: "troubleshooting",
    privacy: "privacy",
    glossary: "glossary",
  },
} as const;

export type IntroSectionId =
  (typeof MANUAL_SECTION_IDS.intro)[keyof typeof MANUAL_SECTION_IDS.intro];
export type CollaborationSectionId =
  (typeof MANUAL_SECTION_IDS.collaboration)[keyof typeof MANUAL_SECTION_IDS.collaboration];
export type MechanismSectionId =
  (typeof MANUAL_SECTION_IDS.mechanism)[keyof typeof MANUAL_SECTION_IDS.mechanism];
export type ReferenceSectionId =
  (typeof MANUAL_SECTION_IDS.reference)[keyof typeof MANUAL_SECTION_IDS.reference];

export type ManualSectionId =
  | IntroSectionId
  | CollaborationSectionId
  | MechanismSectionId
  | ReferenceSectionId;

/** 节 ID → 所属章（供 JumpLink 跨节回退导航）。 */
const SECTION_OWNER: Record<string, ManualChapterId> = (() => {
  const map: Record<string, ManualChapterId> = {};
  for (const [chapterId, sections] of Object.entries(MANUAL_SECTION_IDS) as [
    ManualChapterId,
    Record<string, string>,
  ][]) {
    for (const id of Object.values(sections)) {
      map[id] = chapterId;
    }
  }
  return map;
})();

/** 章 + 节 → 深链 path（含 `?s=`）。 */
export function manualHref(
  chapter: ManualChapterId,
  section: ManualSectionId | string,
): string {
  return `${MANUAL_CHAPTER_PATHS[chapter]}?s=${section}`;
}

/** 仅知节 ID 时解析深链；未知节返回 null。 */
export function resolveSectionHref(sectionId: string): string | null {
  const chapter = SECTION_OWNER[sectionId];
  if (!chapter) return null;
  return manualHref(chapter, sectionId);
}

/** 节是否在注册表中。 */
export function isRegisteredSectionId(sectionId: string): boolean {
  return sectionId in SECTION_OWNER;
}

export function chapterOfSection(
  sectionId: string,
): ManualChapterId | undefined {
  return SECTION_OWNER[sectionId];
}
