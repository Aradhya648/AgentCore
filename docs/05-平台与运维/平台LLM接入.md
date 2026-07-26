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

> **状态**：✅ 现状 = **生产 `platform` 全量代付**（2026-07-21 上线：`billing_mode=platform`、平台模型集 `5.2`+`grok-4.5`、合作中转上游、`PLATFORM_FREE_TIER_ENABLED=false`）+ 多厂商 provider 路由 + sidecar 推理代理 + BYOK 降级为高级选项。**dev 默认仍 BYOK**（`billing_mode=byok`，不破坏本地开发流）；byok 部署下 `PLATFORM_FREE_TIER_ENABLED` 免费档钩子原样保留（§〇·五）。
>
> ✅ **2026-07-20「内测计费翻转」代码落地 · 2026-07-21 生产上线**：platform 路径成为内测主路——`PLATFORM_*` 指向运营配置的平台上游（OpenAI 兼容）、平台模型集 = `PLATFORM_MODELS` 显式 allowlist（空 = 回退单 `platform_model`，byok / 免费档部署零变化）、BYOK 降级高级选项。决策与 as-built → [`成本配额与计费.md` §〇·六](/docs/05-平台与运维/成本配额与计费.md)。
>
> 本文只记「代码看不出来的」上游接入事实（各厂商接入坑、BYOK key 去向）。计费 / 配额口径见 [`成本配额与计费.md`](/docs/05-平台与运维/成本配额与计费.md)。

---

## 一、总览：三条上游路径

内测默认 **BYOK**。一次 LLM 调用的上游经 `llm/resolve.py` 单点决策，走下面三条之一：

| 路径 | 何时走 | 上游 |
|---|---|---|
| **BYOK 直连**（默认主路） | 用户在「设置 · 模型配置」配了一个或多个 OpenAI 兼容服务商 | 用户自带端点（多服务商并存；典型 DeepSeek `deepseek-v4-pro/flash`） |
| **多厂商 provider 路由** | model 串带 `厂商/` 前缀 | 豆包 / Moonshot / 智谱 等（见 §四） |
| **platform 平台凭据** | 免费档 fallback（无 key 用户 ∧ `PLATFORM_FREE_TIER_ENABLED`）/ 用户显式偏好 platform / `billing_mode=platform` 全员代付 | `PLATFORM_*` 三项（免费档 = DeepSeek 官方 `deepseek-v4-flash`） |

> **BYOK 服务商去向**（曾反复踩坑）：每用户自带**多服务商列表**（`user_llm_providers` 表，每行一个端点：label + AES-256-GCM 密文 key + base_url + 该服务商默认模型 + 服务商级价卡 + 连通状态）。账号/会话选的是**模型组合**（`llm_model_profiles` + `users.default_model_profile_id` + `conversations.model_profile_id`），组合展开为 `{main, worker?, background?}` 槽位，每槽 `(model, origin, provider_id)`（`provider_id` 有值=byok；空 + model 有值=platform；Worker/后台空槽 = 跟随主模型）。key **AES 加密存 Postgres**、按 turn 解密注入（`llm/resolve.py::resolve_user_llm_credentials(provider_id=…)` + `security/keys.py`），**不在 `.env`**。BYOK 模式下 `chat` 回合无任何服务商、又无 platform 回退（免费档关闭或平台凭据未配）时返 `402 LLM_KEY_REQUIRED`——须先加 BYOK 服务商（`POST /v1/users/me/llm-providers` 或「设置 · 模型配置」；dev 便利 `scripts/set_dev_llm_key.py`）。旧账号三指针列与会话 `model*` 列已硬切 drop（迁移 `d7a1c4e9f2b8`）。
>
> 计费口径（**per-model origin 路由**（✅ 统一模型目录后取代 per-user `billing_preference`）、免费档 gate fallback、call 级凭据来源算价）→ [`成本配额与计费.md` §〇·五](/docs/05-平台与运维/成本配额与计费.md)。

---

## 二、模型与凭据解析（服务端权威）

