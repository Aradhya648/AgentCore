---
status: landed
code: apps/server/agentcore/messaging/
related:
  - docs/05-平台与运维/认证与会话.md
skip_if:
  - 只改 AI 对话（读 03-AI / 04-前端）
---

# 消息 IM（找人）

> **状态**：**P0（人 ↔ 人单聊）✅ + 内测全员群 MVP & 自助管理（退群/静音/置顶/成员面板）& 审核治理 & 富消息（图/文件）✅ 已落地**；**官方号产品公告广播 ✅**（全站唯一 `type=official` + Admin Notice publish → IM）；**P1 在线态（部分）✅**（ChatHub 真在线 + firehose `presence` + REST `online`；桌面单聊绿点/头副标题、群成员绿点/「N 人在线」）；**回复引用 S1 ✅**；**@人/@所有人 S2 ✅**（结构化 mentions + 桌面菜单/高亮/静音弱通知）；⏳ **基础社交原语余项**（撤回与编辑，见 §八）；⏳ 官方号服务推送（任务/审批 deep-link）、P1 余项（已读 UI / 正在输入 / 联系人 / 隐私设置面）、P2 余项（通用建群 + 群审核；人+AI 混合群见远期规划）、多 worker 实时。
>
> **定位**：**对话页 = 找 AI，消息页 = 找人**——复用前端聊天内核 + 实时通道，IM 另开后端表。

→ 见代码 `apps/server/agentcore/messaging/`、`api/routes/messages.py`、`api/routes/realtime.py`；前端 `renderer/services/messaging.ts`、`pages/MessagesPage.tsx`

---

## 一、定位与边界（✅ 已定）

| 决策 | 内容 |
|---|---|
| 双入口分工 | 对话页找 AI（保留），消息页找人（IM 收件箱）。纯 AI 团队群聊归对话页；消息页承载「人 ↔ 人」「官方号」「人 + AI 混合群（远期，见 远期规划 §4.1（详细提案不在公开仓 / 维护者本地））」 |
| 复用边界 | 复用的是**前端组件 + 实时通道**，不是同一张表 |
| 关系模型 | **任意搜人**：按用户名 / ID 精确搜到即可发起，非好友前置；配套隐私 / 反滥用护栏（§五） |
| 实时通道 | **每用户一条 SSE firehose + POST 发送**（§四） |

**被否决**：① 扩 `messages` 加 `sender_user_id` 复用同表——污染 AI 热路径表、跨域耦合 AI 与社交两套演进；改为新开 IM 表。② 起步用 WebSocket——要新传输 + 新鉴权、脱离现有 401 刷新纪律；先用 SSE firehose 复用基建，真成瓶颈再上 WS。

## 二、数据模型（✅ 已落地，5 表）

遵循项目建模约定（UUID 主键、**无 ForeignKey**、`server_default`、按查询维度建索引；见 [`核心接口定义.md` §6.2](/docs/02-架构/核心接口定义.md)）。字段细节 → 见代码 `db/models/chat.py`。

| 表 | 说明 |
|---|---|
| `chats` | IM 会话；`auto_join=true` 标记「新用户默认入群」（内测全员群 + 全站唯一 `type=official` 官方号，见 §七） |
| `chat_members` | 参与者 + 每人会话态；`state=pending` 即陌生人「消息请求」门；`muted`=用户自静音、`muted_by_admin`=管理员禁言（可读不可发）；官方号默认 `pinned`、禁止 leave |
| `chat_messages` | 人向消息；`client_msg_id` 解断网重发去重；`system_card`+`payload` 承载产品公告（`kind=product_notice`）与二期服务 deep-link |
| `user_blocks` | 对称拉黑：断 DM + 双向搜索互隐 |
| `user_directory_settings` | 隐私自决；缺行 = 可被搜到（开放为默认） |

## 三、后端 API（✅ `/v1/messages`）

薄路由委托 `MessagingService`，权限在 service 层。

**关键决策**：**非会话成员一律 404**（IDOR 安全、不泄露存在性）；陌生人首条进 `pending` 消息请求门；发消息先按用户限流。

→ 见代码 `api/routes/messages.py`

## 四、实时通道（✅ 进程内；⏳ 多 worker）

