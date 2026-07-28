/**
 * LocalChromiumHost —— 主窗口内嵌多页 WebContentsView。
 *
 * 安全不变量（L1b）：
 * - 外网页：**非持久** {@link BROWSER_PARTITION}；工作区 HTML：**非持久**
 *   {@link WORKSPACE_PARTITION}——二者 ≠ PREVIEW_PARTITION / defaultSession，互不共用；
 * - sandbox:true、**无 preload**、nodeIntegration 关、contextIsolation 开、webviewTag 关；
 * - 导航策略见 navigation.ts（按 web | workspace 模式；不改 lockPreviewNavigation）。
 *
 * 多页：一 client pageId 一 view；仅激活页 show+bounds，其余 hide；关页销毁 view。
 * 同 pageId 在 http(s) ↔ workspace 间切换时销毁重建以换 partition。
 * Bridge（sidecar）经 {@link bridgeDispatchLocalBrowser} 驱动同一套页（pageId = session_id）。
 */

import {
  BROWSER_CHANNELS,
  type BrowserBounds,
  type BrowserNavState,
  type BrowserResult,
} from "@shared/browser-contract";
import { BrowserWindow, WebContentsView, session, type WebContents } from "electron";
import type {
  BridgeAction,
  BridgeHostResult,
} from "./bridge-handler";
import {
  LOCAL_BROWSER_BLANK,
  type LocalBrowserNavMode,
  attachLocalBrowserDownloadGuard,
  isNavigableLocalBrowserUrl,
  lockLocalBrowserNavigation,
} from "./navigation";
import { BROWSER_PARTITION, normalizeBrowserBounds } from "./paths";
import {
  WORKSPACE_PARTITION,
  buildWorkspaceUrl,
  isWorkspaceBrowserUrl,
  normalizePreviewPath,
} from "./workspace-paths";
import { registerWorkspaceProtocol } from "./workspace-protocol";

interface PageView {
  pageId: string;
  view: WebContentsView;
  snapshotVersion: number;
  kind: LocalBrowserNavMode;
}

/** pageId → 视图。 */
const pages = new Map<string, PageView>();

let hostWin: BrowserWindow | null = null;
let activePageId: string | null = null;

/** 与 sandbox driver 对齐的交互元素快照（data-acref）。 */
const SNAPSHOT_JS = `(version) => {
  const sel = [
    'a', 'button', 'input', 'textarea', 'select',
    '[role=button]', '[role=link]', '[role=textbox]', '[role=checkbox]',
    '[role=tab]', '[role=menuitem]', '[onclick]'
  ].join(',');
  const out = [];
  let n = 0;
  for (const el of document.querySelectorAll(sel)) {
    const r = el.getBoundingClientRect();
    if (r.width === 0 && r.height === 0) continue;
    const style = window.getComputedStyle(el);
    if (style.visibility === 'hidden' || style.display === 'none') continue;
    n++;
    const ref = 'e' + n;
    el.setAttribute('data-acref', ref);
    const type = (el.getAttribute('type') || '').toLowerCase();
    const ac = (el.getAttribute('autocomplete') || '').toLowerCase();
    const isPassword = type === 'password' || ac.includes('password');
    const role = isPassword ? 'password' : (el.getAttribute('role') || el.tagName.toLowerCase());
    const nameSrc = isPassword
      ? (el.getAttribute('aria-label') || el.getAttribute('placeholder') || '')
      : (el.getAttribute('aria-label') || el.textContent
        || el.getAttribute('placeholder') || el.value || '');
    let name = nameSrc.trim().replace(/\\s+/g, ' ').slice(0, 100);
    out.push('[' + ref + '] ' + role + (name ? ': ' + name : ''));
    if (n >= 200) break;
  }
  return out.join('\\n');
}`;

const IS_PASSWORD_JS = `(el) => {
  const type = (el.getAttribute('type') || '').toLowerCase();
  const ac = (el.getAttribute('autocomplete') || '').toLowerCase();
  return type === 'password' || ac.includes('password');
}`;

const hostsWithCleanup = new WeakSet<BrowserWindow>();

function pushNavState(pageId: string): void {
  const entry = pages.get(pageId);
  if (!entry || !hostWin || hostWin.isDestroyed()) return;
  if (entry.view.webContents.isDestroyed()) return;
  const payload: BrowserNavState = {
    pageId,
    url: entry.view.webContents.getURL(),
    canGoBack: entry.view.webContents.navigationHistory.canGoBack(),
  };
  hostWin.webContents.send(BROWSER_CHANNELS.navState, payload);
}

