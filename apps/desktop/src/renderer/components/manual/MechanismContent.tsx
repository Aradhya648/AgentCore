/**
 * 运行机制真图嵌入件（产品手册「看懂协作」章）。
 *
 * 由 `pages/toolbox/manual/content/mechanism.ts` 经 `embed` block 引用；
 * 全屏壳 / 顶栏 / 目录归手册页。叙事正文在内容源，本模块只提供协作图真图。
 *
 * 真图三件：① `HeroGraph` 看团队跑一遍 ② `GraphLegend` 图例
 * ③ `MechanismScenarios` 机制场景画廊。
 * 共用 `EmbeddedGraphCanvas`（真实 AgentNode / StepEdge / ELK / WaveLanes）。
 * 拍板卡 / 审批卡 / 记分牌等 UI 预览在 `pages/toolbox/manual/embeds/`，不经本 barrel。
 */
export { GraphLegend } from "./mechanism/GraphLegend";
export { HeroGraph } from "./mechanism/HeroGraph";
export { MechanismScenarios } from "./mechanism/MechanismScenarios";
