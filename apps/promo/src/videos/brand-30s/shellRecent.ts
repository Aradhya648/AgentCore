import type { RecentConversation } from "../../core/chrome/PromoShell";
import { DEMO_TASK } from "./data/demo";

/** Sidebar recent list for brand-30s / stills that reuse the hero task title. */
export const BRAND_SHELL_RECENT: RecentConversation[] = [
  { title: DEMO_TASK, active: true, running: true },
  { title: "竞品调研与定价策略对比", active: false, running: false },
  { title: "周报：本周进展与下周计划", active: false, running: false },
  { title: "重构 DAG 调度器的方案讨论", active: false, running: false },
  { title: "给新功能起一个好名字", active: false, running: false },
];
