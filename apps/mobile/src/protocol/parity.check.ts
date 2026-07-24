// 对等对账门禁 (parity gate) · 运行时校验 —— 由 conformance.run.ts 调用，挂在现有 mobile
// conformance / CI job 上（与 fold conformance 同一个门）。
//
// 锚 A（协议事件）的穷尽性由 `Record<SSEEventType, ParityEntry>` 在 `tsc` 编译期保证（CI mobile
// typecheck）；此处再做运行时的「裁决质量」自检（必填的 reason/surface 没漏）。
// 锚 B（桌面交互面）扫 apps/desktop/.../components/chat 顶层 + `ask/` 子树（提问 intent 专用卡；
// 其余子目录仍为卡内部实现、不入表免抖动）、锚 C（桌面页面）递归扫 apps/desktop/.../pages：
// 每个 .tsx 必须在对应登记表有裁决（桌面新建一面/一页 → 红），并报告指向已不存在文件的陈旧键。
// 读桌面目录为只读 glob（monorepo 内），不引入对桌面代码的依赖。

import { readdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import {
  DESKTOP_CHAT_PARITY,
  DESKTOP_PAGE_PARITY,
  EVENT_PARITY,
  type ParityEntry,
} from "./parity";

const HERE = dirname(fileURLToPath(import.meta.url));
// apps/mobile/src/protocol → apps/desktop/src/renderer/components/chat
const DESKTOP_CHAT_DIR = join(
  HERE,
  "..",
  "..",
  "..",
  "desktop",
  "src",
  "renderer",
  "components",
  "chat",
);
// apps/mobile/src/protocol → apps/desktop/src/renderer/pages
const DESKTOP_PAGES_DIR = join(
  HERE,
  "..",
  "..",
  "..",
  "desktop",
  "src",
  "renderer",
  "pages",
);

export interface ParityProblem {
  anchor: "event" | "desktop-card" | "desktop-page";
  key: string;
  detail: string;
}

/** Required-field discipline per verdict: ported→surface; simplified/impossible/internal→reason.
 *  Forces every entry to be a deliberate, documented decision (no bare verdicts). */
function entryProblem(entry: ParityEntry): string | null {
  if (entry.verdict === "ported") {
    return entry.surface ? null : "ported 裁决缺 surface（须指明手机落点）";
  }
  return entry.reason ? null : `${entry.verdict} 裁决缺 reason`;
}

/** 锚 A 兜底：逐条校验事件裁决的必填字段（穷尽性已由 tsc 的 Record 类型保证）。 */
function checkEventEntries(problems: ParityProblem[]): void {
  for (const [type, entry] of Object.entries(EVENT_PARITY)) {
    const p = entryProblem(entry);
    if (p) problems.push({ anchor: "event", key: type, detail: p });
  }
}

/** 收集 `dir` 下的 .tsx 面文件。`recursive` 时下钻子目录、key = 相对 `dir` 的路径（正斜杠、去 .tsx）
 *  使嵌套同名文件保持区分（如 ConversationsPage 桶文件 vs conversations/ConversationsPage 实体）；
 *  否则只取顶层（锚 B 卡级粒度——多数子目录是卡内部实现，且辩论等正被并行重写，不入表免抖动）。
 *  测试文件（*.test.tsx / __tests__）不是面，恒跳过。 */
function collectTsxKeys(dir: string, recursive: boolean): Set<string> {
  const keys = new Set<string>();
  const walk = (cur: string, prefix: string): void => {
    for (const ent of readdirSync(cur, { withFileTypes: true })) {
      if (ent.isDirectory()) {
        if (!recursive || ent.name === "__tests__") continue;
        walk(join(cur, ent.name), prefix ? `${prefix}/${ent.name}` : ent.name);
      } else if (ent.name.endsWith(".tsx") && !ent.name.endsWith(".test.tsx")) {
        const base = ent.name.replace(/\.tsx$/, "");
        keys.add(prefix ? `${prefix}/${base}` : base);
      }
    }
  };
  walk(dir, "");
  return keys;
}

/** 锚 B 对照面：顶层 .tsx + `ask/` 子树（提问 intent 专用卡族；key 带 `ask/` 前缀）。 */
function collectDesktopChatKeys(dir: string): Set<string> {
  const keys = collectTsxKeys(dir, false);
  const askDir = join(dir, "ask");
  try {
    for (const rel of collectTsxKeys(askDir, true)) {
      keys.add(`ask/${rel}`);
    }
  } catch {
    // ask/ 缺失时由 checkDirParity 对整目录失败路径统一报；此处仅合并可选子树。
  }
  return keys;
}

/** 锚 B/C 通用：扫桌面目录，断言每个 .tsx 都在登记表里有裁决（新增面 → 红）、报告陈旧键
 *  （桌面已删/改名 → 红），并逐条校验必填字段质量。`keys` 可注入自定义收集（锚 B = 顶层+ask/）；
 *  否则 `recursive` 决定卡级（顶层）还是页级（下钻路由子目录）。读桌面目录为只读 glob
 *  （monorepo 内），不引入对桌面代码的依赖。 */
function checkDirParity(
  dir: string,
  table: Record<string, ParityEntry>,
  anchor: ParityProblem["anchor"],
  unclassifiedDetail: string,
  recursive: boolean,
  problems: ParityProblem[],
  keys?: Set<string>,
): void {
  let present: Set<string>;
  try {
    present = keys ?? collectTsxKeys(dir, recursive);
  } catch {
    problems.push({ anchor, key: "(dir)", detail: `桌面目录读不到：${dir}` });
    return;
  }
  // 桌面新建/已有但未分类的面 → 必须给出对等裁决。
  for (const name of present) {
    if (!(name in table)) {
      problems.push({ anchor, key: name, detail: unclassifiedDetail });
    }
  }
  // 登记表里指向已不存在的桌面文件（已删/改名）→ 提示清理，防表自身漂移。
  for (const [name, entry] of Object.entries(table)) {
    if (!present.has(name)) {
      problems.push({
        anchor,
        key: name,
        detail: "登记表指向已不存在的桌面文件（桌面已删/改名，请清理或更名）",
      });
      continue;
    }
    const p = entryProblem(entry);
    if (p) problems.push({ anchor, key: name, detail: p });
  }
}

/** Collect deliberate non-ported verdicts for the PASS report (known gaps inventory).
 *  Gate stays green: simplified/impossible/internal are documented decisions, not failures. */
function collectKnownGaps(): Array<{
  anchor: ParityProblem["anchor"];
  key: string;
  verdict: ParityEntry["verdict"];
  detail: string;
}> {
  const gaps: Array<{
    anchor: ParityProblem["anchor"];
    key: string;
    verdict: ParityEntry["verdict"];
    detail: string;
  }> = [];
  const push = (
    anchor: ParityProblem["anchor"],
    table: Record<string, ParityEntry>,
  ) => {
    for (const [key, entry] of Object.entries(table)) {
      if (entry.verdict === "ported") continue;
      gaps.push({
        anchor,
        key,
        verdict: entry.verdict,
        detail: entry.reason ?? entry.surface ?? "",
      });
    }
  };
  push("event", EVENT_PARITY);
  push("desktop-card", DESKTOP_CHAT_PARITY);
  push("desktop-page", DESKTOP_PAGE_PARITY);
  return gaps;
}

/** Run all parity assertions, print a red/green report, return the problem count (0 = green).
 *  Mirrors runConformance's report shape so the two read alike in CI logs. PASS also prints
 *  the known-gap inventory (simplified / impossible；internal 略）so「如实」不靠假绿。 */
export function runParityChecks(): number {
  const problems: ParityProblem[] = [];
  checkEventEntries(problems);
  let chatKeys: Set<string> | undefined;
  try {
    chatKeys = collectDesktopChatKeys(DESKTOP_CHAT_DIR);
  } catch {
    chatKeys = undefined; // checkDirParity 会报目录读不到
  }
  checkDirParity(
    DESKTOP_CHAT_DIR,
    DESKTOP_CHAT_PARITY,
    "desktop-card",
    "桌面交互面未在 DESKTOP_CHAT_PARITY 给出手机对等裁决（新增/漏分类）",
    false, // 卡级：顶层；ask/ 经 collectDesktopChatKeys 另并入
    problems,
    chatKeys,
  );
  checkDirParity(
    DESKTOP_PAGES_DIR,
    DESKTOP_PAGE_PARITY,
    "desktop-page",
    "桌面页面未在 DESKTOP_PAGE_PARITY 给出手机对等裁决（新增/漏分类）",
    true, // 页级：下钻路由子目录（more/、toolbox/、conversations/…）
    problems,
  );

  const total =
    Object.keys(EVENT_PARITY).length +
    Object.keys(DESKTOP_CHAT_PARITY).length +
    Object.keys(DESKTOP_PAGE_PARITY).length;
  console.log(
    `\nparity · mobile · ${total} surfaces (events + desktop chat + desktop pages)`,
  );
  if (problems.length === 0) {
    const gaps = collectKnownGaps().filter(
      (g) => g.verdict === "simplified" || g.verdict === "impossible",
    );
    if (gaps.length > 0) {
      console.log(
        `  known gaps (${gaps.length} simplified/impossible — documented, not failures):`,
      );
      for (const g of gaps) {
        console.log(`  ○ [${g.anchor}] ${g.key} — ${g.verdict}: ${g.detail}`);
      }
    }
    console.log(`  PASS (0 problems; ${gaps.length} known gaps)`);
  } else {
    for (const p of problems)
      console.log(`  ✗ [${p.anchor}] ${p.key} — ${p.detail}`);
    console.log(`  FAIL (${problems.length} problems)`);
  }
  return problems.length;
}