**模型组合（✅ 2026-07-25；预置 2026-07-25 收口为两档）**：用户选「一组用法」而非裸模型。CRUD `/v1/users/me/llm-model-profiles`；`PUT …/default` 设账号默认；会话 `PATCH` 只认 `model_profile_id`（null = 跟随账号默认；**活引用**——改组合定义后引用该组合的会话下一 turn 用新展开）。系统预置两档「5.2」/「Grok 4.5」（虚拟 id，main 固定 `origin=platform` + 对应 model id；worker/后台跟随主模型；模型不在平台目录则该档隐藏，expand 回落 5.2）。账号未设默认 → 回落 **5.2** 预置（不跟 `settings.platform_model`）。展开后仍走下方 `resolve_*`；场景 `ProfileParams`（温度/轮数）与模型组合无关。明确不做：质量档矩阵、角色→模型矩阵、输入框双 picker、旧三档启发式/兼容映射。

`llm/resolve.py` 是所有调用点的单一解析入口：

- **`resolve_model_config(purpose)`**：SELECTION/ADVISORY（解析凭据与模型名，授权归 gate）。
  - **主对话（chat）用户 key 优先**；无 key 才落 platform 凭据。
  - **后台档（`title` / `memory` / `compaction` / `followups`）平台优先**（✅ 2026-07-25，对齐 Cursor 等行业「产品壳子走平台」）：有平台凭据即走平台 + **必过 `enforce_quota`**（有 BYOK key 也不跳闸，防白嫖）；平台不可用才回落组合展开的后台槽 / 主模型服务商。调用点经 `billing/gate.py::resolve_and_gate_background`（配额耗尽返回 `None`，best-effort 降级，不 429 主回合）。**历史**：2026-07-13 曾反转为用户 key 优先；内测计费翻转后主路已是平台额度，再翻回平台优先并强制过闸。
  - **平台代付总闸 `platform_billing_selectable`**（`billing/preference.py`）：`billing_mode=platform` 部署恒可选；BYOK 部署仅免费档开启时可选。关闭时目录不列 platform 行、已存 platform 槽静默回落、无 key 用户 resolve 出 `origin=byok` → gate 402 引导配 key。
  - **后台模型降档（✅）**：平台优先路径用 `platform_background_model`（部署级，默认空=跟随 `platform_model`）；仅平台不可用回落时才看组合 `background` 槽（空 = 跟随主模型）。
  - **Worker 槽（✅）**：组合 `worker` 空 = 跟随本 turn 主模型；非空则 `resolve_turn_profiles` 填 `TurnProfiles.model_overrides["agent"]`；跨 origin / 跨服务商时设 `agent_provider_id` 并由 `build_turn_router` 注入 extras。Sidecar 在 `cost_role=member` 时按 Worker 槽重解析；captain / 辩论（`cost_role=arena` + 注入 turn main）仍跟主模型。删 BYOK 服务商时指向它的槽静默失效 → 跟随主模型。
  - **槽位可指平台（✅）**：写组合时 platform 槽须 `platform_billing_selectable` ∧ 模型 ∈ 平台目录。
  - **BYOK 价卡贯穿**：用户自填单价与服务商默认模型随 `LLMCredentials` 解析、经 log context 贯穿到 `calculate_cost`（云管线 `prepare.py` 与推理代理 `proxy.py` 同路），见 [成本配额与计费 §〇·五](/docs/05-平台与运维/成本配额与计费.md)。
- **平台模型常量**：`deepseek-v4-flash` / `deepseek-v4-pro`（`llm/profiles.py`）；`settings.platform_model` 默认 `deepseek-v4-flash`。
- **`resolve_turn_model` / `resolve_conversation_model_selection`**：先经 `LlmModelProfileService.expand` 取会话 `model_profile_id`（否则账号 `default_model_profile_id`，再否则系统 5.2 预置）的 **main** 槽 → `(model, origin, provider_id)`；再兜底 `deepseek-v4-flash`。云端主路经 `conversation/common.py::resolve_turn_profiles`（同函数再叠 Worker 覆盖）；**桌面 sidecar 路**经 `api/routes/inference/proxy.py` 权威重解析（`cost_role=member` 走 Worker 槽）。

