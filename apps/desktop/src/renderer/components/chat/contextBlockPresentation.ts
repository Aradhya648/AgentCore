/**
 * 「收到的上下文」块呈现分类：复制型默认折叠为引用卡；增量型保持原分段卡。
 * 判定只看 channel 白名单，禁止对 body 做文本比对。
 */

/** Channels whose body is a copy/relay of another surface (upstream / history / request…). */
export const COPY_CONTEXT_CHANNELS = new Set([
  "dependency",
  "opponent",
  "history",
  "request",
  "team_result",
]);

/** True when this channel should render as a collapsed citation card by default. */
export function isCopyContextChannel(channel: string): boolean {
  return COPY_CONTEXT_CHANNELS.has(channel);
}

/** First non-empty line of body — citation-card summary when collapsed. */
export function contextBlockSummaryLine(body: string): string {
  for (const line of body.split(/\r?\n/)) {
    const trimmed = line.trim();
    if (trimmed) return trimmed;
  }
  return "";
}
