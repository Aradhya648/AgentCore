import type { ReactNode } from "react";

/**
 * 页面宽度档位（见 `.cursor/rules/desktop-layout.mdc`）：
 * - `content` 896px：线性阅读（设置、详情、表单）
 * - `canvas` 1200px：网格/多列（探索、列表、工具箱）
 *
 * 对话页与文件页有各自的分栏布局，不走本组件。
 */
export type PageWidth = "content" | "canvas";

const WIDTH_CLASS: Record<PageWidth, string> = {
  content: "max-w-4xl",
  canvas: "max-w-[1200px]",
};

interface PageContainerProps {
  children: ReactNode;
  /** 宽度档位，默认 `content`。 */
  width?: PageWidth;
  /** 合并到外层滚动容器（如作为 flex 子项时传 `flex-1`）。 */
  className?: string;
}

/**
 * 统一页面外壳：外层全宽滚动，内层按档位居中并套用标准 `px-6 py-8` 留白。
 * 窄屏占满、宽屏到档位上限后居中。
 */
export function PageContainer({
  children,
  width = "content",
  className,
}: PageContainerProps) {
  const outer = ["h-full w-full overflow-y-auto", className]
    .filter(Boolean)
    .join(" ");

  return (
    <div className={outer}>
      <div className={`mx-auto w-full px-6 py-8 ${WIDTH_CLASS[width]}`}>
        {children}
      </div>
    </div>
  );
}
