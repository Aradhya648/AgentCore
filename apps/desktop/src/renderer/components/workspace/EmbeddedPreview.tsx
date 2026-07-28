import { IconButton } from "@/components/ui";
import { SimpleTooltip } from "@/components/ui/tooltip";
import {
  embeddedPreviewVisible,
  previewAddressLabel,
} from "@/lib/embeddedPreview";
import { notifyActionError } from "@/lib/toast";
import { openWorkspaceInBrowser } from "@/services/workspace";
import { useOverlayStore } from "@/stores/overlay";
import type { PreviewBounds, PreviewNavState } from "@shared/preview-contract";
import {
  ArrowLeft,
  ExternalLink,
  Globe,
  Loader2,
  RotateCw,
  X,
} from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

/**
 * @deprecated M3b：产品入口已拆除。完整预览走右坞 BrowserPanel（`openWorkspaceHtmlInBrowser`）。
 * 本组件与 `previewApi.embed*` 仅作协议/内嵌实现参考保留；UI 不得再挂载。
 *
 * SidePanel「预览」tab 的正文 —— 应用内内置浏览器的**渲染层外壳 + 原生视图定位器**。
 *
 * 页面本身由主进程一个隔离 WebContentsView（preview:// 代理会话工作区字节）渲染，恒盖在 DOM
 * 之上；本组件只负责：(1) 最小外壳（只读地址 + 后退 + 刷新 + 系统浏览器打开 + 关闭，均为可信侧
 * DOM，不被原生视图遮挡——它们在占位容器之上）；(2) 测量占位容器 bounds 并驱动主进程 show/
 * setBounds/hide，做**遮挡管理**：
 *   - 激活且无弹层遮挡 → show（首帧）/ setBounds（布局变化，经 ResizeObserver + window resize）；
 *   - 非激活（组件仍挂载，父容器 hidden）/ 弹层遮挡 → hide；
 *   - 卸载（切 tab / 折叠面板 / 离开路由）→ hide **保活**（返回即恢复页面状态）；
 *   - 销毁 → `previewApi.embedClose`（不再经 sidePanel.closePreview；该 API 已随 M3b 删除）。
 *
 * bounds 用占位容器 `getBoundingClientRect()`（视口坐标）；frame:false 下内容区原点 = 视口原点，
 * 直接对齐主进程 `setBounds` 的内容区坐标。面板右贴靠、顶栏定高，故位移只源于窗口尺寸变化
 * （window resize）与面板宽度拖拽（占位容器尺寸变 → ResizeObserver），二者均已覆盖。
 */
