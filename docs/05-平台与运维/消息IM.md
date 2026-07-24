---
status: landed
code: apps/server/agentcore/messaging/
related:
  - docs/05-平台与运维/认证与会话.md
skip_if:
  - 只改 AI 对话（读 03-AI / 04-前端）
---

# 消息 IM（找人）

> **状态**：**P0（人 ↔ 人单聊）✅ + 内测全员群 MVP & 自助管理（退群/静音/置顶/成员面板）& 审核治理 & 富消息（图/文件）✅ 已落地**；⏳ 官方号推送、P1（已读 UI / 在线态 / 联系人 / 隐私设置面）、P2 余项（通用建群 + 群审核；人+AI 混合群见远期规划）、多 worker 实时。
>
> **定位**：**对话页 = 找 AI，消息页 = 找人**——复用前端聊天内核 + 实时通道，IM 另开后端表。

→ 见代码 `apps/server/agentcore/messaging/`、`api/routes/messages.py`、`api/routes/realtime.py`；前端 `renderer/services/messaging.ts`、`pages/MessagesPage.tsx`

---

## 一、定位与边界（✅ 已定）

| 决策 | 内容 |
|---|---|
| 双入口分工 | 对话页找 AI（保留），消息页找人（IM 收件箱）。纯 AI 团队群聊归对话页；消息页承载「人 ↔ 人」「官方号」「人 + AI 混合群（远期，见 [`../06-规划/远期规划.md` §4.1](/docs/06-规划/远期规划.md)）」 |
| 复用边界 | 复用的是**前端组件 + 实时通道**，不是同一张表 |
| 关系模型 | **任意搜人**：按用户名 / ID 精确搜到即可发起，非好友前置；配套隐私 / 反滥用护栏（§五） |
| 实时通道 | **每用户一条 SSE firehose + POST 发送**（§四） |

**被否决**：① 扩 `messages` 加 `sender_user_id` 复用同表——污染 AI 热路径表、跨域耦合 AI 与社交两套演进；改为新开 IM 表。② 起步用 WebSocket——要新传输 + 新鉴权、脱离现有 401 刷新纪律；先用 SSE firehose 复用基建，真成瓶颈再上 WS。

## 二、数据模型（✅ 已落地，5 表）

遵循项目建模约定（UUID 主键、**无 ForeignKey**、`server_default`、按查询维度建索引；见 [`核心接口定义.md` §6.2](/docs/02-架构/核心接口定义.md)）。字段细节 → 见代码 `db/models/chat.py`。

| 表 | 说明 |
|---|---|
| `chats` | IM 会话；`auto_join=true` 标记「新用户默认入群」（内测全员群，见 §七） |
| `chat_members` | 参与者 + 每人会话态；`state=pending` 即陌生人「消息请求」门；`muted`=用户自静音、`muted_by_admin`=管理员禁言（可读不可发） |
| `chat_messages` | 人向消息；`client_msg_id` 解断网重发去重；`system_card`+`payload` 承载官方号 deep-link |
| `user_blocks` | 对称拉黑：断 DM + 双向搜索互隐 |
| `user_directory_settings` | 隐私自决；缺行 = 可被搜到（开放为默认） |

## 三、后端 API（✅ `/v1/messages`）

薄路由委托 `MessagingService`，权限在 service 层。

**关键决策**：**非会话成员一律 404**（IDOR 安全、不泄露存在性）；陌生人首条进 `pending` 消息请求门；发消息先按用户限流。

→ 见代码 `api/routes/messages.py`

## 四、实时通道（✅ 进程内；⏳ 多 worker）

- **传输**：`GET /v1/realtime` 每用户一条长连 SSE firehose（server→client），发送走上面的 POST。鉴权复用 Cookie；此流自带 401→刷新→重连（[认证与会话 §六](/docs/05-平台与运维/认证与会话.md)），前端客户端见 `renderer/services/realtime.ts`（§六）。
- **fan-out**：A 发 → 落库 `chat_messages` → 经 `HubChatEventPublisher`（`messaging/hub.py` 进程内 pub/sub）推送给在线成员的 firehose。
- **多载事件**：这条 firehose 不止 IM 消息——是该用户通用的「跨端 server→client」管线。除 `chat_message` 外，还载 `memory_updated`（记忆整合后由 `memory/consolidation.py` 广播，前端 `realtime.ts` 据此实时补「记忆已更新」卡 / toast）。原 `workspace_promoted` 已随 auto-promote 链路移除（现为「项目即工作区」，见 [双模式工作区 §六](/docs/02-架构/双模式工作区.md)）。**扩展性**：新事件类型只需 `_format_event` 透传 + 前端 `handleFrame` 加一分支，无需新通道。
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

→ 见代码 `apps/desktop/src/renderer/pages/MessagesPage.tsx`、`services/messaging.ts`、`stores/messaging.ts`

## 七、余项缺口（⏳）与内测全员群关键决策（✅）

| 项 | 现状 / 缺口 |
|---|---|
| 官方号(C) 推送 | 表 / schema 已留 `type=official`·`sender_type=official`·`system_card`+`payload`；**推送路径（任务完成 / 审批 → 写官方号会话 → deep-link 跳回对话页）业务逻辑未接** |
| P1 | 已读回执 UI、在线态 / 正在输入（走实时通道 + Redis TTL，不入库）、联系人收藏、隐私设置面板 |
| P2 | **人群聊：内测全员群 MVP + 自助管理 + 审核治理 + 富消息（图/文件）✅ 已落地**（`type=group` + `auto_join` 默认进群 + 群线程/发送者名/群标识 + 退群/静音/置顶/成员面板 + 平台 admin 踢人/禁言/公告 + system_card 系统提示 + 图/文件附件复用工作区存储，关键决策见下方）；通用建群 + 群审核仍 ⏳；**人 + AI 混合群**（`@` 唤起 agent → 接 CEO 编排，消息页独有差异化形态）已迁远期规划 → [`../06-规划/远期规划.md` §4.1](/docs/06-规划/远期规划.md) |
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
> | 内测后归宿 | 转放量时该群保留 / 拆主题多群 / 关停 → 见 [`../06-规划/远期规划.md` §三](/docs/06-规划/远期规划.md) |
