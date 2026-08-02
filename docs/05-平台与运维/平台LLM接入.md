---
status: reference
code: apps/server/agentcore/llm/
related:
  - docs/05-平台与运维/成本配额与计费.md
  - docs/03-AI核心/辩论编排设计.md
skip_if:
  - 不涉及 LLM 上游 / 模型解析 / BYOK
---

# 平台 LLM 接入

> **现状**：目标仍是 `billing_mode=platform`（额度 `quota_*` · ¥10/月·¥10/日 · 台账 **nano-CNY**，无 FX）；**现网可临时 `byok`**（见 [成本配额与计费](/docs/05-平台与运维/成本配额与计费.md) 文首）。**dev 默认仍 BYOK**。本文只记上游接入事实（厂商坑、BYOK 去向、platform 排查）。

## 一、三条上游路径

| 路径 | 何时走 | 上游 |
|---|---|---|
| **BYOK 直连** | 用户配了 OpenAI 兼容服务商 | 用户自带端点（多服务商；典型 DeepSeek） |
| **多厂商 provider 路由** | model 串带 `厂商/` 前缀 | 豆包 / Moonshot / 智谱 等（§四） |
| **platform 平台凭据** | `billing_mode=platform` / 显式 platform | `PLATFORM_*` 三项 |

**BYOK 去向**：每用户多服务商列表（`user_llm_providers`：AES-GCM 密文 key + base_url + 默认模型）；账号/会话选的是**模型组合**（`llm_model_profiles` → `{main, worker?, background?}` 槽，每槽 `(model, origin, provider_id)`）。key **不在 `.env`**。BYOK 且无服务商、又无 platform 回退 → `402 LLM_KEY_REQUIRED`。

## 二、模型与凭据解析

**模型组合**：CRUD `/v1/users/me/llm-model-profiles`；会话只认 `model_profile_id`（null = 账号默认；**活引用**）。系统预置由平台目录 / `PLATFORM_MODELS`（空则 `[PLATFORM_MODEL, PLATFORM_BACKGROUND_MODEL]`）动态投影，稳定 id = `uuid5(…, agentcore:platform-preset:{model_id})`，无硬编码产品 UUID；逻辑默认 = `PLATFORM_MODEL` 对应预置（须在目录内）否则 allowlist 首个。明确不做：质量档矩阵、角色→模型矩阵、输入框双 picker。

`llm/resolve.py` 单点：

- **主对话**：用户 key 优先；无 key 才 platform。
- **后台档**（title/memory/compaction/followups）：**平台优先** + 必过 `enforce_quota`（防白嫖）；平台不可用（配置缺失 **或** 上游 auth 拒绝）才回落用户 BYOK。统一入口 `billing/gate.py::run_background_llm`（`resolve_and_gate_background` 解析 + 一次 auth→BYOK；耗尽 / 两边都失败 → `None`，不 429 主回合）。禁止调用点各自 try/except 拼回落、禁止进程内 auth 熔断缓存。
- **回合内鉴权死短路（甲+乙）**：同一用户回合首次确认真 API Key `LLMAuthError`（不含 `INFERENCE_TOKEN_EXPIRED`）后，`llm/turn_auth_dead.py` 回合级死位短路后续未启动的 LLM（主聊后续轮 / 未开跑 worker / 本回合 chrome）；已在飞可自然失败。**不做**跨回合 TTL 负缓存（丙暂缓）。用户文案 / CTA 按 `credential_source` 分流（BYOK→去设置；平台→改用自己的 Key / 联系管理员）。
- **`platform_billing_selectable`**：仅 `billing_mode=platform` 时可选；BYOK 部署不开放平台代付。
- **Worker 槽**：空 = 跟随主模型；跨 origin 时 `build_turn_router` 注入 extras。Sidecar `cost_role=member` 按 Worker 槽重解析。
- **统一目录** `GET /v1/users/me/models`：键 `(id, origin, provider_id)`；BYOK 行代理发现（禁硬编码清单）；platform 行有补贴才列。

## 三、sidecar 推理代理

