import { APP_PATHS } from "../paths";
import { MANUAL_SECTION_IDS } from "../sectionIds";
import type { ManualChapterContent } from "../types";

/**
 * 认识 AgentCore —— 第一章内容源。
 *
 * 口径：实用说明、不营销；上手四步与空态引导（DraftEmptyState）对齐。
 */
export const introChapter: ManualChapterContent = {
  id: "intro",
  path: APP_PATHS.toolbox.manual.intro,
  label: "认识 AgentCore",
  sections: [
    {
      id: MANUAL_SECTION_IDS.intro.what,
      title: "这是什么",
      icon: "Compass",
      blocks: [
        {
          type: "lead",
          text: "AgentCore 是 Multi-Agent AI 工作台：你只对接一位 CEO；简单问题它直接答，复杂任务它组团协作后把结果交给你。",
        },
        {
          type: "callout",
          variant: "tip",
          text: [{ text: "协作，是更高级的智能", strong: true }],
        },
      ],
    },
    {
      id: MANUAL_SECTION_IDS.intro.mindset,
      title: "你怎么用",
      icon: "Target",
      blocks: [
        {
          type: "bullets",
          items: [
            {
              title: "说目标，别说步骤",
              desc: "怎么拆、谁来做、先后顺序——交给 CEO。",
            },
            {
              title: "小事秒答，大事才组团",
              desc: "闲聊或简单问答直接回；需要产出或多人协作时才拉人。",
            },
            {
              title: "全程透明，随时插手",
              desc: "协作图实时可见；觉得跑偏了，一条消息就能纠正。",
            },
          ],
        },
        {
          type: "paragraph",
          text: "没有固定角色——CEO 按任务临时分配谁上场。",
        },
      ],
    },
    {
      id: MANUAL_SECTION_IDS.intro.quickstart,
      title: "5 分钟上手",
      icon: "Rocket",
      blocks: [
        {
          type: "steps",
          items: [
            {
              title: "直接开聊（平台额度）",
              desc: [
                "平台默认给你额度，打开就能用。想用自己的模型？去 ",
                {
                  text: "设置 · 服务商",
                  link: { kind: "go", to: APP_PATHS.more.providers },
                },
                " 接入 API Key（可选，自担费用）。",
              ],
            },
            {
              title: "说目标",
              desc: "新建对话，用大白话描述你想要什么。空态页的建议任务可一键填入。",
            },
            {
              title: "看它干活",
              desc: "简单问题秒回；复杂任务会弹出协作图，谁在做什么一目了然。",
            },
            {
              title: "收结果",
              desc: "CEO 汇总团队产出交给你。文件落在工作区——绑了本地文件夹就在你电脑上，没绑则在云端项目里。",
            },
          ],
        },
        {
          type: "callout",
          variant: "tip",
          text: "想立刻看见多人协作，试试：「分三路并行调研：竞品定价、用户痛点、渠道策略，各自产出一页摘要后由你汇总成决策简报。」",
        },
      ],
    },
  ],
};
