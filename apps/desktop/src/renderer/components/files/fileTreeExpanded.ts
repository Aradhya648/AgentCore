import { uiGet, uiSet } from "@/lib/uiStorage";

const expandedKey = (id: string): string => `filetree-expanded:${id}`;

export function loadExpanded(id: string): Set<string> {
  const parsed = uiGet<unknown>(expandedKey(id));
  if (!Array.isArray(parsed)) return new Set();
  return new Set(parsed.filter((p): p is string => typeof p === "string"));
}

export function saveExpanded(id: string, set: Set<string>): void {
  uiSet(expandedKey(id), [...set]);
}
