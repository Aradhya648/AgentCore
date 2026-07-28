/**
 * 右坞「本机浏览器」IPC 契约（LocalChromiumHost）。
 *
 * 与旧 {@link PreviewApi}（preview:// 预览 tab）**刻意分立**：外网页 / 工作区 HTML 各用
 * 独立非持久 partition + 新导航策略，禁止改 `lockPreviewNavigation` 放行 http。
 * 本契约驱动主窗口内嵌 WebContentsView（多页签）。
 *
 * Bridge（sidecar → main）见 main/browser/bridge.ts，不经本 IPC。
 */

export const BROWSER_CHANNELS = {
  /** 创建/复用并显示某 pageId 的本机视图（renderer→main，invoke）。 */
  show: "browser:show",
  /** 同步当前激活视图的占位 bounds（renderer→main，send，高频）。 */
  setBounds: "browser:set-bounds",
  /** 隐藏全部本机视图但保活（tab 非激活 / 面板折叠 / 弹层遮挡；renderer→main，send）。 */
  hide: "browser:hide",
  /** 导航某页到 http(s) 或 workspace:// URL（renderer→main，invoke）。 */
  navigate: "browser:navigate",
  /**
   * 在指定 pageId 加载会话工作区 HTML（conversationId + path → workspace://；
   * L1b 第二 partition；renderer→main，invoke）。
   */
  openWorkspaceHtml: "browser:open-workspace-html",
  /** 刷新某页（renderer→main，send）。 */
  reload: "browser:reload",
  /** 某页后退一步（renderer→main，send）。 */
  back: "browser:back",
  /** 销毁某页视图（关页签；renderer→main，send）。 */
  close: "browser:close",
  /** 导航态推送（main→renderer：pageId + url + canGoBack）。 */
  navState: "browser:nav-state",
} as const;

/** 内嵌视图占位矩形（DIP，相对主窗口内容区左上角）。 */
export interface BrowserBounds {
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface BrowserShowInput {
  pageId: string;
  bounds: BrowserBounds;
}

export interface BrowserNavigateInput {
  pageId: string;
  url: string;
}

export interface BrowserOpenWorkspaceHtmlInput {
  pageId: string;
  conversationId: string;
  path: string;
}

export type BrowserResult = { ok: true } | { ok: false; reason: string };

export interface BrowserNavState {
  pageId: string;
  url: string;
  canGoBack: boolean;
}

export interface BrowserApi {
  show: (input: BrowserShowInput) => Promise<BrowserResult>;
  setBounds: (bounds: BrowserBounds) => void;
  hide: () => void;
  navigate: (input: BrowserNavigateInput) => Promise<BrowserResult>;
  openWorkspaceHtml: (
    input: BrowserOpenWorkspaceHtmlInput,
  ) => Promise<BrowserResult>;
  reload: (pageId: string) => void;
  back: (pageId: string) => void;
  close: (pageId: string) => void;
  onNavState: (cb: (state: BrowserNavState) => void) => () => void;
}
