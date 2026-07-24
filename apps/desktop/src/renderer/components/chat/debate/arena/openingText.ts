import type { DebateModel } from "../model";

/**
 * 主持人开场白：仅取 AI 真实产出的 `opening`（可选、渐进式契约）。
 * 空 ⇒ 返回空串、不渲染入场——不再用模板拼接假冒主持人开口（无 opening 时开场由第 1 轮焦点标题承担）。
 */
export function openingText(model: DebateModel): string {
  return model.opening?.trim() ?? "";
}
