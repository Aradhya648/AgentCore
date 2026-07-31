/**
 * 工作区列举忽略规则（两档，与服务端 `workspace/_paths.py` 对齐）。
 *
 * 改名单须双边同步；对账门禁（漏改一侧必红）::
 *
 *   cd apps/server && uv run python scripts/check_workspace_ignore_parity.py
 *
 * - **系统噪音**：对 AI 与用户文件 UI 都隐藏（目录 + `*.db` / `*.pyc` 等）。
 * - **AI 噪音**：媒体 / 压缩包 / 字体 / 二进制对象——仅从 AI 视角排除
 *  （`collectWorkspaceFiles` / `opIndexFiles` / `opList` / `opListTree` / grep）；
 *   文件 UI（`listDir`）保持可见，避免 AI 生成的图片/压缩包在面板被藏掉。
 *
 * 同树旁路 `AgentCore/{index,trash,baselines}` 为路径感知系统噪音（禁止把裸名
 * `index`/`trash`/`baselines` 放进全局跳过集，以免误伤用户项目）。
 */

/** 与服务端 `stage_dirs.AGENTCORE_ROOT` 对齐。 */
export const AGENTCORE_ROOT = "AgentCore";

/** 与服务端 `stage_dirs.INTERNAL_ZONE_NAMES` 对齐。 */
export const INTERNAL_ZONE_NAMES = new Set(["index", "trash", "baselines"]);

export const INDEX_REL = `${AGENTCORE_ROOT}/index`;
export const TRASH_REL = `${AGENTCORE_ROOT}/trash`;
export const BASELINES_REL = `${AGENTCORE_ROOT}/baselines`;

/** 系统噪音目录（整棵子树）。↔ 服务端 `IGNORED_DIRS`（parity gate）。 */
export const LIST_FILES_SKIP_DIRS = new Set([
  ".git",
  ".hg",
  ".svn",
  "node_modules",
  "__pycache__",
  ".venv",
  "venv",
  ".mypy_cache",
  ".pytest_cache",
  ".ruff_cache",
  ".turbo",
  ".cache",
  "coverage",
  ".idea",
  ".vscode",
  "dist",
  "build",
  ".next",
  ".nuxt",
  ".vite",
  "out",
  "target",
]);

/** 系统噪音后缀（UI + AI）。↔ 服务端 `SYSTEM_IGNORED_FILE_SUFFIXES`（parity gate）。 */
export const SYSTEM_IGNORED_FILE_SUFFIXES = [
  ".db",
  ".sqlite",
  ".sqlite3",
  ".pyc",
  ".pyo",
] as const;

/** AI 噪音后缀（仅 AI）。↔ 服务端 `AI_NOISE_FILE_SUFFIXES`（parity gate）。 */
export const AI_NOISE_FILE_SUFFIXES = [
  ".class",
  ".o",
  ".a",
  ".lib",
  ".so",
  ".dylib",
  ".dll",
  ".exe",
  ".wasm",
  ".bin",
  ".dat",
  ".pack",
  ".idx",
  ".png",
  ".jpg",
  ".jpeg",
  ".gif",
  ".webp",
  ".ico",
  ".bmp",
  ".mp3",
  ".mp4",
  ".wav",
  ".webm",
  ".zip",
  ".tar",
  ".gz",
  ".tgz",
  ".bz2",
  ".7z",
  ".rar",
  ".woff",
  ".woff2",
  ".ttf",
  ".otf",
  ".eot",
] as const;

function endsWithAny(name: string, suffixes: readonly string[]): boolean {
  const lower = name.toLowerCase();
  return suffixes.some((suf) => lower.endsWith(suf));
}

/** True when relPath is `AgentCore/{index|trash|baselines}` or under it. */
export function isInternalZoneRelPath(relPath: string): boolean {
  const p = relPath.replace(/\\/g, "/").replace(/^\/+|\/+$/g, "");
  if (!p || p === ".") return false;
  for (const zone of INTERNAL_ZONE_NAMES) {
    const prefix = `${AGENTCORE_ROOT}/${zone}`;
    if (p === prefix || p.startsWith(`${prefix}/`)) return true;
  }
  return false;
}

/**
 * 是否跳过目录名。`parentRel` 为父目录的工作区相对路径（根用 `""`），
 * 用于路径感知内部区；裸名 `index` 等不单独跳过。
 */
export function shouldSkipDirName(name: string, parentRel = ""): boolean {
  if (LIST_FILES_SKIP_DIRS.has(name)) return true;
  const parent = parentRel.replace(/\\/g, "/").replace(/^\/+|\/+$/g, "");
  const child = parent && parent !== "." ? `${parent}/${name}` : name;
  return isInternalZoneRelPath(child);
}

/** 系统噪音文件（UI + AI 都隐藏）。 */
export function shouldSkipSystemFileName(name: string): boolean {
  return endsWithAny(name, SYSTEM_IGNORED_FILE_SUFFIXES);
}

/** AI 噪音文件（仅 AI 隐藏；用户 UI 可见）。 */
export function shouldSkipAiNoiseFileName(name: string): boolean {
  return endsWithAny(name, AI_NOISE_FILE_SUFFIXES);
}

/** AI 视角：系统噪音 ∪ AI 噪音。 */
export function shouldSkipFileName(name: string): boolean {
  return shouldSkipSystemFileName(name) || shouldSkipAiNoiseFileName(name);
}

/** AI 列举 / 索引 / grep：目录系统噪音 + 文件全档。 */
export function shouldSkipWorkspaceEntry(
  name: string,
  isDirectory: boolean,
  parentRel = "",
): boolean {
  return isDirectory
    ? shouldSkipDirName(name, parentRel)
    : shouldSkipFileName(name);
}

/** 用户文件 UI（`listDir`）：仅系统噪音。 */
export function shouldSkipSystemWorkspaceEntry(
  name: string,
  isDirectory: boolean,
  parentRel = "",
): boolean {
  return isDirectory
    ? shouldSkipDirName(name, parentRel)
    : shouldSkipSystemFileName(name);
}