**统一模型目录（`llm/catalog.py` · ✅）**：`GET /v1/users/me/models` 返回 `{ current: {id, origin, provider_id}, byok_configured, models[] }`，`(id, origin, provider_id)` 为唯一键。多 BYOK 与平台混排，供**设置页编辑组合槽位**选模型（输入框不再列裸模型）。「来源」是模型属性——原账号级 `billing_preference` 已退役。

- **BYOK 行**：对每个 active 服务商代理 `GET /models` 自动发现（缓存 ~10min；失败降级到已配模型、不 500），`llm/model_metadata.py` 只做美化——**禁止硬编码可选清单替代发现**。
- **platform 行 / keyless**：有补贴 → 仅平台行；无补贴 → `models=[]`，设置页 CTA「接入自己的 Key」。
- **组合 / 槽位授权点**：写组合槽与目录校验走 `validate_model_choice`；会话只校验 `model_profile_id` 归属/存在；resolve 信任已展开槽位。
- **凭据/计费按 origin 路由**：`preflight_llm_credentials(model_origin=…)` 按本回合实际 origin 分叉（byok 不查配额；platform 走过闸）。

---

## 三、sidecar 推理代理（桌面本地引擎的 LLM 出口）

桌面「本地 sidecar 引擎」在用户机上跑回合，但**不把 BYOK key 下发到客户端**——经服务端推理代理出网，由服务端解析真实凭据与模型：

- **`POST /v1/inference/token`**：用 cookie 会话换一枚 **scoped inference token**（限流铸发），响应带 `token` + `expires_in_sec` + **服务端解析出的 `model`**（`resolve_user_chat_model`）。
- **`POST /v1/inference/v1/chat/completions`**：sidecar 用 `Authorization: Bearer <inference-token>` 调用。服务端 `inference_user` 解析用户 → `preflight_llm_credentials`（同一道计费闸：BYOK 有 key 直通、无 key 走免费档 fallback + **per-call** `enforce_quota`，耗尽返 429 `FREE_TIER_EXHAUSTED`）→ `build_provider` 转发（unary / SSE）→ 按 call 级凭据来源落账 `cost_calls` / `cost_events`。
- **模型服务端权威**：sidecar 可能仍发 `settings.platform_model`（如 `deepseek-v4-flash`），但 BYOK 会覆盖为用户自己的 `default_model`——以服务端解析为准（`proxy.py::_llm_request_from_payload`）。

→ 见代码：`api/routes/inference/`（`token.py` 铸发 + `proxy.py` 转发）。sidecar 整体见 [`双模式工作区.md`](/docs/02-架构/双模式工作区.md)。

---

## 四、多厂商 provider 路由（真·多模型辩论 / BYOK）

按 **`provider/model` 前缀路由到不同厂商**（`llm/provider/router.py::ProviderRouter` + `llm/provider/openai_compatible.py::OpenAICompatibleProvider`，`llm/factory.py::build_router` 据已配厂商 key 组装；空 key = 不注册、回退默认，普通对话零行为变化）。这是「真·多模型辩手」（辩论各方各自指定模型）的执行支点；**✅ Phase 3 已启用**（三元组身份 + 辩论回合多凭据 extras），见 [`辩论编排设计.md §7.5`](/docs/03-AI核心/辩论编排设计.md)。

**model 串格式（路由约定）**：

- 带前缀 → 路由到厂商：`doubao/doubao-seed-2-1-turbo-260628`。
- 无前缀 → 默认 provider（DeepSeek BYOK）：`deepseek-v4-pro` / `deepseek-v4-flash`。
- 未注册前缀 → 回退默认 provider，模型名原样透传。

**火山方舟（豆包）接入事实**：

