import { APP_PATHS } from "../paths";
import { MANUAL_SECTION_IDS } from "../sectionIds";
import type { ManualChapterContent } from "../types";

/**
 * 看懂协作（选读）——结构化内容源；真图 / 真 UI 经 embed 槽接入。
 *
 * 口径：机制透明是信任资产——用用户叙事讲清「团队怎么开工、怎么分批、怎么收口」，
 * 禁止实现术语（SSE / WaveScheduler / ReAct / finish_reason / depends_on /
 * Prepare·Execute·Finalize / max_parallel 等）。
 */
export const mechanismChapter: ManualChapterContent = {
  id: "mechanism",
  path: APP_PATHS.toolbox.manual.mechanism,
  label: "看懂协作（选读）",
  sections: [
    {
      id: MANUAL_SECTION_IDS.mechanism.live,
      title: "看团队跑一遍",
      icon: "PlayCircle",
      blocks: [
        {
          type: "callout",
          variant: "info",
          text: [
            "这一章是给好奇的人——想看懂团队在后台到底怎么转。",
            { text: "不看不影响使用", strong: true },
            "，用着用着想深究了再回来。",
          ],
        },
        {
          type: "lead",
          text: [
            "先别管符号——下面这张图和你复杂任务里看到的同源，正在",
            { text: "跑一遍", strong: true },
            "：看团队怎么分批开工、调研产出怎么汇入分析、最后由 CEO 收口落进答案。",
          ],
        },
        { type: "embed", key: "HeroGraph" },
        {
          type: "callout",
          variant: "tip",
          text: "节点亮蓝＝执行中、入边走粒子；变绿＝完成。背后半透明的「第 N 波」泳道，就是团队分轮推进的节奏。",
        },
      ],
    },
    {
      id: MANUAL_SECTION_IDS.mechanism.legend,
      title: "看懂协作图",
      icon: "BookOpen",
      blocks: [
        {
          type: "lead",
          text: "刚才那张图里的节点、连线、颜色、徽章分别是什么意思？下面一个个给你标清楚。",
        },
        { type: "embed", key: "GraphLegend" },
      ],
    },
    {
      id: MANUAL_SECTION_IDS.mechanism.panorama,
      title: "运行时全景",
      icon: "Layers",
      blocks: [
        {
          type: "lead",
          text: "你点发送之后，团队怎么接单、怎么分工推进、怎么收尾交付？三步走。简单对话直接回答；复杂任务才拉起一支团队。",
        },
        {
          type: "cards",
          cols: 3,
          items: [
            {
              title: "接单准备",
              desc: "CEO 接到你的目标，备好该用的能力与对话上下文。闲聊或简单问答当场答；只有需要产出、变更或多人协作时，才组团。",
              icon: "Target",
            },
            {
              title: "分工推进",
              desc: "CEO 拆活、派人：没有先后依赖的人同一批一起开干；有先后的等上游交活再解锁下一批。每位队员干完，产出交给下一位或汇总回 CEO。中途若要你拍板或放行敏感操作，会停下来问你——其他还能并行的人不受影响。",
              icon: "UsersRound",
              highlight: true,
            },
            {
              title: "收尾交付",
              desc: "活干完后回到 CEO，用自己的声音把结果交给你。中途断线也会尽量保住已完成的部分，不会一刀切全丢。",
              icon: "ShieldCheck",
            },
          ],
        },
        {
          type: "callout",
          variant: "info",
          text: "分批推进看的是分工有没有先后，不是另开一种「并行模式」——能一起干的就一起干，必须等的就排队。",
        },
      ],
    },
    {
      id: MANUAL_SECTION_IDS.mechanism.turnflow,
      title: "协作回合",
      icon: "Route",
      blocks: [
        {
          type: "lead",
          text: "从你发一句话，到答案出现在气泡里——中间经历了什么？CEO 什么时候拉人、队员怎么交接、最后怎么收口。",
        },
        {
          type: "steps",
          items: [
            {
              title: "你说出目标",
              desc: "提问落库；协作图左侧出现「你的任务」端点。",
            },
            {
              title: "CEO 判断要不要组团",
              desc: "闲聊或简单问答直接流式作答；需要产出、变更或多人时才拉团队。",
            },
            {
              title: "协作图先成形",
              desc: "本批队员节点一次性点亮为排队态——开跑前你就能看见整张分工图。",
            },
            {
              title: "按依赖分批推进",
              desc: "没有先后依赖的人同一批同时开工；有依赖的等上游齐了再解锁下一批。一批人同时干活时也有人数上限，超了会自动拆成更多批。",
            },
            {
              title: "队员各自干活",
              desc: "每位队员独立推进自己的任务，答案边写边流到节点上，入边走粒子。需要你拍板或放行工具时，会单独停下来问你。",
            },
            {
              title: "CEO 收口汇报",
              desc: "活干完后回到 CEO，用自己的声音写一段简短概览交给你。",
            },
            {
              title: "答案落进气泡",
              desc: "图上的 CEO 汇聚点＝这段最终答案；点它可跳到气泡，本回合收口。",
            },
          ],
        },
        {
          type: "paragraph",
          text: "中途你会看见的真界面",
          emphasis: true,
        },
        {
          type: "paragraph",
          text: "关键岔路弹出拍板卡；写文件、跑代码等敏感操作要你点「允许」才放行——下面就是对话里同一套组件，不是截图。",
        },
        { type: "embed", key: "ManualCheckpointCardPreview" },
        { type: "embed", key: "ManualApprovalCardPreview" },
      ],
    },
    {
      id: MANUAL_SECTION_IDS.mechanism.scenarios,
      title: "机制场景",
      icon: "LayoutGrid",
      blocks: [
        {
          type: "lead",
          text: [
            "下面都是",
            { text: "真的", strong: true },
            "协作图——和你对话里看到的一模一样。并行、串行、辩论三形态、嵌套、带现场续派……各种形态都在。",
          ],
        },
        {
          type: "callout",
          variant: "info",
          text: "不是截图，是实时渲染的真实组件。滚到才加载，随便看。",
        },
        {
          type: "paragraph",
          text: "辩论时，记分牌也是真组件",
          emphasis: true,
        },
        {
          type: "paragraph",
          text: "辩题、轮次、阵营比分与动量——和辩论室顶栏同一套。",
        },
        { type: "embed", key: "ManualDebateScoreboardPreview" },
        { type: "embed", key: "MechanismScenarios" },
      ],
    },
  ],
};
