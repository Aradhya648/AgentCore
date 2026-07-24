/**
 * 工作区路径救援 —— 与后端 ``strip_root_label_prefix`` /
 * ``_normalize_artifact_relpath`` 对齐（``agentcore.workspace._paths``）。
 *
 * 模型常吐沙箱绝对路径（``/workspace/index.html``），写工具落盘时会 strip 成相对路径
 * （``index.html``）。桌面预览 / 产物卡若原样只去前导 ``/``，会把根标签当成子目录
 * （``workspace/index.html``）→ 上游 404。本模块是桌面侧同一语义的单一源。
 */

/** 云端会话工作区默认根标签（与 ServerWorkspace.root_label 默认一致）。 */
export const DEFAULT_WORKSPACE_ROOT_LABEL = "workspace";

/**
 * 把 ``/<rootLabel>/…`` 绝对输入改写为工作区相对路径；相对输入原样返回。
 *
 * * ``/<rootLabel>/foo/bar.md`` → ``foo/bar.md``
 * * ``/<rootLabel>`` → ``.``
 * * ``workspace/foo``（无前导 ``/``）→ 原样（可能是真子目录）
 * * ``/etc/passwd`` → 原样（不同根，交给下游拒绝）
 */
export function stripRootLabelPrefix(
  relativePath: string,
  rootLabel: string = DEFAULT_WORKSPACE_ROOT_LABEL,
): string {
  if (!rootLabel) return relativePath;
  const normalized = relativePath.replace(/\\/g, "/");
  if (!normalized.startsWith("/")) return relativePath;
  const [first, ...restParts] = normalized.replace(/^\/+/, "").split("/");
  if (first !== rootLabel) return relativePath;
  const rest = restParts.join("/");
  return rest || ".";
}

/**
 * 工具 / UI 入口路径 → 工作区相对 POSIX 路径（展示、去重、预览打开共用）。
 * 空 / 裸根 ``/workspace`` → ``""``（调用方应跳过）。
 */
export function toWorkspaceRelPath(
  path: string,
  rootLabel: string = DEFAULT_WORKSPACE_ROOT_LABEL,
): string {
  const raw = path.replace(/\\/g, "/").trim();
  if (!raw) return "";
  const stripped = stripRootLabelPrefix(raw, rootLabel);
  if (stripped === "." || stripped === "") return "";
  return stripped.replace(/^\.\/+/, "");
}
