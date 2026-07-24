/**
 * 从手册内容源 / 机制场景数据抽取用户可见文案，供术语 lint。
 */

import { SCENARIOS } from "@/components/manual/mechanism/scenarioData";
import { CONTENT_CHAPTERS } from "../content";
import { extractBlockText } from "../searchIndex";
import type { ManualBlock, ManualChapterContent } from "../types";

export interface CorpusPiece {
  /** 章 / 场景定位 */
  where: string;
  text: string;
}

function walkBlock(
  chapter: ManualChapterContent,
  sectionId: string,
  sectionTitle: string,
  block: ManualBlock,
  blockIndex: number,
  out: CorpusPiece[],
): void {
  const loc = `${chapter.id}/${sectionId}「${sectionTitle}」block[${blockIndex}:${block.type}]`;
  const text = extractBlockText(block);
  if (text.trim()) out.push({ where: loc, text });
}

export function collectManualCorpus(): CorpusPiece[] {
  const out: CorpusPiece[] = [];
  for (const chapter of CONTENT_CHAPTERS) {
    out.push({ where: `${chapter.id}·label`, text: chapter.label });
    for (const section of chapter.sections) {
      out.push({
        where: `${chapter.id}/${section.id}·title`,
        text: section.title,
      });
      section.blocks.forEach((block, i) =>
        walkBlock(chapter, section.id, section.title, block, i, out),
      );
    }
  }
  return out;
}

/** 机制场景图：title / desc / 节点上用户可见字段。 */
export function collectScenarioCorpus(): CorpusPiece[] {
  const out: CorpusPiece[] = [];
  SCENARIOS.forEach((scenario, si) => {
    const base = `scenarioData[${si}]「${scenario.title}」`;
    out.push({ where: `${base}·title`, text: scenario.title });
    out.push({ where: `${base}·desc`, text: scenario.desc });
    scenario.nodes.forEach((node, ni) => {
      const d = node.data;
      for (const key of [
        "role",
        "task",
        "label",
        "preview",
        "outputPreview",
      ] as const) {
        const v = d[key];
        if (typeof v === "string" && v.trim()) {
          out.push({ where: `${base}/node[${ni}].${key}`, text: v });
        }
      }
    });
  });
  return out;
}

export function collectAllUserVisibleCorpus(): CorpusPiece[] {
  return [...collectManualCorpus(), ...collectScenarioCorpus()];
}
