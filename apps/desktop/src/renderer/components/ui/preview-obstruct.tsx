import { popOverlay, pushOverlay } from "@/stores/overlay";
import { useEffect } from "react";

/**
 * 渲染 null、只做副作用：挂载时 {@link pushOverlay}、卸载时 {@link popOverlay}，用于标记
 * 「一个遮挡型弹层正打开」，好让内嵌预览的原生 WebContentsView 让位隐藏（否则它会盖住弹层）。
 *
 * 必须放在 Radix Portal **内部**（`*Content` 里）——Portal 仅在弹层 open 时挂载子树，故本组件的
 * 挂载/卸载精确对应弹层的开/关。放在 Portal 外（如 `*Content` 组件顶层）会因 Radix 常驻渲染而
 * 在关闭态也误计数。
 */
export function PreviewObstruct() {
  useEffect(() => {
    pushOverlay();
    return popOverlay;
  }, []);
  return null;
}