- **传输**：`GET /v1/realtime` 每用户一条长连 SSE firehose（server→client），发送走上面的 POST。鉴权复用 Cookie；此流自带 401→刷新→重连（[认证与会话 §六](/docs/05-平台与运维/认证与会话.md)），前端客户端见 `renderer/services/realtime.ts`（§六）。
- **fan-out**：A 发 → 落库 `chat_messages` → 经 `HubChatEventPublisher`（`messaging/hub.py` 进程内 pub/sub）推送给在线成员的 firehose。
- **多载事件**：这条 firehose 不止 IM 消息——是该用户通用的「跨端 server→client」管线。除 `chat_message` 外，还载 `presence`（用户 `/v1/realtime` 连接数 0↔≥1 时推给**有共同会话**的对端；不入库）、`memory_updated`（记忆整合后由 `memory/consolidation.py` 广播，前端 `realtime.ts` 据此实时补「记忆已更新」卡 / toast）。原 `workspace_promoted` 已随 auto-promote 链路移除（现为「项目即工作区」，见 [双模式工作区 §六](/docs/02-架构/双模式工作区.md)）。**扩展性**：新事件类型只需 `_format_event` 透传 + 前端 `handleFrame` 加一分支，无需新通道。
- **在线态（✅ 基本功能）**：在线 = ChatHub 上该用户 ≥1 条活着的 `/v1/realtime` 订阅（与 admin 同源）。REST 快照：`ChatParticipant.online`（会话列表 dm peer / 群成员面板）；实时：`presence` 事件。桌面呈现：单聊列表绿点 + 头「在线/离线」；群成员绿点 + 头「N 人在线」。不做：正在输入、last_seen、隐身、Redis TTL、手机端。
- **离线补偿**：不另建表，上线时按 `last_read_message_id` 拉 `chat_messages` 增量。
- **多 worker（⏳）**：换 Redis / NATS pub-sub——`ChatEventPublisher` Protocol 已抽象（`events.py`），届时为 seam 局部替换，不动业务逻辑（同限流 / 审批门的多机化路径）。

## 五、隐私与反滥用（✅ 已落地护栏）

开放搜人滥用面大，起步即带默认护栏（实现细节，不改「任意搜人」决策）：

| 护栏 | 处理 |
|---|---|
| 防遍历 | 搜索按**精确**用户名 / ID，不做模糊枚举 |
| 隐私自决 | `discoverable`（可否被搜到）/ `who_can_dm`（anyone / contacts），默认开放 |
| 防骚扰 | 陌生人首条进「消息请求」（`chat_members.state=pending`），对方回信前受限 |
| 拉黑 | `user_blocks` 对称，断 DM + 互隐搜索；共享空间联动：挡新邀请 + 自动拒双方 pending（不自动移除已有成员，见 [双模式工作区 §十一](/docs/02-架构/双模式工作区.md)） |
| 限流 | 发消息复用按用户限流（`conversation/rate_limit.py`） |
| IDOR | → 见 [`认证与会话.md` §八](/docs/05-平台与运维/认证与会话.md) |

## 六、前端 MessagesPage（✅ 已落地）

桌面端「消息」两栏收件箱：复用对话页前端内核 + 实时通道，但走**独立 store / service**，与 AI 对话状态解耦。

**媒体显示路径（✅）**：桌面 cookie 鉴权 / 手机 Bearer `fetch` → `createObjectURL` → `<img>`；气泡用 `thumb_path ?? workspace_path`，lightbox 拉 `workspace_path` 原图；prod CSP `img-src` 显式含 `blob:`（只展示本页已鉴权字节，不放宽第三方远程图）。

→ 见代码 `apps/desktop/src/renderer/pages/MessagesPage.tsx`、`services/messaging.ts`、`stores/messaging.ts`

## 七、余项缺口（⏳）与内测全员群关键决策（✅）

