/**
 * 后台进程输出：strip ANSI（MVP 不引 xterm；终端 tab 纯文本滚屏）。
 */

/** CSI / OSC 等常见 ESC 序列（用 String.fromCharCode 避开 regex 控制字符 lint）。 */
const ESC = String.fromCharCode(0x1b);
const BEL = String.fromCharCode(0x07);
const ANSI_RE = new RegExp(
  `${ESC}(?:[@-Z\\\\-_]|\\[[0-?]*[ -/]*[@-~]|\\][^${BEL}]*(?:${BEL}|${ESC}\\\\))`,
  "g",
);

export function stripAnsi(text: string): string {
  return text.replace(ANSI_RE, "");
}

/** UI 侧输出截断（保留尾部），与主进程环形 buffer 同量级。 */
export const UI_OUTPUT_CAP = 1024 * 1024;

export function appendUiOutput(
  current: string,
  chunk: string,
  cap = UI_OUTPUT_CAP,
): string {
  if (!chunk) return current;
  const next = current + chunk;
  if (next.length <= cap) return next;
  return next.slice(next.length - cap);
}

/**
 * 终端 tab 条件显隐：本对话有后台进程 / 执行记录 / 用户终端，或可新开交互 shell。
 */
export function shouldShowTerminalTab(
  processCount: number,
  recordCount = 0,
  ptyCount = 0,
  canOpenPty = false,
): boolean {
  return processCount > 0 || recordCount > 0 || ptyCount > 0 || canOpenPty;
}

/** 人类可读时长（自 started_at ISO）。 */
export function formatProcessDuration(
  startedAt: string,
  nowMs = Date.now(),
): string {
  const start = Date.parse(startedAt);
  if (!Number.isFinite(start)) return "—";
  const sec = Math.max(0, Math.floor((nowMs - start) / 1000));
  if (sec < 60) return `${sec}s`;
  const min = Math.floor(sec / 60);
  if (min < 60) return `${min}m ${sec % 60}s`;
  const hr = Math.floor(min / 60);
  return `${hr}h ${min % 60}m`;
}
