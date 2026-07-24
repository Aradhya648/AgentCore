export interface SpeechArgument {
  id: string;
  title: string;
  body: string;
}

/** 截断为一行摘要：优先在句读处断开（质询预览等；论点 title 路径勿用）。 */
export function summarizeText(text: string, maxLen: number): string {
  const trimmed = text.trim().replace(/\s+/g, " ");
  if (!trimmed) return "";
  if (trimmed.length <= maxLen) return trimmed;

  const slice = trimmed.slice(0, maxLen);
  const lastPunct = Math.max(
    slice.lastIndexOf("。"),
    slice.lastIndexOf("；"),
    slice.lastIndexOf("，"),
    slice.lastIndexOf("—"),
    slice.lastIndexOf("–"),
  );
  if (lastPunct > maxLen * 0.45) return slice.slice(0, lastPunct + 1);
  return `${slice}…`;
}

/** 折叠空白，不截断。 */
function normalizeTitle(text: string): string {
  return text.trim().replace(/\s+/g, " ");
}

/** 从一段发言正文中提取论点标题（首句 / 冒号标签 / 首行）；完整文案入库。 */
export function argumentTitle(body: string): string {
  const trimmed = body.trim();
  if (!trimmed) return "";

  const colonMatch = trimmed.match(/^([^：:\n]{2,24}[：:])\s*/);
  if (colonMatch) {
    const label = colonMatch[1].replace(/[：:]$/, "");
    const after = trimmed.slice(colonMatch[0].length);
    const clause = after.split(/[。；—–-]/)[0]?.trim();
    if (clause) return normalizeTitle(`${label}：${clause}`);
    return normalizeTitle(label);
  }

  const firstLine = trimmed.split("\n")[0] ?? "";
  const firstSentence =
    firstLine.split(/[。；]/)[0]?.trim() || firstLine.trim();
  return normalizeTitle(firstSentence);
}

const HEADER_SPLIT = /(?=^#{1,3}\s+)/m;
const NUMBERED_LINE = /^\d+\.\s+/;
const BULLET_LINE = /^[-*•]\s+/;

function splitBlocks(text: string): string[] {
  const trimmed = text.trim();
  if (!trimmed) return [];

  if (HEADER_SPLIT.test(trimmed)) {
    return trimmed
      .split(HEADER_SPLIT)
      .map((b) => b.trim())
      .filter(Boolean);
  }

  const lines = trimmed.split("\n");
  const isNumbered = lines.every(
    (l) => !l.trim() || NUMBERED_LINE.test(l.trim()),
  );
  if (isNumbered && lines.filter((l) => l.trim()).length > 1) {
    return lines.map((l) => l.trim()).filter(Boolean);
  }

  const isBullet = lines.every((l) => !l.trim() || BULLET_LINE.test(l.trim()));
  if (isBullet && lines.filter((l) => l.trim()).length > 1) {
    return lines.map((l) => l.trim()).filter(Boolean);
  }

  const paragraphs = trimmed
    .split(/\n{2,}/)
    .map((p) => p.trim())
    .filter(Boolean);
  if (paragraphs.length > 1) return paragraphs;

  return [trimmed];
}

function titleFromHeaderBlock(block: string): { title: string; body: string } {
  const lines = block.split("\n");
  const head = lines[0]?.replace(/^#{1,3}\s+/, "").trim() ?? "";
  const body = lines.slice(1).join("\n").trim() || head;
  return {
    title: normalizeTitle(head),
    body: body || block,
  };
}

function stripListMarker(line: string): string {
  return line.replace(/^(?:\d+\.\s+|[-*•]\s+)/, "").trim();
}

function blockToArgument(block: string, i: number): SpeechArgument {
  if (/^#{1,3}\s+/.test(block)) {
    const { title, body } = titleFromHeaderBlock(block);
    return { id: `arg-${i}`, title, body };
  }

  const stripped = stripListMarker(block);
  return {
    id: `arg-${i}`,
    title: argumentTitle(stripped),
    body: stripped,
  };
}

/**
 * 把辩手发言拆成论点列表（展示层启发式）。
 * 新契约：后端 ``sides[].arguments`` 为权威；本函数仅缺结构化字段时回退。
 * 识别 markdown 标题、有序 / 无序列表、空行分段；单段则整段为一个论点。
 * ``title`` 为完整标题（不在数据层截断）；折叠态由 CSS 截断展示。
 */
export function parseSpeechArguments(text: string): SpeechArgument[] {
  const blocks = splitBlocks(text);
  if (blocks.length === 0) return [];
  return blocks.map((block, i) => blockToArgument(block, i));
}

/**
 * 展示层标题重水合：结构化 ``arguments`` 权威保留 id/body，用成稿 ``output``
 * 解析出的完整 title 按稳定 id（优先）或 index 盖回。
 * 旧 journal / 磁带里 title 曾被截断；成稿仍含完整 ``###`` 标题时可修复大纲显示。
 */
export function rehydrateArgumentTitles(
  structured: SpeechArgument[],
  output: string,
): SpeechArgument[] {
  if (structured.length === 0) return structured;
  const trimmed = output.trim();
  if (!trimmed) return structured;

  const parsed = parseSpeechArguments(trimmed);
  if (parsed.length === 0) return structured;

  const byId = new Map(parsed.map((a) => [a.id, a]));
  return structured.map((arg, i) => {
    const match = byId.get(arg.id) ?? parsed[i];
    const fullTitle = match?.title?.trim();
    if (!fullTitle || fullTitle === arg.title) return arg;
    return { id: arg.id, title: fullTitle, body: arg.body };
  });
}
