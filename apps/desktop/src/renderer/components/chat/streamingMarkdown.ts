/**
 * 流式 Markdown 的**逐块切分**（流式渲染性能·Stage 4）。
 *
 * 回合流式期间，`Markdown` 每收到一批 delta 就重渲染一次；若每次都把累积的全文重新解析，
 * 整轮是 O(n²)。这里把内容切成**一串顶层块**（{@link splitMarkdownBlocks}）：每个已写完的块
 * 各自记忆化、只解析一次并永久冻结，仅最后的「在写尾块」随每批 delta 重解析——整轮降到 O(总量)。
 *
 * 安全性：只在**栅栏代码块之外**、且**下一非空行不是列表/引用/缩进续行**的空行处切分，因此
 * 每一块各自都是「独立合法的 Markdown」——冻结块的渲染结果与它在整篇文档里时完全一致，松散
 * 列表 / 多行引用 / 代码块都不会被从中劈开。调用方对**收尾后的最终内容仍按整篇渲染一次**，
 * 故本切分保守漏掉的跨块引用（如 `[ref]` 链接定义）会在终态被正确解析。
 */
/** 续行：列表项 / 有序列表项 / 引用 / 缩进（≥2 空格或 Tab）。绝不在这类行之前切分，
 *  以免把松散列表、多行引用、缩进代码从中劈开。 */
const CONTINUATION = /^(?:\s*(?:[-*+]|\d+[.)])\s|>|\s{2,}\S|\t)/;
/** 栅栏围栏：``` 或 ~~~（长度 ≥ 3），允许少量前导空格。 */
const FENCE = /^\s*(`{3,}|~{3,})/;

/**
 * 把流式内容切成**一串顶层块**，恒满足 `blocks.join("") === content`。
 *
 * 每个切分点落在一个「块边界」：栅栏代码块之外、且其后下一非空行不是列表/引用/缩进续行的
 * 空行处（边界归属**前一块**，即块含其后的空行）。已写完的块从此不再变化 → 逐块记忆化下
 * 只解析一次；只有最后一块（在写尾块）随 delta 增长重解析。空串返回 `[]`；无完整块（无这样
 * 的空行）时整体作为唯一一块返回 `[content]`。仅供流式期调用；收尾后整篇渲染一次，无需切分。
 */
export function splitMarkdownBlocks(content: string): string[] {
  if (content === "") return [];
  // 连一个空行都没有 → 没有可冻结的完整块，整体是唯一一块。
  if (!content.includes("\n\n")) return [content];

  const lines = content.split("\n");
  // 每行在原串中的起始字符下标（用于把行号换算回切分点）。
  const starts = new Array<number>(lines.length);
  let off = 0;
  for (let i = 0; i < lines.length; i++) {
    starts[i] = off;
    off += lines[i].length + 1; // +1 为被 split 掉的 "\n"
  }

  const cuts: number[] = []; // 各块边界字符下标（升序、去重）
  let last = -1;
  let inFence = false;
  let fenceChar = "";
  for (let i = 0; i < lines.length; i++) {
    const fence = FENCE.exec(lines[i]);
    if (fence) {
      if (!inFence) {
        inFence = true;
        fenceChar = fence[1][0];
      } else if (fence[1][0] === fenceChar) {
        inFence = false;
        fenceChar = "";
      }
      continue;
    }
    if (inFence) continue;
    if (lines[i].trim() !== "") continue;

    // 一个栅栏外的空行：找它之后的下一非空行来判定能否在此切。
    let j = i + 1;
    while (j < lines.length && lines[j].trim() === "") j++;
    if (j >= lines.length) break; // 末尾只剩空行——其后无内容可冻结
    if (CONTINUATION.test(lines[j])) continue; // 是续行 → 保持整组不切
    const cut = starts[j];
    // 同一段连续空行会对同一 j 反复命中；只记一次边界。
    if (cut !== last) {
      cuts.push(cut);
      last = cut;
    }
  }

  if (cuts.length === 0) return [content];
  const blocks: string[] = [];
  let prev = 0;
  for (const cut of cuts) {
    blocks.push(content.slice(prev, cut));
    prev = cut;
  }
  blocks.push(content.slice(prev));
  return blocks;
}