export function EmbeddedPreview({
  conversationId,
  path,
  name,
  active,
}: {
  conversationId: string;
  path: string;
  name: string;
  active: boolean;
}) {
  const hostRef = useRef<HTMLDivElement>(null);
  const obstructed = useOverlayStore((s) => s.count > 0);
  const [nav, setNav] = useState<PreviewNavState>({
    url: "",
    canGoBack: false,
  });
  const [openingBrowser, setOpeningBrowser] = useState(false);

  const api = typeof window !== "undefined" ? window.previewApi : undefined;
  const visible = embeddedPreviewVisible(active, obstructed);
  const closeEmbed = useCallback(() => {
    api?.embedClose();
  }, [api]);

  // 测占位容器，得整数视口相对 bounds；不可测（未挂载 / display:none）→ null。
  const measure = useCallback((): PreviewBounds | null => {
    const el = hostRef.current;
    if (!el) return null;
    const r = el.getBoundingClientRect();
    if (r.width <= 0 || r.height <= 0) return null;
    return { x: r.left, y: r.top, width: r.width, height: r.height };
  }, []);

  // 显隐 + bounds 同步：可见 → 首次 show、其后随布局 setBounds；不可见 → hide（保活）。
  // ResizeObserver 兜住面板宽度拖拽（占位容器尺寸变）；window resize 兜住窗口尺寸变（面板右贴靠，
  // 仅窗口宽变会平移占位而不改其尺寸）。目标（会话/路径）变 → 依赖变 → 重跑 → 重新 show（主进程
  // 据目标是否变决定是否导航）。
  useEffect(() => {
    if (!api) return;
    if (!visible) {
      api.embedHide();
      return;
    }
    let raf = 0;
    let shown = false;
    const sync = () => {
      cancelAnimationFrame(raf);
      raf = requestAnimationFrame(() => {
        const b = measure();
        if (!b) return;
        if (shown) {
          api.embedSetBounds(b);
        } else {
          shown = true;
          void api.embedShow({ conversationId, path, bounds: b });
        }
      });
    };
    sync();
    const ro = new ResizeObserver(sync);
    const el = hostRef.current;
    if (el) ro.observe(el);
    window.addEventListener("resize", sync);
    return () => {
      cancelAnimationFrame(raf);
      ro.disconnect();
      window.removeEventListener("resize", sync);
    };
  }, [api, visible, conversationId, path, measure]);

  // 卸载 → 隐藏但保活；显式销毁走 embedClose（产品 UI 已不再挂本组件）。
  useEffect(() => {
    return () => {
      window.previewApi?.embedHide();
    };
  }, []);

  // 订阅主进程导航态推送，更新只读地址栏 + 后退可用性。
  useEffect(() => {
    if (!api) return;
    return api.onNavState(setNav);
  }, [api]);

  const address = previewAddressLabel(nav.url || null, path);

  const onOpenExternal = async () => {
    if (openingBrowser) return;
    setOpeningBrowser(true);
    try {
      await openWorkspaceInBrowser(conversationId, path);
    } catch (e) {
      notifyActionError("无法在系统浏览器打开", e);
    } finally {
      setOpeningBrowser(false);
    }
  };

  return (
    <div className="flex h-full flex-col">
      <div className="flex h-9 shrink-0 items-center gap-1 border-b border-border pl-1 pr-1">
        <SimpleTooltip label="后退">
          <IconButton
            onClick={() => api?.embedBack()}
            disabled={!nav.canGoBack}
            aria-label="后退"
          >
            <ArrowLeft size={15} />
          </IconButton>
        </SimpleTooltip>
        <SimpleTooltip label="刷新">
          <IconButton onClick={() => api?.embedReload()} aria-label="刷新">
            <RotateCw size={14} />
          </IconButton>
        </SimpleTooltip>
        <SimpleTooltip label={`${name} · ${address}`}>
          <span className="mx-1 min-w-0 flex-1 truncate rounded-lg bg-muted/60 px-2 py-1 text-xs text-muted-foreground">
            {address}
          </span>
        </SimpleTooltip>
        <SimpleTooltip label="在系统浏览器打开（完整效果）">
          <IconButton
            onClick={() => void onOpenExternal()}
            disabled={openingBrowser}
            aria-label="在系统浏览器打开"
          >
            {openingBrowser ? (
              <Loader2 size={14} className="animate-spin" />
            ) : (
              <ExternalLink size={14} />
            )}
          </IconButton>
        </SimpleTooltip>
        <SimpleTooltip label="关闭预览">
          <IconButton onClick={closeEmbed} aria-label="关闭预览">
            <X size={15} />
          </IconButton>
        </SimpleTooltip>
      </div>

      {/* 占位容器：原生 WebContentsView 恒盖在此矩形上；下方水印仅在原生视图未覆盖（加载中 /
          被弹层让位隐藏）时透出，pointer-events-none 不拦交互。 */}
      <div ref={hostRef} className="relative min-h-0 flex-1 bg-muted/20">
        <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center gap-2 text-muted-foreground/50">
          <Globe size={22} />
          <span className="text-xs">预览加载中…</span>
        </div>
      </div>
    </div>
  );
}
