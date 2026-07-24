/**
 * 异步团队收口：系统合成的「用户」消息（metadata.origin=execution_harvest）。
 * REST MessageDetail 暴露 ``origin``；正文前缀保留为旧数据兜底。
 */

export const EXECUTION_HARVEST_ORIGIN = "execution_harvest";

/** StatusStrip / 时间线芯片文案 */
export const HARVEST_SYSTEM_CHIP_LABEL = "后台团队已完成，系统自动收口";

/** 后端落库的合成用户消息正文前缀（execution_harvest.py `_HARVEST_USER_TEXT`）。 */
export const HARVEST_USER_CONTENT_PREFIX = "【系统收口】";

export function isExecutionHarvestMessage(msg: {
  role: string;
  content: string;
  origin?: string | null;
}): boolean {
  if (msg.role !== "user") return false;
  if (msg.origin === EXECUTION_HARVEST_ORIGIN) return true;
  return msg.content.startsWith(HARVEST_USER_CONTENT_PREFIX);
}
