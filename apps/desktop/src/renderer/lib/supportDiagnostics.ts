/**
 * Format conversation / message / trace / execution IDs for support & DEV diagnostics.
 * Users paste this blob when reporting; ops grep logs with the same keys.
 * Trailing line is a ready-to-run log_timeline.py command when trace or conversation is present.
 */
export function formatSupportDiagnosticText(ids: {
  conversationId?: string | null;
  messageId?: string | null;
  traceId?: string | null;
  executionId?: string | null;
}): string {
  const lines: string[] = [];
  const conversationId = ids.conversationId?.trim() || "";
  const messageId = ids.messageId?.trim() || "";
  const traceId = ids.traceId?.trim() || "";
  const executionId = ids.executionId?.trim() || "";

  if (conversationId) lines.push(`conversation_id: ${conversationId}`);
  if (messageId) lines.push(`message_id: ${messageId}`);
  if (traceId) lines.push(`trace_id: ${traceId}`);
  if (executionId) lines.push(`execution_id: ${executionId}`);

  if (traceId) {
    lines.push(`uv run python scripts/log_timeline.py --trace ${traceId}`);
  } else if (conversationId) {
    lines.push(`uv run python scripts/log_timeline.py ${conversationId}`);
  }

  return lines.join("\n");
}