| 项 | 现状 / 缺口 |
|---|---|
| 官方号(C) 推送 | **产品公告 ✅**：Admin `publish` 且 `surface∈{inbox,both}` → 写入全站唯一 `type=official` 会话 1 条共享 `system_card`（`payload.kind=product_notice`），经现有 `chat_message` firehose 扇出；归档/过期不删 IM 历史、不回填。任务完成 / 审批 → 官方号 deep-link **二期 ⏳** |
| P1 | 已读回执 UI、**在线态 ✅（见 §四）** / 正在输入 ⏳（typing 仍待；在线态走 ChatHub 真在线，不入库、无 Redis TTL）、联系人收藏、隐私设置面板；**基础社交原语 → §八** |
| P2 | **人群聊：内测全员群 MVP + 自助管理 + 审核治理 + 富消息（图/文件）✅ 已落地**（`type=group` + `auto_join` 默认进群 + 群线程/发送者名/群标识 + 退群/静音/置顶/成员面板 + 平台 admin 踢人/禁言/公告 + system_card 系统提示 + 图/文件附件复用工作区存储，关键决策见下方）；通用建群 + 群审核仍 ⏳；**人 + AI 混合群**（`@` 唤起 agent → 接 CEO 编排，消息页独有差异化形态）已迁远期规划 → 远期规划 §4.1（详细提案不在公开仓 / 维护者本地） |
| 多 worker 实时 | firehose / pub-sub 上 Redis / NATS（见 §四） |

> **内测全员群关键决策**（首个「人群聊」落地形态）：
>
> | 决策 | 结论与理由 |
> |---|---|
> | 默认进群机制 | `chats.auto_join=true` 标记「新用户默认入群」（迁移建群 + 回填活跃用户、`pinned=true`）；自动入群**只在注册时触发**、登录不重灌——否则退群永远失效（「可退群」语义前提）。被否：单建 `beta_group` 表 / 存 `beta_group_id` 配置（一行配置不值得建表；`auto_join` 列自描述、可扩展、查询直接） |
> | 治理权来源 | 平台 admin（`users.role='admin'`，即创始团队），非群级 `chat_members.role`——内测群无群主、零迁移、前端 `user.role==='admin'` 免扩 schema 门控；群级 `role` 列保留给后续用户自建群。被否：内测群指定群主/群管（多一次成员迁移 + 前端需新增 role 字段） |
> | 禁言存储 | 新列 `chat_members.muted_by_admin`（不复用 `state`，避免污染 accepted/pending 消息请求门）；禁言=可读不可发（send 403），管理员豁免。被否：`state='muted'`（语义混淆） |
> | 系统提示范围 | 只发**公告 + 踢人**（`system_card`，NULL sender=official 居中胶囊）；入群/退群/禁言**不发**全群提示（全员群每次注册自动入群会刷屏；禁言改发言时 403 toast）。禁言端点 `POST .../mute`（toggle） |
> | 群内隐私 | roster 暴露成员显示名（内测社区可接受）；`discoverable=false` 隐身**不掩盖**已在群内身份；群内被拉黑者消息 MVP 仍可见（客户端过滤为后续可选项） |
> | 内测后归宿 | 转放量时该群保留 / 拆主题多群 / 关停 → 见 远期规划 §三（详细提案不在公开仓 / 维护者本地） |

## 八、基础社交原语（⏳ 已确认 · 分阶段落地）

> **目标**：补齐「找人」会话的线程感与可治理性——回复引用、@人/@所有人、撤回与编辑；对齐主流 IM 习惯，优先做透每一档，不与远期 `@agent` 混合群绑死。  
> **现状锚点**：**S1 回复 ✅**；**S2 @ ✅**——结构化 `mentions`（`user` / `everyone`）落库；非成员 422；非平台 admin `@所有人` 403；桌面 composer 菜单 + 高亮 + 静音弱通知。recall / edit **仍无**（S3–S4）。  
> **范围外（本轮不做）**：emoji 反应、转发到他聊、消息搜索全文、置顶单条消息、正在输入/已读 UI（仍归 §七 P1）、`@agent` 接编排（远期）。

### 8.1 关键取舍（已定）

