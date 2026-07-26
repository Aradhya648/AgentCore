import type { AskCommenceScene } from "./askCommenceMock";

/** Preview-only scenes for 开工提案 layout A/B. Deep-link: `#/preview/ask-commence?s=<id>`. */
export const ASK_COMMENCE_SCENES: AskCommenceScene[] = [
  {
    id: "ask-commence-v1",
    title: "Compact Decision",
    intent:
      "决策优先：压缩说明、选项占主视觉，主/次 CTA 固定底栏——类似 Linear issue confirm。",
    paradigm: "Linear",
  },
  {
    id: "ask-commence-v2",
    title: "Brief + Choose",
    intent:
      "【已退役】题干与选项常驻（紧凑单行选项，决策空间一眼可见）；brief/起步计划/补充说明折叠收纳；风格 pills 常驻一行。留作 v5 的对照。",
    paradigm: "Notion AI × Executive Summary",
  },
  {
    id: "ask-commence-v3",
    title: "Wizard Step",
    intent:
      "一题一答：当前题绝对焦点、大选项卡；进度克制，计划沉为次要 chips。",
    paradigm: "Structured wizard",
  },
  {
    id: "ask-commence-v4",
    title: "Executive Summary",
    intent:
      "顶部一行结论 + 关键参数 pill，下方精简选项列表——Cursor / ChatGPT 确认条升级版。",
    paradigm: "Cursor / ChatGPT",
  },
  {
    id: "ask-commence-v5",
    title: "Row List",
    intent:
      "【生产默认】单页全览不变，视觉换成行式选项：无描边、发丝分隔线、hover 整行灰底 + 右侧 →，序号方块反白即选中；彩色徽章全删，起步计划常驻两列表，只剩「补充说明」一个折叠入口。",
    paradigm: "Claude Code AskUserQuestion",
  },
];
