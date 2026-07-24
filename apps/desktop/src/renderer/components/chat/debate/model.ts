/**
 * 辩论视图模型 (方案 A · 单一来源) —— 把「进行中」(transport-only `debateRounds` +
 * 辩手 run 树) 与「收场」(权威 `debate_result`) **收敛成同一个规范化模型**，让一个常驻
 * 外壳全程渲染、不再 live↔收场 卸载重挂 (跳跃的根因)。
 *
 * 这能成立是因为后端**故意**把进行中逐轮 ({@link DebateNarrativeRound}) 与收场逐轮
 * ({@link DebateRoundInfo}) 设计成同构孪生 (辩论编排设计.md §7.4 · `verdict` 可空是唯一
 * 差别)；两套前端树本是实现产物，违背了数据模型意图。
 *
 * **固有接缝 (非补丁)**：进行中、当前那一轮 (只定了焦点、尚未裁判) 没有权威的
 * round→`run_id` 映射——主持人是「先报焦点、再派辩手」，宣布焦点时辩手 run 尚未创建。
 * 故这一轮的发言**必须**从 run 树按 `round`/`stance` 标签取回 ({@link debateGroups} /
 * {@link debateLiveRounds})；已裁判轮与收场轮则走 `run_id` 直取。本模块把两路归一。
 */
export * from "./model/index";