桌面本地引擎**不拿 BYOK key**——经服务端出网：`POST /v1/inference/token` 铸 scoped token + 服务端解析 `model`；`POST /v1/inference/v1/chat/completions` 过同一道计费闸后转发。模型以服务端解析为准。→ `api/routes/inference/`；整体 → [双模式工作区](/docs/02-架构/双模式工作区.md)。

**令牌 TTL**：默认 `inference_token_expire_minutes=720`（12h）。桌面在每次 `startTurn` / `resume` **强制续铸**；开跑前若代理仍拒票则清缓存换票再 RPC 一次。代理 401/403 映射为 `INFERENCE_TOKEN_EXPIRED`（可重试、勿引导「去设置 · 服务商」），与 BYOK 的 `LLM_KEY_INVALID` 区分。

## 四、多厂商 provider 路由

`provider/model` 前缀 → `ProviderRouter`（空 key = 不注册）。辩论多凭据 → [辩论编排 §7.5](/docs/03-AI核心/辩论编排设计.md)。

- 带前缀 → 厂商；无前缀 → 默认 DeepSeek BYOK；未注册前缀 → 回退默认、模型名透传。
- **火山方舟**：一把 `ark-…` key + `https://ark.cn-beijing.volces.com/api/v3`；model 必须传**接入点 ID（`ep-…`）或已开通模型 ID**。
- **兼容性铁律**：只发标准 OpenAI 字段，不发 DeepSeek 特有 `thinking` 等（别家网关会 400）。

## 四·附、DeepSeek API 易错约束（BYOK 常用）

官方文档：https://api-docs.deepseek.com。产品路由 / 计费仍以上文为准。以下为**外部 API 约束**（代码里看不出来）：

| 项 | 约束 |
|---|---|
| 模型名 | `deepseek-v4-pro` / `deepseek-v4-flash`；旧名 `deepseek-chat` / `deepseek-reasoner` 已停用 |
| base_url | `https://api.deepseek.com`（兼容 `/v1`） |
| 思考开关 | `extra_body.thinking.type=enabled/disabled`，默认 enabled；AgentCore 只用此开关 |
| 温度坑 | **思考模式下** `temperature`/`top_p`/penalty **静默忽略** |
| 工具调用 | 有 tool call 的回合必须原样回传 `reasoning_content`，否则 400 |
| 其它 | 不支持强制 `tool_choice=required`（probe 遇 400 回退）；无 `developer` role |

**思考开关按角色**：CEO / worker / 单聊 = on；后台 one-shot（title/memory/compaction/followups/file.rewrite）= disabled。无 per-agent 思考强度档。

## 五、platform 模式与故障排查

`billing_mode=platform` 走 `PLATFORM_*`；改三项须重启后端。

**多模型 + 每模型凭据覆盖**（成本 §〇·六 F3）：`PLATFORM_MODELS` allowlist（非空时 `PLATFORM_MODEL` / 后台档须 ∈ 列表，否则启动 fail-fast）；`PLATFORM_MODEL_CREDENTIALS`（JSON `{model → {api_key?, base_url?, upstream_model?}}`）给「一 key 一模型」中转绑独立凭据；可选 `upstream_model` 让目录 id 与上游 id 解耦（如 `glm-5.2-jiu` → 上游仍发 `glm-5.2`；计费 / 目录仍用目录 id）。单点 `platform_llm_credentials(model=…)` + 出站改写 `platform_wire_model`（`PlatformProvider`）。可用性 = 默认 key **或**任一覆盖有 key。缺 curated 价卡的 allowlist id → 不上架。

**排查**：curl 直连 `{PLATFORM_BASE_URL}/chat/completions` 分辨代理 vs 上游；日志 `inference.proxy_upstream_error` / `llm.*`。可选 `SUB2API_ADMIN_*` 探测（非当前上游）。

**本机系统代理**：产品出网 httpx 默认 `trust_env=False`（不继承 `HTTP(S)_PROXY` / `ALL_PROXY`）。用户装 Clash 等把 `ALL_PROXY` 设成 `socks5://…` 时，旧行为会因缺少可选依赖 `socksio` 报「调用失败」；桌面 sidecar 启动时另剥离 SOCKS 类代理环境变量（HTTP 代理保留）。显式应用内代理配置仍可后续加，不靠默吃系统 SOCKS。
