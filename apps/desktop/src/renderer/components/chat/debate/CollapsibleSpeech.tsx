import { usePersistentDisclosure } from "@/stores/disclosure";
import { type ReactNode, useLayoutEffect, useRef, useState } from "react";

/**
 * 长发言折叠壳（辩论室发言气泡 / 擂台发言格共用）—— 取代旧的 `max-h-* overflow-y-auto` 内嵌滚动
 * 条：短/中发言原样全展（绝大多数，零跳变），只有**真的超长**才夹到 `max-h-72` + 底部渐隐 + 一枚
 * 「展开全文 / 收起」。这既去掉画布放大态里的**嵌套滚动条 / 滚动陷阱**，也消除旧版「流式不夹、收场
 * 才夹」的高度跳变（收场后只有超长才收，且是显式渐隐而非突兀滚动框）。
 *
 * `fadeToClass` 是折叠渐隐要融进的底色（发言气泡 `from-card`），随宿主气泡底色传入，让渐隐无缝。
 * 纯渲染、无副作用（仅按内容测一次是否溢出）。
 */
export function CollapsibleSpeech({
  contentKey,
  fadeToClass = "from-card",
  collapsedMaxHClass = "max-h-72",
  sceneKey,
  children,
}: {
  /** 内容指纹（发言全文串）：变化时重测是否溢出，避免流式收场后残留旧判定。 */
  contentKey: string;
  /** 折叠渐隐融入的宿主底色 Tailwind `from-*` 类（默认发言气泡 `from-card`）。 */
  fadeToClass?: string;
  /** 折叠态的最大高度 Tailwind `max-h-*` 类（默认 `max-h-72`）；主对话长回答用更高的阈值，
   * 只夹真正超长的答案，短/中答案原样全展。 */
  collapsedMaxHClass?: string;
  /** 持久化作用域键（回合+轮+方标识）：给了才把「展开全文」跨卸载/刷新记住；缺省走会话内存态。 */
  sceneKey?: string;
  children: ReactNode;
}) {
  const [expanded, setExpanded] = usePersistentDisclosure(
    sceneKey ?? null,
    false,
  );
  const [overflow, setOverflow] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  // biome-ignore lint/correctness/useExhaustiveDependencies: contentKey is an intentional re-run key — re-measure overflow when the speech content changes.
  useLayoutEffect(() => {
    const el = ref.current;
    if (el) setOverflow(el.scrollHeight - el.clientHeight > 4);
  }, [contentKey]);

  return (
    <div>
      <div
        ref={ref}
        className={
          expanded
            ? "text-sm"
            : `relative ${collapsedMaxHClass} overflow-hidden text-sm`
        }
      >
        {children}
        {!expanded && overflow && (
          <div
            className={`pointer-events-none absolute inset-x-0 bottom-0 h-8 bg-gradient-to-t to-transparent ${fadeToClass}`}
            aria-hidden
          />
        )}
      </div>
      {overflow && (
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          aria-expanded={expanded}
          className="mt-1 text-xs font-medium text-primary hover:underline"
        >
          {expanded ? "收起" : "展开全文"}
        </button>
      )}
    </div>
  );
}