function ensureHostCleanup(win: BrowserWindow): void {
  if (hostsWithCleanup.has(win)) return;
  hostsWithCleanup.add(win);
  win.once("closed", () => {
    if (hostWin === win) closeAllLocalBrowserPages();
  });
}

function partitionFor(kind: LocalBrowserNavMode): string {
  return kind === "workspace" ? WORKSPACE_PARTITION : BROWSER_PARTITION;
}

function createPageView(
  win: BrowserWindow,
  pageId: string,
  kind: LocalBrowserNavMode,
): WebContentsView {
  if (kind === "workspace") registerWorkspaceProtocol();
  const partition = partitionFor(kind);
  const sess = session.fromPartition(partition);
  attachLocalBrowserDownloadGuard(sess);

  const view = new WebContentsView({
    webPreferences: {
      partition,
      sandbox: true,
      contextIsolation: true,
      nodeIntegration: false,
      webviewTag: false,
      // 刻意不挂 preload —— 浏览页不得拿应用 IPC。
    },
  });
  lockLocalBrowserNavigation(view.webContents, kind);
  view.webContents.on("did-navigate", () => pushNavState(pageId));
  view.webContents.on("did-navigate-in-page", () => pushNavState(pageId));
  view.webContents.on("page-title-updated", () => pushNavState(pageId));
  view.setVisible(false);
  win.contentView.addChildView(view);
  void view.webContents.loadURL(LOCAL_BROWSER_BLANK);
  return view;
}

/**
 * 确保 pageId 视图存在且为指定 kind；kind 变更则销毁重建（换 partition）。
 */
function ensurePageKind(
  win: BrowserWindow,
  pageId: string,
  kind: LocalBrowserNavMode,
): PageView {
  const existing = pages.get(pageId);
  if (
    existing &&
    !existing.view.webContents.isDestroyed() &&
    existing.kind === kind
  ) {
    return existing;
  }
  const wasActive = activePageId === pageId;
  const prevBounds =
    existing && !existing.view.webContents.isDestroyed()
      ? existing.view.getBounds()
      : null;
  if (existing) destroyPageView(pageId);

  hostWin = win;
  ensureHostCleanup(win);
  const view = createPageView(win, pageId, kind);
  if (prevBounds) view.setBounds(prevBounds);
  if (wasActive) {
    activePageId = pageId;
    view.setVisible(true);
  }
  const entry: PageView = { pageId, view, snapshotVersion: 0, kind };
  pages.set(pageId, entry);
  return entry;
}

function hideAllViews(): void {
  for (const { view } of pages.values()) {
    if (!view.webContents.isDestroyed()) view.setVisible(false);
  }
}

function destroyPageView(pageId: string): void {
  const entry = pages.get(pageId);
  if (!entry) return;
  pages.delete(pageId);
  if (activePageId === pageId) activePageId = null;
  const { view } = entry;
  try {
    if (hostWin && !hostWin.isDestroyed()) {
      hostWin.contentView.removeChildView(view);
    }
  } catch {
    /* 已摘除 */
  }
  try {
    if (!view.webContents.isDestroyed()) view.webContents.close();
  } catch {
    /* 已销毁 */
  }
}

/** 销毁全部本机页（宿主窗口关闭）。 */
export function closeAllLocalBrowserPages(): void {
  const ids = [...pages.keys()];
  for (const id of ids) destroyPageView(id);
  hostWin = null;
  activePageId = null;
}

/**
 * 显示（并必要时创建）某 pageId 视图，设为激活并定位 bounds；其余页 hide。
 */
export function showLocalBrowserPage(
  win: BrowserWindow,
  pageId: string,
  boundsIn: BrowserBounds,
): BrowserResult {
  try {
    const bounds = normalizeBrowserBounds(boundsIn);
    if (!bounds) return { ok: false, reason: "无效的预览区域" };
    if (!pageId.trim()) return { ok: false, reason: "无效的页 id" };

    if (hostWin && hostWin !== win) closeAllLocalBrowserPages();
    hostWin = win;
    ensureHostCleanup(win);

    // show 不强制换 kind：已有页保留（workspace 页再次 show 不掉回 web）。
    let entry = pages.get(pageId);
    if (!entry || entry.view.webContents.isDestroyed()) {
      entry = ensurePageKind(win, pageId, "web");
    }

    hideAllViews();
    activePageId = pageId;
    entry.view.setBounds(bounds);
    entry.view.setVisible(true);
    pushNavState(pageId);
    return { ok: true };
  } catch (e) {
    return {
      ok: false,
      reason: e instanceof Error ? e.message : "打开本机浏览器失败",
    };
  }
}

