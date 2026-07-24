import { APP_PATHS } from "../paths";
import { MANUAL_SECTION_IDS } from "../sectionIds";
import type { ManualChapterContent } from "../types";

/** 参考 · 排查 · 信任 —— 结构化内容源（无 JSX）。 */
export const referenceChapter: ManualChapterContent = {
  id: "reference",
  path: APP_PATHS.toolbox.manual.reference,
  label: "参考 · 排查 · 信任",
  sections: [
    {
      id: MANUAL_SECTION_IDS.reference.chat,
      title: "对话",
      icon: "MessageSquare",
      blocks: [
        {
          type: "lead",
          text: "对话就是你的指挥台——所有事都从这里开始。",
        },
        {
          type: "bullets",
          items: [
            {
              title: "说人话就行",
              desc: "用日常语言描述目标，不需要任何特殊格式。",
            },
            {
              title: "富表达",
              desc: "可以贴代码、引用文件、发富文本。",
            },
            {
              title: "历史对话",
              desc: "左侧列表管理所有对话，分组、搜索、随时续聊。",
            },
          ],
        },
        {
          type: "callout",
          variant: "tip",
          text: "越具体越好——「目标 + 约束 + 想要什么」说清楚，团队产出就越准。",
        },
      ],
    },
    {
      id: MANUAL_SECTION_IDS.reference.tools,
      title: "工具与能力",
      icon: "Wrench",
      blocks: [
        {
          type: "lead",
          text: "工具是团队的「手」——读文件、查资料、调外部 API，全靠这些。",
        },
        {
          type: "bullets",
          items: [
            {
              title: "内置工具",
              desc: "平台自带，所有 Agent 开箱即用——读文件、搜索、执行等。",
            },
            {
              title: "白板（已可用）",
              desc: "工具箱里的独立创作工具：自由摆元素、读图、和团队一起画。",
            },
            {
              title: "其他创作工具（即将上线）",
              desc: "文档 / 思维导图 / 表格 / 幻灯片 / 流程图 / 表单 / 可运行产物——尚未开放。",
            },
            {
              title: "MCP（规划中）",
              desc: "接入第三方工具与数据源的行业标准协议——工具箱「集成 · 连接器」仍为占位。",
            },
            {
              title: "A2A（规划中）",
              desc: "连接外部 Agent 的行业标准协议——尚未开放入口。",
            },
          ],
        },
        {
          type: "callout",
          variant: "tip",
          text: [
            "完整清单在 ",
            {
              text: "工具箱 · 能力图鉴",
              link: { kind: "go", to: APP_PATHS.toolbox.tools },
            },
            "——每个工具能做什么、谁可用，一目了然。",
          ],
        },
        {
          type: "bullets",
          items: [
            {
              title: "读代码与 Git 状态",
              desc: "Agent 可读工作区文件、git status / diff / log，无需你逐次点头。",
            },
            {
              title: "改文件与 Git 写入",
              desc: "写文件、git add / commit / 切分支等会弹出审批——你可以「允许一次」或「本轮内都允许」。",
            },
          ],
        },
      ],
    },
    {
      id: MANUAL_SECTION_IDS.reference.workspace,
      title: "工作区与文件",
      icon: "FolderOpen",
      blocks: [
        {
          type: "lead",
          text: "团队做出来的东西，都落在工作区——你和 AI 共享的文件空间。项目即工作区：创建项目时选定本地或云端，之后不可改。",
        },
        {
          type: "bullets",
          items: [
            {
              title: "项目即工作区",
              desc: "建项目时必须绑定工作区（本地文件夹或云端空间），创建时确定、事后不改绑；项目内对话共用这份空间。",
            },
            {
              title: "绑本地文件夹",
              desc: "创建时选本地——团队直接改你电脑上的真实项目，适合开发内环。",
            },
            {
              title: "不绑 → 云端项目",
              desc: "创建时选云端，或随手裸聊用对话临时空间——文件在服务端；手机、网页也能看同一项目。",
            },
            {
              title: "模式条",
              desc: "对话页顶部的云/本地指示条告诉你当前在哪跑；可随时看清绑定状态。",
            },
            {
              title: "右坞终端",
              desc: "右侧面板「终端」tab：你的交互 shell、后台进程与执行记录——长任务可观测、可停。",
            },
            {
              title: "文件工作台",
              desc: "在文件页直接看、改、整理产物。",
            },
          ],
        },
        {
          type: "callout",
          variant: "tip",
          text: "想让团队基于某个文件干活？对话里直接引用它就行。",
        },
      ],
    },
    {
      id: MANUAL_SECTION_IDS.reference.settings,
      title: "设置速查",
      icon: "Settings",
      blocks: [
        {
          type: "lead",
          text: "常用设置入口，点击直达。",
        },
        {
          type: "settingsRows",
          rows: [
            {
              label: "模型配置",
              desc: "选择团队使用的模型，或自带 Key（BYOK）",
              to: APP_PATHS.more.model,
            },
            {
              label: "AI 记忆",
              desc: "长期记忆总开关——关掉则不再读写记忆",
              to: APP_PATHS.more.memory,
            },
            {
              label: "自主度",
              desc: "团队遇敏感操作时问你多还是少",
              to: APP_PATHS.more.autonomy,
            },
            {
              label: "用量",
              desc: "查看花费与额度",
              to: APP_PATHS.more.usage,
            },
            {
              label: "外观",
              desc: "明暗主题与界面偏好",
              to: APP_PATHS.more.appearance,
            },
            {
              label: "快捷键",
              desc: "常用操作的键盘快捷键",
              to: APP_PATHS.more.shortcuts,
            },
            {
              label: "反馈",
              desc: "提 Bug、功能建议或体验改进",
              to: APP_PATHS.more.feedback,
            },
            {
              label: "关于",
              desc: "版本与产品信息",
              to: APP_PATHS.more.about,
            },
          ],
        },
      ],
    },
    {
      id: MANUAL_SECTION_IDS.reference.faq,
      title: "常见问题",
      icon: "HelpCircle",
      blocks: [
        {
          type: "faq",
          items: [
            {
              q: "为什么没组团？",
              a: [
                {
                  type: "text",
                  text: "CEO 觉得直接答更快。想要多人协作，把任务拆开说——比如「先 A 再 B，同时做 C」。",
                },
              ],
            },
            {
              q: "怎么强制多人干？",
              a: [
                {
                  type: "text",
                  text: [
                    "见「指挥你的团队」· ",
                    {
                      text: "怎么下任务",
                      link: {
                        kind: "jump",
                        to: MANUAL_SECTION_IDS.collaboration.briefing,
                      },
                    },
                    "——并行 / 串行 / 辩论的说法都在那。",
                  ],
                },
              ],
            },
            {
              q: "检查点怎么答？",
              a: [
                {
                  type: "text",
                  text: [
                    "见「指挥你的团队」· ",
                    {
                      text: "检查点与审批",
                      link: {
                        kind: "jump",
                        to: MANUAL_SECTION_IDS.collaboration.checkpoint,
                      },
                    },
                    "——拍板卡、审批放行与计划复核都在那。",
                  ],
                },
              ],
            },
            {
              q: "跑偏了 / 中途想改方向？",
              a: [
                {
                  type: "text",
                  text: [
                    "见「指挥你的团队」· ",
                    {
                      text: "中途接管",
                      link: {
                        kind: "jump",
                        to: MANUAL_SECTION_IDS.collaboration.control,
                      },
                    },
                    "——纠偏、带现场续派、停止，不在这里复述。",
                  ],
                },
              ],
            },
            {
              q: "画布和白板有什么区别？",
              a: [
                {
                  type: "text",
                  text: "画布是对话里的跨回合空间视图——把多轮协作图画在一张可平移的空间上；白板是工具箱里的独立创作工具，用来自由摆元素、读图协作。",
                },
              ],
            },
            {
              q: "费用怎么看？",
              a: [
                {
                  type: "text",
                  text: [
                    {
                      text: "设置 · 用量",
                      link: { kind: "go", to: APP_PATHS.more.usage },
                    },
                    " 里看花费和额度。",
                  ],
                },
              ],
            },
            {
              q: "怎么给产品提意见？",
              a: [
                {
                  type: "text",
                  text: [
                    "去 ",
                    {
                      text: "设置 · 反馈",
                      link: { kind: "go", to: APP_PATHS.more.feedback },
                    },
                    "，选分类、写标题和描述即可。我们会附带当前页面路由（方便定位你在哪），不含工作区里的文件内容。",
                  ],
                },
              ],
            },
            {
              q: "Agent 对 Git / 代码能做什么？",
              a: [
                {
                  type: "text",
                  text: "三类边界，和审批弹窗一致：",
                },
                {
                  type: "boundaryTable",
                  rows: [
                    {
                      can: "读文件；git status / diff / log",
                      approve:
                        "改文件；git add / commit / 建分支 / 切分支；跑代码",
                      wont: "push（含 force push）；reset / rebase；在 main / master 上直接提交",
                    },
                  ],
                },
                {
                  type: "text",
                  text: "推送远端请你在本地终端手动完成——团队只帮你改到可提交的状态。",
                },
              ],
            },
            {
              q: "用的什么模型？",
              a: [
                {
                  type: "text",
                  text: "默认用平台额度跑（内测期平台代付），打开就能用。",
                },
                {
                  type: "text",
                  text: [
                    "想用自己的模型？自带 Key（BYOK）——在 ",
                    {
                      text: "模型配置",
                      link: { kind: "go", to: APP_PATHS.more.model },
                    },
                    " 接 OpenAI / DeepSeek / Kimi / 智谱 / 豆包 / OpenRouter，或填自定义端点；可同时接多家服务商，聊天框里随时切换。每个回合全链路用你选的那一个模型。",
                  ],
                },
              ],
            },
            {
              q: "数据存哪？",
              a: [
                {
                  type: "text",
                  text: "文件在工作区，对话记录在后端。文件页随时看、随时导出。",
                },
              ],
            },
            {
              q: "想了解底层怎么跑的？",
              a: [
                {
                  type: "text",
                  text: [
                    "看 ",
                    {
                      text: "看懂协作（选读）",
                      link: {
                        kind: "go",
                        to: APP_PATHS.toolbox.manual.mechanism,
                      },
                    },
                    "：先看团队跑一遍（活图），再到图例、运行时全景、协作回合、机制场景——全有。",
                  ],
                },
              ],
            },
          ],
        },
      ],
    },
    {
      id: MANUAL_SECTION_IDS.reference.troubleshooting,
      title: "故障排查",
      icon: "LifeBuoy",
      blocks: [
        {
          type: "lead",
          text: "卡住了？对症看这里。",
        },
        {
          type: "faq",
          items: [
            {
              q: "填了 Key 还是报错 / 用不了",
              a: [
                {
                  type: "text",
                  text: [
                    "去 ",
                    {
                      text: "设置 · 模型配置",
                      link: { kind: "go", to: APP_PATHS.more.model },
                    },
                    " 核对 Key、base URL 与模型名是否填对；换一家厂商或自定义端点再试。",
                  ],
                },
              ],
            },
            {
              q: "任务一直转、半天不动",
              a: [
                {
                  type: "text",
                  text: "可能卡在某个队员或外部工具。点停止（界面呈「已停止」）结束本回合，或发消息追问；长任务也能中途打断、下次从断点续跑。",
                },
              ],
            },
            {
              q: "产物找不到 / 没生成文件",
              a: [
                {
                  type: "text",
                  text: "去文件页的工作区看——Agent 创建、修改的文件都落在那里。",
                },
              ],
            },
            {
              q: "费用涨得比预期快",
              a: [
                {
                  type: "text",
                  text: [
                    "复杂任务 = 多队员 + 更强模型 + 深度思考，成本更高。在 ",
                    {
                      text: "设置 · 用量",
                      link: { kind: "go", to: APP_PATHS.more.usage },
                    },
                    " 看明细，必要时换更省的模型或少开深度思考。",
                  ],
                },
              ],
            },
          ],
        },
      ],
    },
    {
      id: MANUAL_SECTION_IDS.reference.privacy,
      title: "数据与隐私",
      icon: "Lock",
      blocks: [
        {
          type: "lead",
          text: "你的东西存在哪、怎么用——讲清楚。",
        },
        {
          type: "bullets",
          items: [
            {
              title: "自带 Key（BYOK）",
              desc: "平台默认已备额度，打开即用；想用自己的模型可自带 API Key（可选升级），在「设置 · 模型配置」里填写与管理。",
            },
            {
              title: "生成的文件",
              desc: "都在工作区，你可在文件页随时查看、编辑、导出。",
            },
            {
              title: "对话记录",
              desc: "保存在后端，用于续聊与记忆；随时可查。正式说明见「设置 · 关于」中的隐私政策。",
            },
            {
              title: "记忆",
              desc: "团队记住的偏好来自你的对话；想改写或清掉，直接说即可。也可在「设置 · AI 记忆」关总开关。",
            },
            {
              title: "反馈附带的上下文",
              desc: "提交反馈时会自动带上当前页面路由（如所在对话），便于复现问题；不含工作区文件内容。",
            },
          ],
        },
        {
          type: "callout",
          variant: "info",
          text: "想带走数据？文件页可导出工作区里的产物。",
        },
      ],
    },
    {
      id: MANUAL_SECTION_IDS.reference.glossary,
      title: "术语",
      icon: "BookMarked",
      blocks: [
        {
          type: "lead",
          text: "手册里常出现的词，一句话一个——与产品术语表对齐。",
        },
        {
          type: "faq",
          items: [
            {
              q: "CEO",
              a: [
                {
                  type: "text",
                  text: "主 Agent——本回合对话 + 按需组团 + 收尾汇报。你只跟它对接；用户才是最终决策者。",
                },
              ],
            },
            {
              q: "队员",
              a: [
                {
                  type: "text",
                  text: "被 CEO 委派干某个子任务的 Agent（worker）；干完即走。中文一律称「队员」。",
                },
              ],
            },
            {
              q: "对话",
              a: [
                {
                  type: "text",
                  text: "你与团队的一通聊天单元（对话页 / 对话列表）。中文一律「对话」，不用「会话」指这层实体。",
                },
              ],
            },
            {
              q: "协作图",
              a: [
                {
                  type: "text",
                  text: "把本次任务的分工、依赖、进度画成的一张实时图。",
                },
              ],
            },
            {
              q: "画布",
              a: [
                {
                  type: "text",
                  text: "对话的跨回合空间视图——多轮协作图累积在一张可平移画布上。≠ 白板。",
                },
              ],
            },
            {
              q: "白板",
              a: [
                {
                  type: "text",
                  text: "工具箱里的独立创作工具（已可用）——自由摆元素、读图协作。≠ 画布。",
                },
              ],
            },
            {
              q: "辩论室",
              a: [
                {
                  type: "text",
                  text: "辩论回合的赛事页呈现——记分牌 + 剧本主列 + 终审舞台；入口为状态条「打开辩论室」或全屏「辩论室」tab。",
                },
              ],
            },
            {
              q: "站队",
              a: [
                {
                  type: "text",
                  text: "辩论记分牌上点选你的倾向——仅你可见，绝不改写 AI 裁决；会话内态，重载即重置。",
                },
              ],
            },
            {
              q: "用户检查点",
              a: [
                {
                  type: "text",
                  text: "团队停下来等你拍板的卡片（问答、计划评审、续跑等）——心智是「团队请示领导」。",
                },
              ],
            },
            {
              q: "放行",
              a: [
                {
                  type: "text",
                  text: "审批门放过敏感操作。界面按钮文案是「允许一次 / 本轮内都允许」。",
                },
              ],
            },
            {
              q: "已停止",
              a: [
                {
                  type: "text",
                  text: "你主动喊停后的状态展示；动作叫「停止」，不用「取消」当 gloss。",
                },
              ],
            },
            {
              q: "重新生成",
              a: [
                {
                  type: "text",
                  text: "从某条用户消息整轮再跑一遍，要个新答案。改了输入再发叫「调整后重发」；传输失败再试叫「重试」。",
                },
              ],
            },
            {
              q: "带现场续派（同人接续）",
              a: [
                {
                  type: "text",
                  text: "唤回刚干完的同一队员，带着完整现场接着改稿或接强相关新任务——不是新队员从零来。",
                },
              ],
            },
            {
              q: "接续链",
              a: [
                {
                  type: "text",
                  text: "协作图上同一现场根的「续 ×N」节点链；状态条可显「接续 N 次」。有接续标记才是同人，无标记的同角色再委派仍是冷启动新人。",
                },
              ],
            },
            {
              q: "自主度",
              a: [
                {
                  type: "text",
                  text: [
                    "你定团队遇敏感操作时问你多还是少——见 ",
                    {
                      text: "设置 · 自主度",
                      link: { kind: "go", to: APP_PATHS.more.autonomy },
                    },
                    "。",
                  ],
                },
              ],
            },
            {
              q: "工作区",
              a: [
                {
                  type: "text",
                  text: "你和团队共享的文件空间；项目即工作区，产物都落在这里。",
                },
              ],
            },
            {
              q: "BYOK",
              a: [
                {
                  type: "text",
                  text: "自带 Key——用你自己的 API Key 调模型。",
                },
              ],
            },
          ],
        },
      ],
    },
  ],
};
