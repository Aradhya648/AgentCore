/**
 * 右坞「本机浏览器」IPC 契约（LocalChromiumHost）。
 *
 * 与旧 {@link PreviewApi}（preview:// 预览 tab）**刻意分立**：外网页 / 工作区 HTML 各用
 * 独立非持久 partition（按 conversationId 切开）+ 新导航策略，禁止改 `lockPreviewNavigation`
 * 放行 http。本契约驱动主窗口内嵌 WebContentsView（多页签）。
 *
 * Bridge（sidecar → main）见 main/browser/bridge.ts，不经本 IPC。
 */

export const BROWSER_CHANNELS = {
  /** 创建/复用并显示某 pageId 的本机视图（renderer→main，invoke）。 */
  show: "browser:show",
  /** 同步当前激活视图的占位 bounds（renderer→main，send，高频）。 */
  setBounds: "browser:set-bounds",
  /**
   * 脱离附着：清 active、全部 setVisible(false)、bump generation（保活不销毁）；
   * 关坞 / 关浏览器 tab / 切对话 / 面板不可见；renderer→main，invoke（可 await，与 show 串行）。
   */
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
  /** 某页前进一步（renderer→main，send）。 */
  forward: "browser:forward",
  /** 销毁某页视图（关页签；renderer→main，send）。 */
  close: "browser:close",
  /** 销毁某对话全部本机页（删对话 purge；renderer→main，invoke）。 */
  closeConversation: "browser:close-conversation",
  /**
   * 在系统浏览器打开 URL（renderer→main，invoke；仅 http(s)/mailto，
   * 经 isSafeExternalUrl 闸）。
   */
  openExternal: "browser:open-external",
  /** 导航态推送（main→renderer：pageId + url + canGoBack/Forward + title）。 */
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
  conversationId: string;
  bounds: BrowserBounds;
}

export interface BrowserNavigateInput {
  pageId: string;
  conversationId: string;
  url: string;
}

export interface BrowserOpenWorkspaceHtmlInput {
  pageId: string;
  conversationId: string;
  path: string;
}

export interface BrowserCloseConversationInput {
  conversationId: string;
}

/**
 * IPC 结果。`show` 成功时附带当前 WebContents 快照，供挂回时写地址栏、
 * 判断是否还需冷 navigate（空白 + store 有 URL）。
 */
export type BrowserResult =
  | {
      ok: true;
      url?: string;
      title?: string;
      canGoBack?: boolean;
      canGoForward?: boolean;
    }
  | { ok: false; reason: string };

export interface BrowserNavState {
  pageId: string;
  url: string;
  title: string;
  canGoBack: boolean;
  canGoForward: boolean;
}

export interface BrowserOpenExternalInput {
  url: string;
}

export interface BrowserApi {
  show: (input: BrowserShowInput) => Promise<BrowserResult>;
  setBounds: (bounds: BrowserBounds) => void;
  /** 脱离附着（保活）；与 show 在 main 侧串行，可 await。 */
  hide: () => Promise<void>;
  navigate: (input: BrowserNavigateInput) => Promise<BrowserResult>;
  openWorkspaceHtml: (
    input: BrowserOpenWorkspaceHtmlInput,
  ) => Promise<BrowserResult>;
  reload: (pageId: string) => void;
  back: (pageId: string) => void;
  forward: (pageId: string) => void;
  close: (pageId: string) => void;
  /** 关某对话全部 Local 页（幂等；与 server registry.close 双关）。 */
  closeConversation: (
    input: BrowserCloseConversationInput,
  ) => Promise<BrowserResult>;
  /** 在系统默认浏览器打开（仅安全 scheme）。 */
  openExternal: (input: BrowserOpenExternalInput) => Promise<BrowserResult>;
  onNavState: (cb: (state: BrowserNavState) => void) => () => void;
}