/** 同步激活页 bounds（高频）；无激活页则忽略。 */
export function setLocalBrowserBounds(boundsIn: BrowserBounds): void {
  const bounds = normalizeBrowserBounds(boundsIn);
  if (!bounds || !activePageId) return;
  const entry = pages.get(activePageId);
  if (!entry || entry.view.webContents.isDestroyed()) return;
  entry.view.setBounds(bounds);
}

/** 隐藏全部本机视图但保活。 */
export function hideLocalBrowserPages(): void {
  hideAllViews();
}

/** 导航某页到 http(s) 或 workspace://（可先于 show；无宿主窗口则拒）。 */
export function navigateLocalBrowserPage(
  pageId: string,
  url: string,
): BrowserResult {
  const trimmed = url.trim();
  if (!isNavigableLocalBrowserUrl(trimmed)) {
    return { ok: false, reason: "仅支持 http(s) 或工作区地址" };
  }
  const win = resolveBridgeWindow();
  if (!win) return { ok: false, reason: "页尚未打开" };

  const kind: LocalBrowserNavMode = isWorkspaceBrowserUrl(trimmed)
    ? "workspace"
    : "web";
  const entry = ensurePageKind(win, pageId, kind);
  void entry.view.webContents.loadURL(trimmed);
  pushNavState(pageId);
  return { ok: true };
}

/**
 * 在指定 pageId 加载会话工作区 HTML（L1b：WORKSPACE_PARTITION + workspace://）。
 * 可先于 UI show；无主窗口 → 失败。
 */
export function openLocalBrowserWorkspaceHtml(
  pageId: string,
  conversationId: string,
  path: string,
): BrowserResult {
  try {
    const id = pageId.trim();
    const conv = conversationId.trim();
    if (!id) return { ok: false, reason: "无效的页 id" };
    if (!conv) return { ok: false, reason: "无效的会话 id" };
    const rel = normalizePreviewPath(path);
    if (!rel) return { ok: false, reason: "无效的工作区路径" };

    const win = resolveBridgeWindow();
    if (!win) {
      return { ok: false, reason: "无宿主窗口" };
    }

    registerWorkspaceProtocol();
    const entry = ensurePageKind(win, id, "workspace");
    const target = buildWorkspaceUrl(conv, rel);
    void entry.view.webContents.loadURL(target);
    pushNavState(id);
    return { ok: true };
  } catch (e) {
    return {
      ok: false,
      reason: e instanceof Error ? e.message : "打开工作区预览失败",
    };
  }
}

export function reloadLocalBrowserPage(pageId: string): void {
  const entry = pages.get(pageId);
  if (!entry || entry.view.webContents.isDestroyed()) return;
  entry.view.webContents.reload();
}

export function goBackLocalBrowserPage(pageId: string): void {
  const entry = pages.get(pageId);
  if (!entry || entry.view.webContents.isDestroyed()) return;
  const nav = entry.view.webContents.navigationHistory;
  if (nav.canGoBack()) nav.goBack();
}

/** 关页：销毁对应 view。 */
export function closeLocalBrowserPage(pageId: string): void {
  destroyPageView(pageId);
}

function resolveBridgeWindow(): BrowserWindow | null {
  if (hostWin && !hostWin.isDestroyed()) return hostWin;
  const focused = BrowserWindow.getFocusedWindow();
  if (focused && !focused.isDestroyed()) return focused;
  const all = BrowserWindow.getAllWindows().filter((w) => !w.isDestroyed());
  return all[0] ?? null;
}

/**
 * Bridge：确保 pageId 对应视图存在（可先于 UI show；无主窗口 → host_unavailable）。
 */
