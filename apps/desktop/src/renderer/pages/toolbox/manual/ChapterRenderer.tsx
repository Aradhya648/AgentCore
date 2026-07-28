import { useEffect } from "react";
import { useSearchParams } from "react-router-dom";
import { BlockRenderer } from "./BlockRenderer";
import { resolveManualIcon } from "./icons";
import { SectionHeading } from "./primitives";
import { resolveCanonicalSectionId } from "./sectionIds";
import type { ManualChapterContent } from "./types";

/** 通用章节渲染器：消费结构化内容源。 */
export function ChapterRenderer({
  chapter,
  previewManual,
}: {
  chapter: ManualChapterContent;
  /** 可选：离线截图标记（四章均设，对齐 manual-scenes.json previewManual） */
  previewManual?: string;
}) {
  const [searchParams] = useSearchParams();

  useEffect(() => {
    const raw = searchParams.get("s");
    if (!raw) return;
    const target = resolveCanonicalSectionId(raw);
    // shoot 无头截图用 instant，避免 smooth 未完成就拍到错节。
    const shoot =
      typeof window !== "undefined" &&
      new URLSearchParams(window.location.search).has("shoot-manual");
    requestAnimationFrame(() =>
      document.getElementById(target)?.scrollIntoView({
        behavior: shoot ? "instant" : "smooth",
        block: "start",
      }),
    );
  }, [searchParams]);

  const sectionParam = searchParams.get("s");
  const previewSection = sectionParam
    ? resolveCanonicalSectionId(sectionParam)
    : "top";

  return (
    <div
      className="mx-auto w-full max-w-3xl px-6 py-10"
      {...(previewManual
        ? {
            "data-preview-manual": previewManual,
            "data-preview-section": previewSection,
          }
        : {})}
    >
      {chapter.sections.map((section, index) => {
        const Icon = resolveManualIcon(section.icon);
        return (
          <section key={section.id} className="mb-14">
            <SectionHeading
              icon={Icon}
              index={index + 1}
              title={section.title}
              id={section.id}
            />
            <div className="mt-4 space-y-4">
              {section.blocks.map((block, bi) => (
                // biome-ignore lint/suspicious/noArrayIndexKey: 静态 block 列表
                <BlockRenderer key={bi} block={block} />
              ))}
            </div>
          </section>
        );
      })}
    </div>
  );
}
