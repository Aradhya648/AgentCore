/**
 * Frontmatter 字段解析（纯函数，供内联预览的 {@link FrontmatterCard} 用）。
 *
 * 只做「展示用」的轻量解析：把 YAML front matter 文本拆成 key→value 行，数组
 * （`- a` / `- b`）折叠成逗号串、缩进续行拼回上一行。不追求完整 YAML 语义（那是
 * 源码模式的事），目标是给一张可读的元数据卡片。
 */

export interface FrontmatterField {
  key: string;
  value: string;
}

const KV_RE = /^([^:\s][^:]*):\s?(.*)$/;
const LIST_RE = /^\s*-\s+(.*)$/;

/** 解析 front matter YAML 正文为展示字段；非 key:value 行尽量折叠进上一字段。 */
export function parseFrontmatterFields(yaml: string): FrontmatterField[] {
  const rows: FrontmatterField[] = [];
  let last: FrontmatterField | null = null;

  for (const raw of yaml.split("\n")) {
    if (!raw.trim()) continue;
    const indented = /^\s/.test(raw);
    const list = LIST_RE.exec(raw);
    const kv = !indented ? KV_RE.exec(raw) : null;

    if (kv) {
      last = { key: (kv[1] ?? "").trim(), value: (kv[2] ?? "").trim() };
      rows.push(last);
    } else if (list && last) {
      const item = (list[1] ?? "").trim();
      last.value = last.value ? `${last.value}, ${item}` : item;
    } else if (indented && last) {
      const cont = raw.trim();
      last.value = last.value ? `${last.value} ${cont}` : cont;
    } else {
      last = { key: "", value: raw.trim() };
      rows.push(last);
    }
  }
  return rows;
}
