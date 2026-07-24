import { uiGet, uiSet } from "@/lib/uiStorage";

/** `ws_id = conv:<conversationId>` → its conversation id (scratch workspace). */
export function conversationIdOf(wsId: string): string | null {
  return wsId.startsWith("conv:") ? wsId.slice("conv:".length) : null;
}

/** `ws_id = folder:<folderId>` → its folder id (project shared workspace). */
export function folderIdOf(wsId: string): string | null {
  return wsId.startsWith("folder:") ? wsId.slice("folder:".length) : null;
}

const RAIL_KEY = "files-rail-width";
const RAIL_MIN = 200;
const RAIL_MAX = 600;
const RAIL_DEFAULT = 288; // = Tailwind w-72，沿用旧固定宽度作默认

export function clampRail(px: number): number {
  return Math.min(RAIL_MAX, Math.max(RAIL_MIN, Math.round(px)));
}

export function loadRailWidth(): number {
  const raw = uiGet<number>(RAIL_KEY);
  return typeof raw === "number" && Number.isFinite(raw)
    ? clampRail(raw)
    : RAIL_DEFAULT;
}

export function saveRailWidth(px: number): void {
  uiSet(RAIL_KEY, clampRail(px));
}

// Generic Set<string> persistence — every rail fold state (工作区段 / 记忆段 /
// 主题子夹) is "a set of ids in their non-default state". Tolerates unavailable / corrupt storage.
function loadStringSet(key: string): Set<string> {
  const parsed = uiGet<unknown>(key);
  if (!Array.isArray(parsed)) return new Set();
  return new Set(parsed.filter((p): p is string => typeof p === "string"));
}

function saveStringSet(key: string, set: Set<string>): void {
  uiSet(key, [...set]);
}

// 工作区段默认折叠（只露根标题），展开过的记进这个 set 持久化，下次进页面沿用
// （与 FileTree 内部 per-source 目录折叠态各管一层：这一层管「整个工作区段是否展开」）。
const WS_EXPANDED_KEY = "files-ws-expanded";

export function loadExpandedWs(): Set<string> {
  return loadStringSet(WS_EXPANDED_KEY);
}

export function saveExpandedWs(set: Set<string>): void {
  saveStringSet(WS_EXPANDED_KEY, set);
}

// 记忆段折叠态：全局段**默认展开**（保住老肌肉记忆），故只持久化「被折叠」的键——空集 =
// 展开（新用户零配置即得默认）。现仅全局段（键 "global"）使用；项目段默认折叠、走下方
// MEMORY_PROJECTS_EXPANDED_KEY 的「记展开」语义（旧挂载时代的 folderId 残留条目无害，被忽略）。
const MEMORY_COLLAPSED_KEY = "files-memory-collapsed";

export function loadMemoryCollapsed(): Set<string> {
  return loadStringSet(MEMORY_COLLAPSED_KEY);
}

export function saveMemoryCollapsed(set: Set<string>): void {
  saveStringSet(MEMORY_COLLAPSED_KEY, set);
}

// 主题子夹展开态：**默认折叠**（懒列），故只持久化「被展开」的作用域——空集 = 全部折叠。
const MEMORY_TOPICS_EXPANDED_KEY = "files-memory-topics-expanded";

export function loadMemoryTopicsExpanded(): Set<string> {
  return loadStringSet(MEMORY_TOPICS_EXPANDED_KEY);
}

export function saveMemoryTopicsExpanded(set: Set<string>): void {
  saveStringSet(MEMORY_TOPICS_EXPANDED_KEY, set);
}

// 项目「记忆」节点展开态：挂在每个项目下的「记忆」子节点**默认折叠**，故只持久化「被展开」
// 的 folderId——空集 = 全部折叠。（旧「项目记忆」聚合夹的 "__projects__" 残留键无害、被忽略。）
const MEMORY_PROJECTS_EXPANDED_KEY = "files-memory-projects-expanded";

export function loadMemoryProjectsExpanded(): Set<string> {
  return loadStringSet(MEMORY_PROJECTS_EXPANDED_KEY);
}

export function saveMemoryProjectsExpanded(set: Set<string>): void {
  saveStringSet(MEMORY_PROJECTS_EXPANDED_KEY, set);
}

// 规则段折叠态：主段（「你的规则」）**默认展开**（与记忆段同肌肉记忆），故只持久化「被折叠」
// 的键——空集 = 展开。键名 "root"。
const RULES_COLLAPSED_KEY = "files-rules-collapsed";

export function loadRulesCollapsed(): Set<string> {
  return loadStringSet(RULES_COLLAPSED_KEY);
}

export function saveRulesCollapsed(set: Set<string>): void {
  saveStringSet(RULES_COLLAPSED_KEY, set);
}

// 项目「规则」节点展开态：挂在每个项目下的「规则」子节点**默认折叠**，故只持久化「被展开」
// 的 folderId——空集 = 全部折叠。（旧「项目规则」聚合夹的 "__projects__" 残留键无害、被忽略。）
const RULES_EXPANDED_KEY = "files-rules-expanded";

export function loadRulesExpanded(): Set<string> {
  return loadStringSet(RULES_EXPANDED_KEY);
}

export function saveRulesExpanded(set: Set<string>): void {
  saveStringSet(RULES_EXPANDED_KEY, set);
}

export interface Tab {
  wsId: string;
  path: string;
  name: string;
}

/** Stable per-file key (a workspace's path is unique within it). */
export function tabKey(wsId: string, path: string): string {
  return `${wsId}:${path}`;
}
