/**
 * Same-path ``file_read`` ceiling rejection (Wave3 B / R1): engine soft-fail with
 * ``status:"error"`` so the model can self-correct, but the UI should read as
 * guidance — not the same red fault chrome as IO/missing-file failures.
 *
 * ``contract_failure`` stays server-only (circuit breaker); no wire enum. Detect
 * via tool name + stable backend copy cues (see ``file_ops._file_read_path_ceiling_error``).
 */
const CEILING_CUES = ["已多次读取", "勿再读", "再读次数"] as const;

export function isFileReadCeilingGuidance(
  toolName: string,
  result: string | null | undefined,
): boolean {
  if (toolName !== "file_read") return false;
  const text = result ?? "";
  if (!text) return false;
  return CEILING_CUES.some((cue) => text.includes(cue));
}
