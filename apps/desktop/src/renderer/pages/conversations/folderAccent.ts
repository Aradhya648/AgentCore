/**
 * Stable project accent from folder id/name — same palette as agent identity
 * (`--agent-N` in design-tokens). No color field on FolderMeta.
 */

const PALETTE_SIZE = 8;

function hashKey(key: string): number {
  let h = 0x811c9dc5;
  for (let i = 0; i < key.length; i++) {
    h ^= key.charCodeAt(i);
    h = Math.imul(h, 0x01000193);
  }
  return h >>> 0;
}

/** 1-based `--agent-N` slot from folder id (preferred) or name. */
export function folderAccentIndex(idOrName: string): number {
  const key = idOrName.trim();
  if (!key) return 1;
  return (hashKey(key) % PALETTE_SIZE) + 1;
}

/** CSS `var(--agent-N)` for inline style (color-tokens.mdc). */
export function folderAccentVar(idOrName: string): string {
  return `var(--agent-${folderAccentIndex(idOrName)})`;
}
