/**
 * 主窗口内嵌预览视图 —— 应用内「完整预览」的**主入口**（第二步）：把一个隔离 WebContents
 * 挂到主窗口 `contentView` 上，由渲染层 SidePanel「预览」tab 定位。原生视图恒盖在 DOM 之上，
 * 故显隐/bounds 全部由渲染层驱动（tab 激活 → show + 上报 bounds；非激活/折叠/遮挡/离开路由 →
 * hide；布局变化 → setBounds）。
 *
 * 安全不变量（与独立子窗口 window.ts **逐条复用**，一条不得削弱）：
 * - 独立**非持久**分区（PREVIEW_PARTITION）——绝不触碰 defaultSession 的登录 cookie；
 * - sandbox:true、**无 preload**、nodeIntegration 关、contextIsolation 开、webviewTag 关；
 * - 该分区权限全拒（见 protocol.registerPreviewProtocol）；
 * - 顶级导航锁定 preview://、外链转 shell、window.open 拒（见 navigation.lockPreviewNavigation）。
 *
 * 单例：全应用至多一个内嵌预览视图（对应「一种预览 tab」）。同目标复用（保留页面滚动/JS 状态），
 * 目标变才导航。宿主窗口关闭 / 显式关闭时销毁并从 contentView 摘除，杜绝原生视图泄漏。
 */

import {
  PREVIEW_CHANNELS,
  type PreviewBounds,
  type PreviewEmbedResult,
  type PreviewNavState,
} from "@shared/preview-contract";
import { type BrowserWindow, WebContentsView } from "electron";
import { lockPreviewNavigation } from "./navigation";
import {
  PREVIEW_PARTITION,
  buildPreviewUrl,
  normalizePreviewBounds,
} from "./paths";
import { registerPreviewProtocol } from "./protocol";

interface EmbedState {
  view: WebContentsView;
  win: BrowserWindow;
  conversationId: string;
  path: string;
}

/** 当前内嵌预览（单例；null = 无）。 */
let embed: EmbedState | null = null;

/** 已挂过「窗口关闭 → 清理内嵌视图」的宿主窗口（每个窗口实例只挂一次，避免开关多轮累积监听）。 */
const hostsWithCleanup = new WeakSet<BrowserWindow>();

/** 把内嵌视图当前导航态（地址 + 能否后退）推给宿主渲染层，驱动只读地址栏/后退按钮。 */
function pushNavState(): void {
  if (!embed) return;
  const { view, win } = embed;
  if (win.isDestroyed() || view.webContents.isDestroyed()) return;
  const payload: PreviewNavState = {
    url: view.webContents.getURL(),
    canGoBack: view.webContents.navigationHistory.canGoBack(),
  };
  win.webContents.send(PREVIEW_CHANNELS.embedNavState, payload);
}

/** 新建隔离预览视图并挂到宿主窗口 contentView（安全不变量在此就位）。 */
function createView(win: BrowserWindow): WebContentsView {
  const view = new WebContentsView({
    webPreferences: {
      // 独立非持久分区：与 defaultSession（应用登录 cookie）完全隔离。
      partition: PREVIEW_PARTITION,
      sandbox: true,
      contextIsolation: true,
      nodeIntegration: false,
      webviewTag: false,
      // 刻意不挂 preload —— 预览页无需、也不该拿到任何应用 IPC 桥。
    },
  });
  lockPreviewNavigation(view.webContents);
  view.webContents.on("did-navigate", pushNavState);
  view.webContents.on("did-navigate-in-page", pushNavState);
  win.contentView.addChildView(view);
  // 宿主窗口关闭 → 清理内嵌视图（防原生视图泄漏；macOS activate 重建走新窗口，下次 show 重挂）。
  // 每个窗口实例只挂一次，避免多轮开关预览累积监听。
  if (!hostsWithCleanup.has(win)) {
    hostsWithCleanup.add(win);
    win.once("closed", () => {
      if (embed?.win === win) closeEmbeddedPreview();
    });
  }
  return view;
}

/**
 * 创建/复用并显示某会话工作区某文件的内嵌预览。首帧按 `bounds` 定位。同目标（会话+路径）复用
 * 既有视图、只 setVisible+setBounds（保留页面状态）；目标变则 loadURL 导航。加载前确保协议处理器
 * + 权限锁就位（幂等）。
 */
export function showEmbeddedPreview(
  win: BrowserWindow,
  input: { conversationId: string; path: string; bounds: PreviewBounds },
): PreviewEmbedResult {
  try {
    registerPreviewProtocol();
    const bounds = normalizePreviewBounds(input.bounds);
    if (!bounds) return { ok: false, reason: "无效的预览区域" };
    const target = buildPreviewUrl(input.conversationId, input.path);

    // 宿主窗口切换（理论上仅 macOS activate 重建）→ 丢弃旧窗口上的视图，避免跨窗残留。
    if (embed && embed.win !== win) closeEmbeddedPreview();

    if (!embed) {
      const view = createView(win);
      embed = {
        view,
        win,
        conversationId: input.conversationId,
        path: input.path,
      };
      view.setBounds(bounds);
      view.setVisible(true);
      void view.webContents.loadURL(target);
      return { ok: true };
    }

    embed.view.setBounds(bounds);
    embed.view.setVisible(true);
    // 目标变了才导航（切文件 / 切会话）；相同则保留页面状态（滚动 / JS）不重载。
    if (
      embed.conversationId !== input.conversationId ||
      embed.path !== input.path
    ) {
      embed.conversationId = input.conversationId;
      embed.path = input.path;
      void embed.view.webContents.loadURL(target);
    }
    return { ok: true };
  } catch (e) {
    return {
      ok: false,
      reason: e instanceof Error ? e.message : "打开内嵌预览失败",
    };
  }
}

/** 同步内嵌视图 bounds（布局变化时高频调用；无视图则忽略）。 */
export function setEmbeddedPreviewBounds(bounds: PreviewBounds): void {
  if (!embed) return;
  embed.view.setBounds(bounds);
}

/** 隐藏内嵌视图但**保活**（tab 非激活 / 面板折叠 / 弹层遮挡 / 离开路由）。 */
export function hideEmbeddedPreview(): void {
  if (!embed) return;
  if (!embed.view.webContents.isDestroyed()) embed.view.setVisible(false);
}

/** 刷新内嵌视图。 */
export function reloadEmbeddedPreview(): void {
  if (!embed || embed.view.webContents.isDestroyed()) return;
  embed.view.webContents.reload();
}

/** 内嵌视图后退一步（可后退时）。 */
export function goBackEmbeddedPreview(): void {
  if (!embed || embed.view.webContents.isDestroyed()) return;
  const nav = embed.view.webContents.navigationHistory;
  if (nav.canGoBack()) nav.goBack();
}

/** 销毁内嵌视图并从 contentView 摘除（关闭预览 tab / 切换会话 / 宿主窗口关闭）。 */
export function closeEmbeddedPreview(): void {
  if (!embed) return;
  const { view, win } = embed;
  embed = null;
  try {
    if (!win.isDestroyed()) win.contentView.removeChildView(view);
  } catch {
    /* 窗口已销毁 / 视图已摘除 —— 忽略 */
  }
  try {
    if (!view.webContents.isDestroyed()) view.webContents.close();
  } catch {
    /* webContents 已销毁 —— 忽略 */
  }
}
