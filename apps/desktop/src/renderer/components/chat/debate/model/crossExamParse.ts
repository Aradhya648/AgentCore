/** 质询作答 blob → 逐条 Q↔A 解析（markdown 标题体，与后端 `cross_exam_parse.py` 对齐）。
 *
 * 新契约：后端解析产物进 ``cross_exam[].exchanges``，投影层优先读载荷。本模块仅作
 * **旧 journal / live 流式尚无答案**时的兼容回退。主路径按 ``### 质询一`` / ``质询1`` /
 * ``Q1`` / ``1.`` 切段；切不出段 → 整段挂第一题。 */

export interface CrossExamQaView {
  question: string;
  answer: string;
}

/** 数字分段要求分隔符后非数字，避免「3.5 倍…」被误当第 3 段。可选 `### ` 前缀。 */
const SECTION_RE =
  /(?:^|\n)\s*(?:#{1,6}\s*)?(?:质询[一二三四五六七八九十\d]+|[Qq]\s*\d+|\d+[.、)](?!\d))\s*[:：.]?\s*/gm;

/** 从辩手质询作答构造与 `questions` 等长的逐条交换。 */
export function parseCrossExamResponse(
  questions: readonly string[],
  content: string,
): CrossExamQaView[] {
  const qs = questions.map((q) => q.trim()).filter(Boolean);
  if (qs.length === 0) return [];

  const text = (content ?? "").trim();
  if (!text) {
    return qs.map((question) => ({ question, answer: "" }));
  }

  const sections = splitSections(text);
  if (sections.length > 0) {
    const aligned =
      sections.length > qs.length
        ? sections.slice(0, qs.length)
        : sections.length < qs.length
          ? [...sections, ...Array(qs.length - sections.length).fill("")]
          : sections;
    return qs.map((question, i) => ({
      question,
      answer: aligned[i] ?? "",
    }));
  }

  // 切不出段：全文挂第一条，其余空。
  if (qs.length === 1) {
    return [{ question: qs[0], answer: text }];
  }
  return [
    { question: qs[0], answer: text },
    ...qs.slice(1).map((question) => ({ question, answer: "" })),
  ];
}

function splitSections(text: string): string[] {
  const re = new RegExp(SECTION_RE.source, SECTION_RE.flags);
  const matches = [...text.matchAll(re)];
  if (matches.length === 0) return [];
  const sections: string[] = [];
  for (let i = 0; i < matches.length; i++) {
    const m = matches[i];
    const start = (m.index ?? 0) + m[0].length;
    const end =
      i + 1 < matches.length
        ? (matches[i + 1].index ?? text.length)
        : text.length;
    sections.push(text.slice(start, end).trim());
  }
  return sections;
}
