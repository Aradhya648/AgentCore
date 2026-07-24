/**
 * 内嵌预览（SidePanel「预览」tab）的**纯逻辑**：遮挡判定 + 只读地址栏文案。
 *
 * 原生 WebContentsView 恒盖在 DOM 之上，故渲染层必须精确判定「此刻是否该显示原生视图」，
 * 并把它上报给主进程。把可测的判定/格式化留在这层，组件只做副作用（测 bounds、发 IPC）。
 */

/**
 * 内嵌原生视图此刻是否应可见：预览 tab 激活（`active`，已隐含面板打开 + 在对话路由，否则组件
 * 已卸载）且无应用内弹层遮挡（`obstructed`——dialog / dropdown / 命令面板等占屏时必须让位）。
 */
export function embeddedPreviewVisible(
  active: boolean,
  obstructed: boolean,
): boolean {
  return active && !obstructed;
}

/**
 * 只读地址栏文案：优先展示内嵌视图当前 `preview://` 地址解码后的工作区相对路径（反映页面内
 * 跳转），无地址（未加载）或解析失败时回退到入口文件路径。顶级导航已锁死 preview://，故正常
 * 只会出现 preview:// 地址；万一出现其它 scheme 原样展示（不隐藏真实去向）。
 */
export function previewAddressLabel(
  url: string | null,
  fallbackPath: string,
): string {
  if (!url) return fallbackPath;
  try {
    const u = new URL(url);
    if (u.protocol !== "preview:") return url;
    const rel = decodeURIComponent(u.pathname).replace(/^\/+/, "");
    return rel || fallbackPath;
  } catch {
    return fallbackPath;
  }
}