- 一把 key（`ark-...`）+ 同一 OpenAI 兼容端点即可托管多模型（豆包 / DeepSeek-V4 / 智谱 GLM / 通义千问）；`base_url` 默认 `https://ark.cn-beijing.volces.com/api/v3`，key 走 `DOUBAO_API_KEY`（`.env`，不入库）。
- **model 字段必须传【接入点 ID（`ep-…`）或已开通的模型 ID】**——单有 key 点不到模型（与 DeepSeek / Kimi 不同）。
- 已开通 `doubao-seed-2-1-turbo-260628`（**深度思考模型**，答一句烧 ~500 reasoning token → 多轮多辩手偏贵偏慢，心里有数）。Kimi 不在方舟（需单独 Moonshot key）。
- **兼容性铁律**：`OpenAICompatibleProvider` **只发标准字段**（model / messages / stream / temperature / max_tokens / tools），不发 DeepSeek 特有 `thinking` 等推理强度字段（别家网关会 400）；usage 用标准 OpenAI 键、cache 拆分缺失记 0。

**真跑一场多模型辩论（dev 验证配方）**——走正规 `/auth/token` + `/messages`、无旁路：

1. 后端 + 桌面 dev 在跑（`:8000` `readyz` 200）。
2. seed dev 账号：`uv run python scripts/seed_dev_user.py`（`dev` / `devpassword`）。
3. **dev 账号需先有 BYOK DeepSeek key**（见 §一），否则发回合即 `402 LLM_KEY_REQUIRED`。
4. 抓 SSE：`uv run python scripts/probe_turn.py "<诱导 CEO 发起多模型辩论、正方指定 doubao/doubao-seed-2-1-turbo-260628、反方 deepseek-v4-pro 的消息>"` → 事件存 `logs/probes/probe_<ts>.json` 复盘（CEO 是否照传 model 串有不确定性，消息里明确写出各方模型更稳）。

---

## 五、platform 模式与故障排查

`billing_mode=platform` 时全员走 `PLATFORM_*` 三项（OpenAI 兼容端点）；免费档同三项但默认 DeepSeek 官方 flash。改 `PLATFORM_MODEL` / `PLATFORM_BASE_URL` / `PLATFORM_API_KEY` 须重启后端。

**平台目录多模型 + 每模型凭据覆盖**（成本配额与计费 §〇·六 F3）：`PLATFORM_MODELS`（逗号分隔）列出平台目录的多个模型；运营中转「一 key 一模型」时用 `PLATFORM_MODEL_CREDENTIALS`（单行 JSON `{model id → {"api_key"?, "base_url"?}}`）给指定模型绑独立 key / base_url，缺字段回退 `PLATFORM_API_KEY` / `PLATFORM_BASE_URL`，空 = 全部共用默认那把 key。凭据解析单点在 `llm/resolve.py::platform_llm_credentials(model=…)`（命中覆盖表用覆盖 key，否则默认；`build_provider` 对 `source=platform` 建 `PlatformProvider`，**每次请求按 `request.model` 取 key**，故 Router 上单个 `platform/` 前缀即可同时服务 `5.2` 与 `grok-4.5`——辩论 `ensure_debate_route_extras` / Worker extras 同路；计费仍按 `source=platform` 入账）；三个调用点按本回合模型解析——云管线 `conversations/_helpers.py::_preflight_turn_llm`、sidecar `inference/proxy.py`、后台档 `resolve_model_config`（按 purpose 降档后的模型名）。平台可用性判定（gate 503 与 `billing/preference.py::is_platform_available`）= 默认 key **或**任一覆盖条目有 key。改这两个变量同样须重启后端。

**Sub2API（可选诊断）**：配 `SUB2API_ADMIN_*` 后，platform 模式 503 时可自动探测账号状态（`sub2api_probe.py`），**非当前上游**。

进一步定位：curl 直连 OpenAI 兼容端点（`POST {PLATFORM_BASE_URL}/chat/completions` + Bearer）分辨代理层 vs 上游；查日志关键字 `inference.proxy_upstream_error` / `llm.` 上游错误。
