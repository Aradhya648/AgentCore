/**
 * Format a paste-ready「排查包」for support / Cursor AI log lookup.
 * Lead line triggers conversation-logs workflow; trailing line is log_timeline.py.
 * Always available from error cards and bubble「更多」(not gated by 诊断模式).
 */
export function formatSupportDiagnosticText(ids: {
  conversationId?: string | null;
  messageId?: string | null;
  traceId?: string | null;
  executionId?: string | null;
}): string {
  const conversationId = ids.conversationId?.trim() || "";
  const messageId = ids.messageId?.trim() || "";
  const traceId = ids.traceId?.trim() || "";
  const executionId = ids.executionId?.trim() || "";

  const idLines: string[] = [];
  if (conversationId) idLines.push(`conversation_id: ${conversationId}`);
  if (messageId) idLines.push(`message_id: ${messageId}`);
  if (traceId) idLines.push(`trace_id: ${traceId}`);
  if (executionId) idLines.push(`execution_id: ${executionId}`);
  if (idLines.length === 0) return "";

  const lines = ["阅读这段产品AI日志：", ...idLines];
  if (traceId) {
    lines.push(`uv run python scripts/log_timeline.py --trace ${traceId}`);
  } else if (conversationId) {
    lines.push(`uv run python scripts/log_timeline.py ${conversationId}`);
  }

  return lines.join("\n");
}
