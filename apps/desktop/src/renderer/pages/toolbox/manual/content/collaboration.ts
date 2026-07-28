import { APP_PATHS } from "../paths";
import { MANUAL_SECTION_IDS, manualHref } from "../sectionIds";
import type { ManualChapterContent } from "../types";

/**
 * 指挥你的团队 —— 结构化内容源（无 JSX）。
 *
 * 口径：任务导向、实用不营销；真组件演示归机制章，本章纯文字 block。
 */
export const collaborationChapter: ManualChapterContent = {
  id: "collaboration",
  path: APP_PATHS.toolbox.manual.collaboration,
  label: "指挥你的团队",
  sections: [
    {
      id: MANUAL_SECTION_IDS.collaboration["collab-overview"],
      title: "团队协作",
      icon: "Network",
      blocks: [
        {
          type: "lead",
          text: "复杂任务不是一个 AI 硬扛，而是一支 AI 团队分工合作——全程在协作图上看得见。",
        },
        {
          type: "paragraph",
          text: "什么时候会组团？",
          emphasis: true,
        },
        {
          type: "paragraph",
          text: "CEO 自己判断。能直接答的就直接答，需要动手做的才拉团队——你不用操心。",
        },
        {
          type: "paragraph",
          text: "四种协作姿势",
          emphasis: true,
        },
        {
          type: "cards",
          cols: 2,
          items: [
            {
              title: "并行扇出",
              desc: "几件事互不依赖？同时跑，最后汇总。",
            },
            {
              title: "串行流水线",
              desc: "调研 → 分析 → 撰写，上游喂下游。",
            },
            {
              title: "辩论 / 互审",
              desc: "正反、红队或圆桌交锋，主持人收口给简报。",
            },
            {
              title: "嵌套小队",
              desc: "队员还能再拉小队，大活分层推进。",
            },
          ],
        },
        {
          type: "callout",
          variant: "tip",
          text: [
            "想指定并行 / 串行 / 辩论，话术见 ",
            {
              text: "怎么下任务",
              link: {
                kind: "jump",
                to: MANUAL_SECTION_IDS.collaboration.briefing,
              },
            },
            "。图上符号见 ",
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
            "；辩论室细节见 ",
            {
              text: "辩论室",
              link: {
                kind: "jump",
                to: MANUAL_SECTION_IDS.collaboration.debate,
              },
            },
            "。",
          ],
        },
      ],
    },
    {
      id: MANUAL_SECTION_IDS.collaboration.briefing,
      title: "怎么下任务",
      icon: "Target",
      blocks: [
        {
          type: "lead",
          text: "你是老板，最该练的技能就一个——把目标说清楚。说得越准，团队产出越准。",
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
      id: MANUAL_SECTION_IDS.collaboration.roles,
      title: "角色分配",
      icon: "UsersRound",
      blocks: [
        {
          type: "lead",
          text: "没有固定的「代码 Agent」「写作 Agent」——每次任务，CEO 现场分配角色。",
        },
        {
          type: "bullets",
          items: [
            {
              title: "按需上岗",
              desc: "CEO 看任务需要什么，临时给队员配角色和工具（调研员 / 分析师 / 撰写员…）。",
            },
            {
              title: "为什么不固定？",
              desc: "真实任务跨领域，固定角色僵硬。你是老板，不该操心「这事该派给谁」。",
            },
          ],
        },
        {
          type: "callout",
          variant: "info",
          text: "你只跟 CEO 对话。背后怎么排并行、谁干什么，都是它的事。",
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
          text: "需要互审、压力测试或铺开多方观点时，CEO 会开一场辩论。过程本身也是产物——不只甩一个结论。",
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
          text: "辩论室三层",
          emphasis: true,
        },
        {
          type: "bullets",
          items: [
            {
              title: "记分牌",
              desc: "辩题、形态、轮次进度、阵营比分与动量；正反可站队。",
            },
            {
              title: "剧本主列",
              desc: "逐轮发言、主持人小结、质询问答，以及轮间掌舵入口。",
            },
            {
              title: "终审舞台",
              desc: "主持人终审：裁决倾向、战果对照、留给你的交接清单。",
            },
          ],
        },
        {
          type: "paragraph",
          text: "站队与掌舵",
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
          type: "callout",
          variant: "tip",
          text: "收场后还想再辩？直接在对话框对 CEO 说话——它会重开一场全新辩论，而不是复活上一场。",
        },
        {
          type: "callout",
          variant: "info",
          text: [
            "入口：协作图状态条出现「辩论」pill 时，点「打开辩论室」；也可在全屏回合详情切「辩论室」tab。协作图符号见 ",
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
            "。",
          ],
        },
      ],
    },
    {
      id: MANUAL_SECTION_IDS.collaboration.progress,
      title: "任务进度",
      icon: "Activity",
      blocks: [
        {
          type: "lead",
          text: "团队干到哪了、谁在忙、有没有卡住——聊天和画布两处都能看见，数据同源。",
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
          type: "paragraph",
          text: "图上能读到什么",
          emphasis: true,
        },
        {
          type: "bullets",
          items: [
            {
              title: "流式输出",
              desc: "每个队员边想边写，节点与侧栏实时更新。",
            },
            {
              title: "协作图",
              desc: "谁在跑、谁等着、谁完成了——一张图看全局。",
            },
            {
              title: "用时与工具",
              desc: "每个队员花了多久、调了几次工具，节点上都标着。",
            },
          ],
        },
        {
          type: "callout",
          variant: "tip",
          text: [
            "图例与符号说明见 ",
            {
              text: "看懂协作（选读）· 看懂协作图",
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
          text: "遇到关键决定或拿不准的地方，团队不会自作主张——会停下来问你。",
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
              title: "ask_user 拍板卡",
              desc: "两键：提交（带上选择与说明继续）+ 停止（结束本回合）。没有单独的「继续 / 调整」。",
            },
            {
              title: "plan_review 计划复核",
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
            " 联动：配方越托管，同类能力越少逐次弹窗。ask_user / plan_review 拍板节点不受配方改写。",
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
          text: "权限配方管「改文件 / 执行命令 / 组团卡」弹多少次。ask_user / plan_review 拍板仍会按需出现。",
        },
        {
          type: "paragraph",
          text: "四个配方怎么选",
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
              title: "写代码（推荐）",
              desc: "本会话信任改文件；跑代码与终端仍在开工卡确认；组团卡按规则。",
            },
            {
              title: "少打断",
              desc: "本会话信任改文件；执行经开工卡；跳过组团卡。",
            },
            {
              title: "托管",
              desc: "本会话信任改文件；免审执行；跳过组团卡。拍板检查点仍会出现。",
            },
          ],
        },
        {
          type: "settingsRows",
          rows: [
            {
              label: "设置 · 权限配方",
              desc: "新会话默认四选一；对话内徽章可改配方或单独调三轴，下一回合生效。",
              to: APP_PATHS.more.autonomy,
            },
          ],
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
      id: MANUAL_SECTION_IDS.collaboration.control,
      title: "中途接管",
      icon: "Hand",
      blocks: [
        {
          type: "lead",
          text: "全程你都是老板，随时能插手——不用干等它跑完。",
        },
        {
          type: "bullets",
          items: [
            {
              title: "带现场续派 / 同人接续",
              desc: "产物不满意？见「带现场续派」节——唤回原队员带完整现场接着改，不是从零重来。",
            },
            {
              title: "跑一半改方向",
              desc: "对某个队员点「立即改此人」（run_redirect）：取消当前执行、带已有进度换方向。辩论回合不可用——想改辩题请重开一场。",
            },
            {
              title: "只补跑失败项",
              desc: "部分队员失败时，可只重试失败项，已成功的继续保留。",
            },
            {
              title: "重新生成",
              desc: "方向全错或要整轮重来，从最后一条用户消息整轮再跑。",
            },
            {
              title: "停止",
              desc: "太慢或方向不对，点停止结束当前回合。",
            },
          ],
        },
        {
          type: "callout",
          variant: "tip",
          text: [
            "带现场续派细节见 ",
            {
              text: "带现场续派",
              link: {
                kind: "jump",
                to: MANUAL_SECTION_IDS.collaboration.continuation,
              },
            },
            "。",
          ],
        },
        {
          type: "callout",
          variant: "warning",
          text: "发消息默认是「在现有基础上改」。想彻底换方向，明确说「推翻重来」，或用重新生成。",
        },
      ],
    },
    {
      id: MANUAL_SECTION_IDS.collaboration.continuation,
      title: "带现场续派",
      icon: "RotateCcw",
      blocks: [
        {
          type: "lead",
          text: "产物不满意？说清要改哪——CEO 唤回原队员，带着完整现场接着改（口语也叫「同人接续」；旧称「热修」），不是从零重来。",
        },
        {
          type: "bullets",
          items: [
            {
              title: "接续链",
              desc: "同一队员、同一上下文；协作图上挂「续 ×N」接续链，可打开版本对比看各次产出。",
            },
            {
              title: "和「重新生成」的区别",
              desc: "续派 = 方向大致对、只改局部；重新生成 = 从最后一条用户消息整轮再答。整轮方向错了就用后者，或明确说「推翻重来」。",
            },
          ],
        },
        {
          type: "callout",
          variant: "tip",
          text: [
            "中途其他插手方式见 ",
            {
              text: "中途接管",
              link: {
                kind: "jump",
                to: MANUAL_SECTION_IDS.collaboration.control,
              },
            },
            "。",
          ],
        },
      ],
    },
    {
      id: MANUAL_SECTION_IDS.collaboration.memory,
      title: "记忆",
      icon: "Brain",
      blocks: [
        {
          type: "lead",
          text: "不用每次重新交代背景——团队会记住你是谁、你喜欢什么。",
        },
        {
          type: "bullets",
          items: [
            {
              title: "跨对话延续",
              desc: "换个对话也不用重新介绍自己和项目。",
            },
            {
              title: "越用越懂你",
              desc: "用得越多，它越清楚你的口味和习惯。",
            },
          ],
        },
        {
          type: "callout",
          variant: "tip",
          text: "想让它记住什么？直接说——「以后回答都用中文」「代码用 TypeScript」。说一次就够了。",
        },
      ],
    },
  ],
};
