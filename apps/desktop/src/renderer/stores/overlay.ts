import { create } from "zustand";

/**
 * 应用内弹层遮挡计数（内嵌预览遮挡管理专用）。
 *
 * 原生 WebContentsView（SidePanel「预览」tab）恒盖在 DOM 之上，任何盖住该区域的应用内弹层
 * （Dialog / DropdownMenu / ContextMenu / 命令面板等，均走 Radix Portal）打开时都会被原生视图
 * 挡住而不可用。故这些弹层的 Portal 内容挂载时 {@link pushOverlay}、卸载时 {@link popOverlay}，
 * 计数 > 0 → 内嵌预览让位隐藏（见 lib/embeddedPreview.embeddedPreviewVisible）。
 *
 * 计数（非布尔）以支持多层叠加（如 dialog 里再开 dropdown）；命令面板走 Dialog 故自动覆盖。
 * 非模态、几乎不覆盖该区域且高频的 Popover（@ 提及）/ Tooltip 刻意不接入，避免频繁闪隐。
 */
interface OverlayState {
  /** 当前打开、需让内嵌预览隐藏的弹层层数。 */
  count: number;
}

export const useOverlayStore = create<OverlayState>(() => ({ count: 0 }));

/** 一个遮挡型弹层已打开（Portal 内容挂载时调）。 */
export function pushOverlay(): void {
  useOverlayStore.setState((s) => ({ count: s.count + 1 }));
}

/** 一个遮挡型弹层已关闭（Portal 内容卸载时调）；钳非负防错配。 */
export function popOverlay(): void {
  useOverlayStore.setState((s) => ({ count: Math.max(0, s.count - 1) }));
}