| 决策 | 结论 | 理由 / 行业对齐 |
|---|---|---|
| 回复引用 | 发消息可带 `reply_to_message_id`；服务端校验**同会话且存在**；响应与 firehose 带**轻量引用快照**（发送者显示名 + 正文截断或附件类型标签）；原消息撤回/删除后引用条仍显示快照，文案可标「原消息已撤回」 | 微信/飞书：引用靠快照，避免原消息一撤全链断裂；只回传 id 会逼客户端二次拉取 |
| @人 | 结构化 `mentions[]`（`user_id`，可选 offset）；**禁止**只靠正文正则当真源；被 @ 者必须是本会话成员；composer `@` 弹出本群成员；气泡内高亮 | Slack/Discord：mention 是一等数据，便于未读与通知策略 |
| @所有人 | **做**；内测全员群（`auto_join` / 平台 admin 治理）仅 **平台 admin** 可发；普通成员只能 @具体人。通用自建群落地后可再开「群主可配」 | 全员群无限制 `@所有人` = 骚扰面；对齐 Slack `@channel` 权限门 |
| 静音 × 被 @ | 用户自静音（`muted`）时：被 @（含合法的 @所有人）→ **会话列表角标加强 + 桌面弱通知**（可点进会话）；不弹强模态。管理员禁言（`muted_by_admin`）仍不可发，与通知无关 | 微信：静音仍可被 @ 提醒；全员 @ 用弱通知降打扰 |
| 撤回 | 本人发送后 **2 分钟内**可撤回；平台 admin 可撤群内任意成员消息（治理，不受 2 分钟限）。撤回后气泡变为「xxx 撤回了一条消息」占位，**保留行**（不物理删），引用快照仍可读。`system_card` / 官方号公告：**用户不可撤**；仅平台 admin 可撤治理 | 微信 2 分钟；保留行避免已读游标与引用悬空 |
| 编辑 | 本人文本消息可编辑（**15 分钟内**）；标 `edited_at`；附件消息首期不支持改附件（只能撤了重发）。已撤回不可再编辑 | 飞书/Slack「已编辑」标记；附件改写成本高，首期砍掉 |
| 与对话页 `@` | IM `@` = **人**（及日后 Agent 分区）；对话页 `@` = 附件/路径引用——**两套语义、两套 UI，禁止混用组件当真源** | 术语已分域 |
| 客户端节奏 | 契约与桌面先做透；手机跟渲染与入口，不阻塞桌面验收 | 单契约多端 |

### 8.2 分阶段与验收（慢慢做透）

| 阶段 | 内容 | 验收要点 |
|---|---|---|
| **S1 回复可用化** ✅ | 校验 + 引用快照 API/事件；桌面：回复入口、composer 引用条、气泡引用块、点击滚到原消息 | 跨端收到带快照的回复；非法 `reply_to`（跨会话/不存在）→ **422**；乐观发送与 firehose 一致；快照落库列 `chat_messages.reply_to`（JSONB，冻结 `sender_user_id` / `sender_display_name` / `body_preview`，预览截断 100 字） |
| **S2 @人 + @所有人** ✅ | `mentions` 落库与校验；composer `@` 菜单；高亮；静音弱通知；平台 admin-only `@所有人`（群） | 非 accepted 成员 id → 422；普通成员发 `@所有人` → 403；单聊 everyone → 422；静音用户被 @ 有列表角标 + 弱通知；未读策略不破坏现有 `last_read_*` |
| **S3 撤回** | recall API + firehose 更新；2 分钟窗；admin 治理撤；官方/system_card 规则 | 超时本人撤 → 403；撤后引用仍显示快照；列表预览不露出已撤正文 |
| **S4 编辑** | edit API + `edited_at`；气泡「已编辑」；15 分钟窗 | 附件消息拒编辑；已撤拒编辑；他端实时看到正文替换 |
| **（并行可选）** | §七 P1：正在输入（单聊优先）、已读 UI（单聊） | 不阻塞 S1–S4；typing 不入库 |

### 8.3 契约方向（实现时细化，此处锁语义）

- **发送**：延续 `POST .../messages`，扩展可选 `reply_to_message_id`、`mentions`；`@所有人` 用约定 sentinel（如 `mentions` 含特殊 `user_id` / `kind=everyone`——实现时二选一写进 OpenAPI，禁止魔法字符串散落前端）。
- **变更**：撤回 / 编辑走**独立写接口**（或同资源 PATCH + `action`），经现有 firehose 扇出 `chat_message` 更新帧（或显式 `chat_message_updated`）；客户端按 `message_id` 原地替换，不靠整页重拉。
- **快照**：引用预览字段与消息同生命周期返回；不另建「引用表」。
- **被否**：① 用正文 `@Name` 正则当唯一真相源；② 撤回物理删除行；③ 全员群开放全员 `@所有人`；④ 首期做反应/转发冒充「基础能力」。
