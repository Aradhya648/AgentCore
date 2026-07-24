/** Built-in tools that rely on LLM tool-calling (开放主流AI模型接入 §4.5). */
export const TOOL_CALLING_TOOL_NAMES = new Set(["delegate", "debate"]);

/**
 * Soft hint when probe reported `supports_tools === false`.
 * Probe failure ≠ hard unsupported — match backend preflight warning, not a block.
 */
export const TOOLS_GATE_HINT =
  "连接测试未确认工具调用支持，委派/辩论可能降级；实际以运行为准，可在模型设置重新测试";

/** True when probe said tools are unconfirmed — show soft hint only, never hard-block UI. */
export function needsToolsGateHint(
  supportsTools: boolean | null | undefined,
): boolean {
  return supportsTools === false;
}
