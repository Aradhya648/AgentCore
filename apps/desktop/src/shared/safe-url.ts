// SECURITY helper (XSS-002 前端XSS·外链交付) — the single allow-list deciding which URLs
// may be handed to the OS. Used by the Electron main `setWindowOpenHandler` BEFORE
// `shell.openExternal`.
//
// Why this exists: `shell.openExternal` will launch ANY registered URI scheme —
// `file://`, `ms-msdt:`, `search-ms:`, a custom app-protocol — and several of those are
// Follina-class local-execution vectors on Windows. The renderer reaches that sink via
// `target="_blank"` anchors, and some of those anchors carry attacker-INFLUENCEABLE URLs
// (a web-search source card / tool-result URL), bypassing react-markdown's own URL
// sanitization (which only guards markdown `[]()` / `![]()`). So the main process must
// filter every outbound URL down to the web-navigable schemes a user actually expects a
// link to open, and deny the rest.
//
// Pure + dependency-free so both the Electron main bundle and unit tests import it.

const SAFE_EXTERNAL_SCHEMES: ReadonlySet<string> = new Set([
  "http:",
  "https:",
  "mailto:",
]);

/**
 * True only when `value` is an absolute URL whose scheme is one a user-facing link may
 * safely open in the OS (`http` / `https` / `mailto`). Relative / malformed URLs and every
 * other scheme (`file:`, `javascript:`, `data:`, `ms-msdt:`, custom protocols, …) return
 * false — they must never be passed to `shell.openExternal`.
 */
export function isSafeExternalUrl(value: unknown): boolean {
  if (typeof value !== "string" || value.trim() === "") return false;
  let parsed: URL;
  try {
    parsed = new URL(value);
  } catch {
    // No scheme (relative) or malformed → not something we hand to the OS shell.
    return false;
  }
  return SAFE_EXTERNAL_SCHEMES.has(parsed.protocol.toLowerCase());
}