function ensurePageForBridge(pageId: string): BridgeHostResult | PageView {
  const id = pageId.trim();
  if (!id) return { ok: false, error: "missing_pageId", code: "host_unavailable" };

  const existing = pages.get(id);
  if (existing && !existing.view.webContents.isDestroyed()) return existing;

  const win = resolveBridgeWindow();
  if (!win) {
    return {
      ok: false,
      error: "host_unavailable: 无可用 Desktop 窗口承载本机浏览器",
      code: "host_unavailable",
    };
  }
  if (hostWin && hostWin !== win) closeAllLocalBrowserPages();
  hostWin = win;
  ensureHostCleanup(win);
  const view = createPageView(win, id, "web");
  // 隐藏占位：Agent 驱动时可先不 show；用户打开右坞后再 setBounds。
  view.setBounds({ x: 0, y: 0, width: 1, height: 1 });
  view.setVisible(false);
  const entry: PageView = { pageId: id, view, snapshotVersion: 0, kind: "web" };
  pages.set(id, entry);
  return entry;
}

async function pageMeta(entry: PageView): Promise<{ final_url: string; title: string }> {
  const wc = entry.view.webContents;
  return {
    final_url: wc.getURL(),
    title: wc.getTitle(),
  };
}

/** capturePage → jpeg base64 + device pixel size（live / keyframe 共用）. */
async function captureJpegFrame(
  entry: PageView,
  quality = 70,
): Promise<{ frame_b64: string; width: number; height: number } | undefined> {
  try {
    const img = await entry.view.webContents.capturePage();
    const size = img.getSize();
    const q = Math.min(100, Math.max(1, Math.round(quality)));
    const jpeg = img.toJPEG(q);
    return {
      frame_b64: Buffer.from(jpeg).toString("base64"),
      width: size.width,
      height: size.height,
    };
  } catch {
    return undefined;
  }
}

function jpegQualityFromArgs(args: Record<string, unknown>, fallback = 70): number {
  const raw = args.quality;
  if (typeof raw === "number" && Number.isFinite(raw)) return raw;
  if (typeof raw === "string" && raw.trim()) {
    const n = Number(raw);
    if (Number.isFinite(n)) return n;
  }
  return fallback;
}

async function bumpSnapshotAndState(
  entry: PageView,
  opts: { capture: boolean; quality?: number },
): Promise<Record<string, unknown>> {
  const quality = opts.quality ?? 70;
  entry.snapshotVersion += 1;
  const meta = await pageMeta(entry);
  const state: Record<string, unknown> = { ...meta };
  if (opts.capture) {
    const frame = await captureJpegFrame(entry, quality);
    if (frame) {
      state.frame_b64 = frame.frame_b64;
      state.width = frame.width;
      state.height = frame.height;
    }
  }
  return state;
}

async function waitLoad(wc: WebContents, timeoutMs: number): Promise<void> {
  if (wc.isLoadingMainFrame()) {
    await new Promise<void>((resolve) => {
      const t = setTimeout(() => {
        wc.removeListener("did-finish-load", onLoad);
        wc.removeListener("did-fail-load", onFail);
        resolve();
      }, timeoutMs);
      const done = () => {
        clearTimeout(t);
        resolve();
      };
      const onLoad = () => done();
      const onFail = () => done();
      wc.once("did-finish-load", onLoad);
      wc.once("did-fail-load", onFail);
    });
  }
}

/**
 * Bridge 派发：与 sandbox browser driver 六动作语义对齐。
 * pageId = Registry session_id。
 */
