import { TabBar } from "@/components/TabBar";
// Shell for a top-level page: the page fills the body, the bottom TabBar persists below
// (手机端布局重构 · 底部 4-tab 导航). The shell owns the viewport height (100dvh) and the top
// safe-area inset (status bar); the inner page's own .screen drops to height:100% (see
// styles.css .tabs-body > .screen) and the TabBar owns the bottom safe-area (home indicator).
// Wrap ONLY top-level routes — detail pages (聊天 / 设置子页 / IM 线程 / 文件预览) render their
// bare .screen full-screen so the bar never crowds a page's own bottom composer.
import type { ReactNode } from "react";

export function TabLayout({ children }: { children: ReactNode }) {
  return (
    <div className="tabs-shell">
      <div className="tabs-body">{children}</div>
      <TabBar />
    </div>
  );
}
