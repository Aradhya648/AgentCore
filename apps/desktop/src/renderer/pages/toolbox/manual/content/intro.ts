import { APP_PATHS } from "../paths";
import { MANUAL_SECTION_IDS } from "../sectionIds";
import type { ManualChapterContent } from "../types";

/**
 * 认识 AgentCore —— 内容源样板（结构化 blocks，无 JSX）。
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
          text: "AgentCore 是一支 AI 团队工作台：你只对接一位 CEO——简单问题它直接答；复杂任务它自己拉人、分工、互审，再把结果交给你。",
        },
        {
          type: "callout",
          variant: "tip",
          text: [
            "一句话：",
            { text: "你带团队，不是盯一个助手。", strong: true },
          ],
        },
      ],
    },
    {
      id: MANUAL_SECTION_IDS.intro.mindset,
      title: "核心心智：你是领导者",
      icon: "Crown",
      blocks: [
        {
          type: "lead",
          text: "用好它的秘诀就一个：别把自己当操作员，把自己当老板。",
        },
        {
          type: "bullets",
          items: [
            {
              title: "说目标，别说步骤",
              desc: "怎么拆、谁来做、先后顺序——这些交给 CEO。",
            },
            {
              title: "小事秒答，大事才动团队",
              desc: "闲聊或简单问答不会兴师动众；需要产出或多人协作时才组团。",
            },
            {
              title: "全程透明，随时插手",
              desc: "协作图实时滚动；觉得跑偏了，一条消息就能纠正。",
            },
          ],
        },
        {
          type: "callout",
          variant: "info",
          text: "你只跟 CEO 对话。背后怎么排并行、怎么收口、谁干什么，都是它的事。",
        },
      ],
    },
    {
      id: MANUAL_SECTION_IDS.intro.quickstart,
      title: "5 分钟上手",
      icon: "Rocket",
      blocks: [
        {
          type: "lead",
          text: "四步，约 5 分钟，从零到看见团队给你交活。",
        },
        {
          type: "steps",
          items: [
            {
              title: "直接开聊（平台额度）",
              desc: [
                "平台默认给你额度，打开就能用——无需先配 key。想用自己的模型？去 ",
                {
                  text: "设置 · 模型配置",
                  link: { kind: "go", to: APP_PATHS.more.model },
                },
                " 接入自己的 API Key 是可选进阶（自担费用）。",
              ],
            },
            {
              title: "说目标",
              desc: "新建对话，用大白话描述你想要什么。空态页的建议任务可一键填入——点一下再发送即可。",
            },
            {
              title: "看它干活",
              desc: "简单问题秒回；复杂任务会弹出协作图，每个人在做什么一目了然。",
            },
            {
              title: "收结果",
              desc: "CEO 把团队产出汇总成一份答案交给你。文件落在工作区——绑了本地文件夹就在你的电脑上，没绑则在云端项目里。",
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
