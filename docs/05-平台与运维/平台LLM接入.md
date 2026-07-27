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

> **现状**：生产 `billing_mode=platform`（全量代付、`PLATFORM_MODELS` allowlist、合作中转、`PLATFORM_FREE_TIER_ENABLED=false`）；**dev 默认仍 BYOK**。计费 / 配额口径 → [成本配额与计费](/docs/05-平台与运维/成本配额与计费.md)。本文只记上游接入事实（厂商坑、BYOK 去向、platform 排查）。

## 一、三条上游路径

| 路径 | 何时走 | 上游 |
|---|---|---|
| **BYOK 直连** | 用户配了 OpenAI 兼容服务商 | 用户自带端点（多服务商；典型 DeepSeek） |
| **多厂商 provider 路由** | model 串带 `厂商/` 前缀 | 豆包 / Moonshot / 智谱 等（§四） |
| **platform 平台凭据** | 免费档 fallback / 显式 platform / `billing_mode=platform` | `PLATFORM_*` 三项 |

**BYOK 去向**：每用户多服务商列表（`user_llm_providers`：AES-GCM 密文 key + base_url + 默认模型 + 价卡）；账号/会话选的是**模型组合**（`llm_model_profiles` → `{main, worker?, background?}` 槽，每槽 `(model, origin, provider_id)`）。key **不在 `.env`**。BYOK 且无服务商、又无 platform 回退 → `402 LLM_KEY_REQUIRED`。

## 二、模型与凭据解析

**模型组合**：CRUD `/v1/users/me/llm-model-profiles`；会话只认 `model_profile_id`（null = 账号默认；**活引用**）。系统预置「5.2」/「Grok 4.5」（`origin=platform`）；未设默认 → 回落 5.2。明确不做：质量档矩阵、角色→模型矩阵、输入框双 picker。

`llm/resolve.py` 单点：

- **主对话**：用户 key 优先；无 key 才 platform。
- **后台档**（title/memory/compaction/followups）：**平台优先** + 必过 `enforce_quota`（防白嫖）；平台不可用才回落组合后台槽。调用点 `billing/gate.py::resolve_and_gate_background`（耗尽 → `None`，不 429 主回合）。
- **`platform_billing_selectable`**：`billing_mode=platform` 恒可选；BYOK 部署仅免费档开时可选。
- **Worker 槽**：空 = 跟随主模型；跨 origin 时 `build_turn_router` 注入 extras。Sidecar `cost_role=member` 按 Worker 槽重解析。
- **统一目录** `GET /v1/users/me/models`：键 `(id, origin, provider_id)`；BYOK 行代理发现（禁硬编码清单）；platform 行有补贴才列。

## 三、sidecar 推理代理

桌面本地引擎**不拿 BYOK key**——经服务端出网：`POST /v1/inference/token` 铸 scoped token + 服务端解析 `model`；`POST /v1/inference/v1/chat/completions` 过同一道计费闸后转发。模型以服务端解析为准。→ `api/routes/inference/`；整体 → [双模式工作区](/docs/02-架构/双模式工作区.md)。

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

**多模型 + 每模型凭据覆盖**（成本 §〇·六 F3）：`PLATFORM_MODELS` allowlist；`PLATFORM_MODEL_CREDENTIALS`（JSON `{model → {api_key?, base_url?}}`）给「一 key 一模型」中转绑独立凭据；单点 `platform_llm_credentials(model=…)`。可用性 = 默认 key **或**任一覆盖有 key。

**排查**：curl 直连 `{PLATFORM_BASE_URL}/chat/completions` 分辨代理 vs 上游；日志 `inference.proxy_upstream_error` / `llm.*`。可选 `SUB2API_ADMIN_*` 探测（非当前上游）。