export async function bridgeDispatchLocalBrowser(
  pageId: string,
  action: BridgeAction,
  args: Record<string, unknown>,
): Promise<BridgeHostResult> {
  const ensured = ensurePageForBridge(pageId);
  if ("ok" in ensured && ensured.ok === false) return ensured;
  const entry = ensured as PageView;
  const wc = entry.view.webContents;

  try {
    switch (action) {
      case "navigate": {
        const target = String(args.url ?? "").trim();
        if (!target || !isNavigableLocalBrowserUrl(target)) {
          return {
            ok: false,
            error: "仅支持 http(s) 或本会话工作区地址（workspace://）",
          };
        }
        // 甲：workspace:// 必须切 workspace partition（与 openLocalBrowserWorkspaceHtml
        // 同形）；禁止在 web 页上硬 load workspace://。
        const win = resolveBridgeWindow();
        if (!win) {
          return {
            ok: false,
            error: "host_unavailable: 无可用 Desktop 窗口承载本机浏览器",
            code: "host_unavailable",
          };
        }
        const kind: LocalBrowserNavMode = isWorkspaceBrowserUrl(target)
          ? "workspace"
          : "web";
        const page = ensurePageKind(win, entry.pageId, kind);
        const wcNav = page.view.webContents;
        const load = wcNav.loadURL(target);
        await Promise.race([
          load,
          new Promise<void>((r) => setTimeout(r, Number(args.timeout_ms ?? 45_000))),
        ]);
        await waitLoad(wcNav, 5_000);
        const capture = args.capture !== false;
        const data = await bumpSnapshotAndState(page, { capture });
        data.http_status = null;
        pushNavState(page.pageId);
        return { ok: true, data };
      }
      case "click": {
        const ref = String(args.ref ?? "").trim();
        if (!ref) return { ok: false, error: "缺少 ref（先调用 browser_snapshot）" };
        const version = args.snapshot_version;
        if (
          version !== undefined &&
          version !== null &&
          Number(version) !== entry.snapshotVersion
        ) {
          return {
            ok: false,
            error: `ref 版本过期（快照 v${version} ≠ 当前 v${entry.snapshotVersion}）`,
          };
        }
        await wc.executeJavaScript(
          `(function(){ const el = document.querySelector('[data-acref="${ref.replace(/"/g, "")}"]'); if (!el) throw new Error('ref_not_found'); el.click(); })()`,
        );
        const data = await bumpSnapshotAndState(entry, {
          capture: args.capture !== false,
        });
        return { ok: true, data };
      }
      case "type": {
        const ref = String(args.ref ?? "").trim();
        if (!ref) return { ok: false, error: "缺少 ref（先调用 browser_snapshot）" };
        const version = args.snapshot_version;
        if (
          version !== undefined &&
          version !== null &&
          Number(version) !== entry.snapshotVersion
        ) {
          return {
            ok: false,
            error: `ref 版本过期（快照 v${version} ≠ 当前 v${entry.snapshotVersion}）`,
          };
        }
        const safeRef = ref.replace(/\\/g, "\\\\").replace(/'/g, "\\'");
        const isPw = await wc.executeJavaScript(
          `(function(){ const el = document.querySelector('[data-acref="${safeRef}"]'); if (!el) throw new Error('ref_not_found'); return (${IS_PASSWORD_JS})(el); })()`,
        );
        if (isPw) {
          return {
            ok: false,
            error:
              "password_blocked: AI 不得填写密码框；请 escalate(blocking=true, browser_login=true) 让用户接管登录",
          };
        }
        const text = String(args.text ?? "");
        await wc.executeJavaScript(
          `(function(){
            const el = document.querySelector('[data-acref="${safeRef}"]');
            if (!el) throw new Error('ref_not_found');
            el.focus();
            if ('value' in el) { el.value = ${JSON.stringify(text)}; el.dispatchEvent(new Event('input', { bubbles: true })); }
            else { el.textContent = ${JSON.stringify(text)}; }
          })()`,
        );
        const data = await bumpSnapshotAndState(entry, {
          capture: args.capture !== false,
        });
        return { ok: true, data };
      }
      case "scroll": {
        const dy = Number(args.dy ?? 600) || 600;
        await wc.executeJavaScript(`window.scrollBy(0, ${dy})`);
        await new Promise((r) => setTimeout(r, 200));
        const data = await bumpSnapshotAndState(entry, {
          capture: args.capture !== false,
        });
        return { ok: true, data };
      }
      case "snapshot": {
        entry.snapshotVersion += 1;
        const elements = await wc.executeJavaScript(
          `(${SNAPSHOT_JS})(${entry.snapshotVersion})`,
        );
        const meta = await pageMeta(entry);
        return {
          ok: true,
          data: {
            ...meta,
            snapshot_version: entry.snapshotVersion,
            elements: typeof elements === "string" ? elements : "",
            aria: "",
          },
        };
      }
      case "screenshot": {
        const meta = await pageMeta(entry);
        const data: Record<string, unknown> = { ...meta };
        if (args.capture !== false) {
          const frame = await captureJpegFrame(entry, jpegQualityFromArgs(args));
          if (frame) {
            data.frame_b64 = frame.frame_b64;
            data.width = frame.width;
            data.height = frame.height;
          }
        }
        return { ok: true, data };
      }
      default:
        return { ok: false, error: `unsupported_action:${action}` };
    }
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e);
    if (msg.includes("host_unavailable")) {
      return { ok: false, error: msg, code: "host_unavailable" };
    }
    return { ok: false, error: msg };
  }
}

/** @deprecated 用 {@link bridgeDispatchLocalBrowser}；保留给旧调用方。 */
export function bridgeNavigateLocalBrowser(
  pageId: string,
  url: string,
): BrowserResult {
  return navigateLocalBrowserPage(pageId, url);
}
