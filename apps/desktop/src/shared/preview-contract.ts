/**
 * 应用内「工作区预览浏览器」IPC 契约。
 *
 * 工作区 HTML 在面板内只显示源码（不渲染效果）；完整效果两个出口——「在浏览器打开」
 * （解压临时目录 + shell.openPath，见 fs/checkout.ts）与本契约的应用内「完整预览」：经主进程
 * `preview://` 自定义协议以 Bearer 代理后端「会话工作区文件」端点取字节，在**独立分区 + sandbox**
 * 的隔离 WebContents 里完整跑 JS + 多文件相对路径引用。仅桌面云端会话工作区源；web 不暴露。
 *
 * 两种宿主**完全复用**同一协议 + 分区 + 安全不变量（见 main/preview/）：
 * - `open`（第一步 · 保留但非主入口）：独立子 BrowserWindow（main/preview/window.ts）；
 * - `embed*`（第二步 · 主入口）：主窗口 contentView 内嵌 WebContentsView（main/preview/embed.ts），
 *   由 SidePanel「预览」tab 承载，renderer 上报占位容器 bounds、主进程 setBounds 定位。
 */

export const PREVIEW_CHANNELS = {
  /** 打开（或复用聚焦）某会话工作区某 HTML 文件的完整预览独立子窗口（保留，非主入口）。 */
  open: "preview:open",
  /** 创建/复用并显示主窗口内嵌预览视图（renderer→main，invoke，返回结果供 toast）。 */
  embedShow: "preview:embed:show",
  /** 同步内嵌视图的占位 bounds（renderer→main，send，高频，随布局变化下发）。 */
  embedSetBounds: "preview:embed:set-bounds",
  /** 隐藏内嵌视图但保活（tab 非激活 / 面板折叠 / 弹层遮挡 / 离开路由；renderer→main，send）。 */
  embedHide: "preview:embed:hide",
  /** 刷新内嵌视图（renderer→main，send）。 */
  embedReload: "preview:embed:reload",
  /** 内嵌视图后退一步（renderer→main，send）。 */
  embedBack: "preview:embed:back",
  /** 销毁内嵌视图并从 contentView 摘除（关闭预览 tab / 切换会话；renderer→main，send）。 */
  embedClose: "preview:embed:close",
  /** 内嵌视图导航态推送（main→renderer：当前 URL + 能否后退，驱动只读地址栏 + 后退按钮）。 */
  embedNavState: "preview:embed:nav-state",
} as const;

/** 打开预览的入参：会话 id + 会话工作区内相对 POSIX 路径（要预览的入口文件）。 */
export interface PreviewOpenInput {
  conversationId: string;
  path: string;
}

/** 打开结果：判别式——失败携一句 `reason` 供调用方 toast（不抛，走 IPC invoke）。 */
export type PreviewOpenResult = { ok: true } | { ok: false; reason: string };

/**
 * 内嵌预览视图的占位矩形（设备无关像素，相对主窗口内容区左上角）。renderer 用
 * `getBoundingClientRect()` 测占位容器得到（frame:false 下内容区原点 = 视口原点，
 * zoom=1 时 CSS px == DIP，二者直接对齐）；主进程 `WebContentsView.setBounds` 消费。
 */
export interface PreviewBounds {
  x: number;
  y: number;
  width: number;
  height: number;
}

/** 显示内嵌预览的入参：会话 id + 入口文件相对路径 + 首帧占位 bounds。 */
export interface PreviewEmbedShowInput {
  conversationId: string;
  path: string;
  bounds: PreviewBounds;
}

/** 内嵌预览操作结果（show）：失败携一句 `reason` 供 toast。 */
export type PreviewEmbedResult = { ok: true } | { ok: false; reason: string };

/** 内嵌视图导航态：当前地址 + 能否后退（main 在 did-navigate 时推送给 renderer）。 */
export interface PreviewNavState {
  url: string;
  canGoBack: boolean;
}

export interface PreviewApi {
  /** 打开会话工作区某文件的完整预览独立子窗口（保留，非主入口）。 */
  open: (input: PreviewOpenInput) => Promise<PreviewOpenResult>;
  /** 创建/复用并显示主窗口内嵌预览（同目标复用并保留页面状态；目标变则导航）。 */
  embedShow: (input: PreviewEmbedShowInput) => Promise<PreviewEmbedResult>;
  /** 同步内嵌视图 bounds（fire-and-forget）。 */
  embedSetBounds: (bounds: PreviewBounds) => void;
  /** 隐藏内嵌视图但保活（fire-and-forget）。 */
  embedHide: () => void;
  /** 刷新内嵌视图（fire-and-forget）。 */
  embedReload: () => void;
  /** 内嵌视图后退一步（fire-and-forget）。 */
  embedBack: () => void;
  /** 销毁内嵌视图（fire-and-forget）。 */
  embedClose: () => void;
  /** 订阅内嵌视图导航态推送；返回退订函数。 */
  onNavState: (cb: (state: PreviewNavState) => void) => () => void;
}
