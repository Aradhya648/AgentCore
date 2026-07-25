/**
 * 协作图嵌入宿主契约——聊天内联 / 画布回合 / 全屏三入口共用。
 *
 * 单一约定（实现落在 GraphView + useGraphViewport + computeLayout）：
 * 1. Provider：每个 ReactFlow 实例由 GraphView 自带 ReactFlowProvider（内联不再缺宿主）。
 * 2. 尺寸：容器 ResizeObserver 测宽（width/contain）或由外层定高；bbox 来自
 *    computeLayout 的「已放置节点」包围盒（原点钉在 padding，无 ELK 虚高死区）。
 * 3. Fit：必须按内容包围盒，不得假设世界坐标从任意偏移起再手写 y=0 裁切。
 *    - view：ReactFlow fitView（全屏基准，勿回归）
 *    - width：fit-to-width；超宽/超高（EMBED_MAX_HEIGHT）均缩 zoom；高度跟
 *      **当前视觉 footprint**（`computeVisualBbox`：测高已到、二次 ELK 未完成也抬高/缩 zoom）
 *    - contain：等比装入容器（画布回合等）——仍用布局 bbox
 * 4. Overflow：内联卡片可 overflow-hidden 做圆角裁切；图区须先装下内容（缩 zoom），
 *    禁止靠外层裁切掩盖节点。fade 仅作极端兜底，非常态裁切路径。
 */
import { ReactFlowProvider } from "@xyflow/react";
import type { ReactNode } from "react";

export type GraphFitMode = "width" | "contain" | "view";

/** Wraps one ReactFlow instance. Safe to nest when an ancestor also provides. */
export function GraphFlowHost({ children }: { children: ReactNode }) {
  return <ReactFlowProvider>{children}</ReactFlowProvider>;
}
