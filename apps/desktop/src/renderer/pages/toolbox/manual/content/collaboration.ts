import { APP_PATHS } from "../paths";
import { MANUAL_SECTION_IDS, manualHref } from "../sectionIds";
import type { ManualChapterContent } from "../types";

/**
 * 指挥你的团队 —— 结构化内容源（无 JSX）。
 *
 * 口径：按用户动作排；去重、去内部名；真组件演示归机制章。
 */
export const collaborationChapter: ManualChapterContent = {
  id: "collaboration",
  path: APP_PATHS.toolbox.manual.collaboration,
  label: "指挥你的团队",
  sections: [
    {
      id: MANUAL_SECTION_IDS.collaboration.briefing,
      title: "怎么下任务",
      icon: "Target",
      blocks: [
        {
          type: "lead",
          text: "把目标说清楚，团队产出才准。能直接答的 CEO 自己答；要动手做的才拉团队——角色由 CEO 临时分配，你不用点名。",
        },
        {
          type: "paragraph",
          text: "一个好任务的三件套",
          emphasis: true,
        },
        {
          type: "bullets",
          items: [
            {
              title: "目标",
              desc: "你要的是什么结果，一句话说清。",
            },
            {
              title: "约束",
              desc: "边界、口味、不要什么——比如「保持接口不变」「用中文」。",
            },
            {
              title: "期望产出",
              desc: "一段摘要？一个能跑的脚本？几个方案对比？说出形态。",
            },
          ],
        },
        {
          type: "doDont",
          good: {
            items: [
              "调研近 7 日成本趋势、定位异常点，产出一段 200 字摘要 + 一张趋势表。",
              "用 TypeScript 重写这个模块，保持现有接口不变，并补单元测试。",
            ],
          },
          bad: {
            items: ["看看成本。", "优化一下代码。"],
          },
        },
        {
          type: "paragraph",
          text: "想指定协作姿势时",
          emphasis: true,
        },
        {
          type: "bullets",
          items: [
            {
              title: "并行",
              desc: "「分三路并行调研：竞品定价、用户痛点、渠道策略，各自产出一页摘要后由你汇总。」",
            },
            {
              title: "串行",
              desc: "「先调研再分析再写方案，上游产出喂给下游。」",
            },
            {
              title: "辩论",
              desc: "「就这个方案开一场正反辩论，再给我决策简报。」或指定红队挑刺 / 多方圆桌。",
            },
          ],
        },
        {
          type: "callout",
          variant: "tip",
          text: "不确定怎么拆？只说目标就行——说清「要什么」永远比说清「怎么做」更重要。",
        },
      ],
    },
    {
      id: MANUAL_SECTION_IDS.collaboration.progress,
      title: "看进度",
      icon: "Activity",
      blocks: [
        {
          type: "lead",
          text: "干到哪了、谁在忙、有没有卡住——聊天和画布同源，随时能看见。",
        },
        {
          type: "paragraph",
          text: "聊天 ⇄ 画布",
          emphasis: true,
        },
        {
          type: "bullets",
          items: [
            {
              title: "聊天视图",
              desc: "默认视图：流式输出 + 内嵌协作图；点「在画布打开」一键切换。",
            },
            {
              title: "画布视图",
              desc: "按对话切换的第二视图：聚焦回合展开完整协作图，其余回合塌成摘要。",
            },
            {
              title: "指挥台",
              desc: "画布侧面板顶部常驻区——检查点、审批、续跑、救火就地拍板，不用切回聊天。",
            },
          ],
        },
        {
          type: "callout",
          variant: "tip",
          text: [
            "图上符号与状态色见 ",
            {
              text: "看懂协作图",
              link: {
                kind: "go",
                to: manualHref(
                  "mechanism",
                  MANUAL_SECTION_IDS.mechanism.legend,
                ),
              },
            },
            "，此处不复述。",
          ],
        },
      ],
    },
    {
      id: MANUAL_SECTION_IDS.collaboration.checkpoint,
      title: "检查点与审批",
      icon: "ShieldCheck",
      blocks: [
        {
          type: "lead",
          text: "关键决定或拿不准时，团队会停下来问你，不会自作主张。",
        },
        {
          type: "paragraph",
          text: "什么时候会停下",
          emphasis: true,
        },
        {
          type: "bullets",
          items: [
            {
              title: "开场澄清",
              desc: "需求能做但还不够明确时，CEO 先给起步计划 + 重点问题，让你补齐再开工。",
            },
            {
              title: "关键岔路",
              desc: "影响全局的 A / B 选择，或不可逆操作，停下等你拍板。",
            },
            {
              title: "工具授权",
              desc: "敏感操作先征得你同意再执行——弹窗频率由权限配方决定。",
            },
            {
              title: "计划复核",
              desc: "流水线波间闸门：上游做完、下游待跑时，可先确认再放行。",
            },
          ],
        },
        {
          type: "paragraph",
          text: "拍板卡怎么点（两类按键不同）",
          emphasis: true,
        },
        {
          type: "bullets",
          items: [
            {
              title: "拍板卡",
              desc: "两键：提交（带上选择与说明继续）+ 停止（结束本回合）。没有单独的「继续 / 调整」。",
            },
            {
              title: "计划复核",
              desc: "三键：继续 / 调整（备注注入未跑下游）/ 停止。",
            },
          ],
        },
        {
          type: "callout",
          variant: "info",
          text: [
            "写文件、跑代码等工具审批与 ",
            {
              text: "自主度",
              link: {
                kind: "jump",
                to: MANUAL_SECTION_IDS.collaboration.autonomy,
              },
            },
            " 联动：配方越托管，同类能力越少逐次弹窗。拍板卡与计划复核不受配方改写。",
          ],
        },
        {
          type: "callout",
          variant: "tip",
          text: "某个队员干到一半卡住，会单独「升级」上来问你——不会拖住其他还在并行跑的队员。关掉窗口也没关系：停在检查点的任务会被存住，下次从断点续。",
        },
      ],
    },
    {
      id: MANUAL_SECTION_IDS.collaboration.autonomy,
      title: "自主度",
      icon: "SlidersHorizontal",
      blocks: [
        {
          type: "lead",
          text: "权限配方管「改文件 / 执行命令 / 组团卡」弹多少次。拍板卡与计划复核仍会按需出现。",
        },
        {
          type: "paragraph",
          text: "三个配方怎么选",
          emphasis: true,
        },
        {
          type: "cards",
          cols: 2,
          items: [
            {
              title: "谨慎",
              desc: "改文件逐次问；不预授执行；组团卡按规则。最稳，批量改文件时会很吵。",
            },
            {
              title: "少打断（推荐）",
              desc: "本会话信任改文件；自动执行；组团卡按规则；本机每次确认。",
            },
            {
              title: "托管",
              desc: "本会话信任改文件；自动执行；跳过组团卡；本机会话信任。拍板检查点仍会出现。",
            },
          ],
        },
        {
          type: "callout",
          variant: "tip",
          text: "桌面：对话输入区权限徽章选三配方之一后，点「设为新会话默认」写入账户默认（只影响之后新建的对话；自定义权限轴不可设为默认）。手机仍可在设置改默认。已有会话请在徽章切配方或权限轴，下一回合生效。",
        },
        {
          type: "callout",
          variant: "tip",
          text: [
            "与 ",
            {
              text: "检查点与审批",
              link: {
                kind: "jump",
                to: MANUAL_SECTION_IDS.collaboration.checkpoint,
              },
            },
            " 的关系：配方减的是工具审批与组团卡疲劳；拍板与计划复核仍走检查点。非法组合「免审执行 + 改文件逐次问」选不出。",
          ],
        },
      ],
    },
    {
      id: MANUAL_SECTION_IDS.collaboration.debate,
      title: "辩论室",
      icon: "Swords",
      blocks: [
        {
          type: "lead",
          text: "需要互审、压力测试或铺开多方观点时，CEO 会开一场辩论——过程本身也是产物。",
        },
        {
          type: "paragraph",
          text: "三种形态",
          emphasis: true,
        },
        {
          type: "cards",
          cols: 3,
          items: [
            {
              title: "正反辩论",
              desc: "正 / 反对称攻防，适合二选一决策。",
            },
            {
              title: "红队挑刺",
              desc: "红队单向找风险，方案方回应，产出风险清单。",
            },
            {
              title: "多方圆桌",
              desc: "3+ 视角碰撞，铺开观点光谱。",
            },
          ],
        },
        {
          type: "paragraph",
          text: "你能做什么",
          emphasis: true,
        },
        {
          type: "bullets",
          items: [
            {
              title: "站队",
              desc: "记分牌上点选倾向——仅你可见，绝不改写 AI 裁决。",
            },
            {
              title: "掌舵",
              desc: "轮间轻量引导（追问 / 加角度 / 够了收），下一轮生效，不硬停辩论。",
            },
          ],
        },
        {
          type: "paragraph",
          text: "界面速览",
          emphasis: true,
        },
        {
          type: "bullets",
          items: [
            {
              title: "记分牌",
              desc: "辩题、形态、轮次与阵营比分。",
            },
            {
              title: "剧本主列",
              desc: "逐轮发言、主持人小结、质询与掌舵入口。",
            },
            {
              title: "终审舞台",
              desc: "裁决倾向、战果对照、交接清单。",
            },
          ],
        },
        {
          type: "callout",
          variant: "info",
          text: [
            "入口：协作图状态条出现「辩论」时点「打开辩论室」；或在全屏回合详情切「辩论室」tab。图上符号见 ",
            {
              text: "看懂协作图",
              link: {
                kind: "go",
                to: manualHref(
                  "mechanism",
                  MANUAL_SECTION_IDS.mechanism.legend,
                ),
              },
            },
            "。收场后还想再辩？直接对 CEO 说话——会重开一场，而不是复活上一场。",
          ],
        },
      ],
    },
    {
      id: MANUAL_SECTION_IDS.collaboration.control,
      title: "中途插手",
      icon: "Hand",
      blocks: [
        {
          type: "lead",
          text: "跑偏了不用干等——随时能停、能纠偏、能续派。",
        },
        {
          type: "bullets",
          items: [
            {
              title: "停止",
              desc: "太慢或方向不对，点停止结束当前回合。",
            },
            {
              title: "纠偏换方向",
              desc: "对某个队员点「立即改此人」：取消当前执行、带已有进度换方向。辩论回合不可用——想改辩题请重开一场。",
            },
            {
              title: "带现场续派",
              desc: "产物大致对、只改局部：唤回原队员带完整现场接着改（口语也叫「同人接续」），协作图上挂「续 ×N」，可打开版本对比。不是从零重来。",
            },
            {
              title: "续聊或再发",
              desc: "部分队员失败时，失败会留在图上可见；对 CEO 续聊或再发一条，让团队接着补。",
            },
            {
              title: "重新生成",
              desc: "方向全错或要整轮重来，从最后一条用户消息整轮再跑。",
            },
          ],
        },
        {
          type: "callout",
          variant: "warning",
          text: "发消息默认是「在现有基础上改」。想彻底换方向，明确说「推翻重来」，或用重新生成。续派适合局部打磨；整轮方向错了用重新生成。",
        },
      ],
    },
    {
      id: MANUAL_SECTION_IDS.collaboration.memory,
      title: "记忆与偏好",
      icon: "Brain",
      blocks: [
        {
          type: "lead",
          text: "不用每次重新交代背景——偏好与项目习惯会跨对话延续。",
        },
        {
          type: "paragraph",
          text: "怎么让它记住",
          emphasis: true,
        },
        {
          type: "bullets",
          items: [
            {
              title: "直接说",
              desc: "「以后回答都用中文」「代码用 TypeScript」「别改公开 API」——说一次就够。",
            },
            {
              title: "越用越懂",
              desc: "常用口味与项目习惯会沉淀下来；换个对话也不用重新介绍自己和项目。",
            },
          ],
        },
        {
          type: "paragraph",
          text: "怎么改、怎么清",
          emphasis: true,
        },
        {
          type: "bullets",
          items: [
            {
              title: "口头改写",
              desc: "直接说「忘掉上次说的……」或「改成……」即可。",
            },
            {
              title: "文件页 · AI 记忆",
              desc: "打开文件页的「AI 记忆」，可查看、编辑或清理长期记忆。",
            },
          ],
        },
        {
          type: "callout",
          variant: "info",
          text: [
            "入口：",
            {
              text: "文件",
              link: { kind: "go", to: APP_PATHS.files },
            },
            " → AI 记忆。记忆来自你的对话偏好；与数据留存、导出等关系见 ",
            {
              text: "数据与隐私",
              link: {
                kind: "go",
                to: manualHref(
                  "reference",
                  MANUAL_SECTION_IDS.reference.privacy,
                ),
              },
            },
            "。",
          ],
        },
      ],
    },
  ],
};
