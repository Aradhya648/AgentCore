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

> **BYOK 服务商去向**（曾反复踩坑）：每用户自带**多服务商列表**（`user_llm_providers` 表，每行一个端点：label + AES-256-GCM 密文 key + base_url + 该服务商默认模型 + 服务商级价卡 + 连通状态），账号级 chat/后台默认各是一对 `(provider_id, model)` 指针（落 `users` 表，可跨服务商），会话覆盖再加 `conversations.model_provider_id` 锁定具体服务商。key **AES 加密存 Postgres**、按 turn 解密注入（`llm/resolve.py::resolve_user_llm_credentials(provider_id=…)` + `security/keys.py`），**不在 `.env`**。BYOK 模式下 `chat` 回合无任何服务商、又无 platform 回退（免费档关闭或平台凭据未配）时返 `402 LLM_KEY_REQUIRED`——新开的 `uv run` / 离线脚本 / `dev` 账号都够不到用户凭据，须先给账号加一个 BYOK 服务商（`POST /v1/users/me/llm-providers` 或桌面「设置 · 模型配置」；dev 便利工具 `scripts/set_dev_llm_key.py`）。
>
> 计费口径（**per-model origin 路由**（✅ 统一模型目录后取代 per-user `billing_preference`）、免费档 gate fallback、call 级凭据来源算价）→ [`成本配额与计费.md` §〇·五](/docs/05-平台与运维/成本配额与计费.md)。

---

## 二、模型与凭据解析（服务端权威）

`llm/resolve.py` 是所有调用点的单一解析入口：

- **`resolve_model_config(purpose)`**：SELECTION/ADVISORY（解析凭据与模型名，授权归 gate）。
  - **一切 purpose 都用户 key 优先**（含后台档 `title` / `memory` / `compaction` / `followups`），无 key 才落 platform 凭据（免费档用户的后台调用因此按来源真实入账、吃免费档额度；都无 → `None` → 402）。**2026-07-13 反转**：原「后台档有 platform 时无条件优先 platform 省钱」在无平台 key 的部署下从未生效过（死代码），而免费档一配平台 key 即激活——BYOK 用户后台调用会翻到平台烧钱、且有 key 跳配额 = 白嫖不设限，并破坏「有 key 用户零变化」承诺，故反转为用户 key 优先。（原「按用户偏好 platform/byok 分叉」已随 `billing_preference` 退役——用户面主对话凭据现按 per-turn origin 走 gate，见下「统一模型目录」。）
  - **平台代付总闸 `platform_billing_selectable`**（`billing/preference.py`）：`billing_mode=platform` 部署恒可选；BYOK 部署仅免费档开启时可选。关闭时目录不列 platform 行、已存 platform 覆盖静默回落账号默认、无 key 用户 resolve 出 `origin=byok` → gate 402 引导配 key（与免费档关闭旧语义逐字节一致）。
  - **后台模型降档（✅ 2026-07-15）**：后台档解析优先账号级**后台默认指针** `(provider_id, model)`（可指向另一个更便宜的服务商，`PUT /users/me/llm-providers/defaults`）→ 未设则跟随 chat 服务商 + `platform_background_model`（部署级，默认空=跟随）→ chat 模型（`_model_for_purpose`）。指针可整体换服务商；未设时只降模型不换凭据。动机：BYOK 用户把 chat `default_model` 配成贵模型时，标题/记忆等后台调用会跟着烧贵模型。
  - **BYOK 价卡贯穿**：用户自填单价（`price_cache_hit/miss/output`）与 `background_model` 随 `LLMCredentials` 解析、经 log context 贯穿到 `calculate_cost` 全部计价点（云管线 `prepare.py` 与推理代理 `proxy.py` 同路），供 BYOK 估算金额（见 [成本配额与计费 §〇·五](/docs/05-平台与运维/成本配额与计费.md)）。
- **平台模型常量**：`deepseek-v4-flash` / `deepseek-v4-pro`（`llm/profiles.py`）；`settings.platform_model` 默认 `deepseek-v4-flash`，仅在 platform 模式作上游模型名（GPT/gpt-4o 平台档已废弃）。
- **`resolve_turn_model` / `resolve_conversation_model_selection`**：解析该 turn 的上游 model。**优先级**：`conversation.(model, model_origin)`（会话覆盖）→ 账号默认（`resolve_account_default_model`：有 key → BYOK `default_model`/byok，否则 `platform_model`/platform）→ 兜底 `deepseek-v4-flash`。会话覆盖仅**主对话 turn** 线程：云端主路经 `conversation/common.py::resolve_turn_profiles`；**桌面 sidecar 路**经 `api/routes/inference/proxy.py` 按 owner 校验后重解析（推理代理对每次代理调用权威重解析，云端单点不足以让桌面生效），worker/辩论回落逻辑不变。**旧数据兜底**：`model` 非空但 `model_origin` NULL → 有服务商视为 byok、否则 platform；origin=byok 且 `model_provider_id` NULL（旧行）→ 保留模型、按账号默认服务商解析；origin=byok 但锁定的服务商已删 / 账号已无服务商 → 覆盖静默失效、回落账号默认（不硬失败；删除服务商同理）。

**统一模型目录（`llm/catalog.py` · ✅ 2026-07-20 取代「模型来源」账号级二分，2026-07-20 升级多服务商）**：`GET /v1/users/me/models` 返回 `{ current: {id, origin, provider_id}, byok_configured, models[] }`，每项含 `origin`（byok|platform）+ `provider_id`/`provider_label`（byok 行）+ 显示名/厂商/能力标签/上下文/单价/`available`，`(id, origin, provider_id)` 为唯一键——**同一 model id 可同时挂在多个服务商下**（各是独立选项）。**多 BYOK 服务商与平台模型混排在同一目录**（每个 active 服务商各自发现模型 + 平台模型集），供前端 `ModelPicker` 按服务商分组渲染。**行业对齐（Cherry Studio / LobeChat / Cursor）：「来源」是模型的属性而非用户预先要做的全局选择**——原 `users.billing_preference` 列、`PUT /users/me/llm-key/billing-preference` 端点、设置页「模型来源」二分卡片均已退役（迁移 drop；顺带消灭「切源后已有会话覆盖不重验」「切源后目录缓存不刷新」两个边界 bug，移动端无需补开关即天然对齐）。

- **BYOK 行**：对**每个 active 服务商**各自代理其端点 OpenAI 标准 `GET /models`（`openai_compatible.py::list_models`）**自动发现**真实模型 id（按 `(provider_id, base_url)` 各测各的、缓存 ~10min；上游失败**优雅降级**到该服务商已配模型、绝不 500），再由 `llm/model_metadata.py` **增强**显示字段——发现决定「有哪些」、元数据只做美化，**禁止硬编码可选清单替代发现**（否则退回两端预设漂移老问题）。
- **platform 行 / keyless 用户**：运营方平台模型集（不打上游）。keyless 分支（`llm/catalog.py`）：**有平台补贴**（`platform_billing_selectable` ∧ 平台凭据可用）→ 目录仅平台行；**无补贴** → `models=[]` 空目录，前端 `ModelPicker` 空态 + 设置·模型配置 CTA（「接入自己的 Key 解锁更多」）。**产品决策**：空目录 + 设置 CTA 是有意 UX——不再塞置灰「配 key 解锁」引导行（旧 `origin=byok, available=false` guide rows 已退役，见 §〇·六 F7）。
- **会话覆盖授权点**：`validate_model_choice`——PATCH `conversations.(model, model_origin, model_provider_id)`（`api/routes/conversations/crud.py`；model 非空时 origin 必填，byok 时 provider_id 随 (id,origin) 一起校验）校验 `(id, origin, provider_id)` ∈ 目录且 `available`，否则 422；resolve 侧信任已存值不重探。
- **凭据/计费按 origin 路由**：`billing/gate.py::preflight_llm_credentials(model_origin=…)` 按**本回合所选模型的 origin** 分叉（byok → 用户 key 不查配额；platform → 平台 key + 免费档限额）——闸语义不变，触发依据从已删的账号偏好换成 per-turn origin。

---

## 三、sidecar 推理代理（桌面本地引擎的 LLM 出口）

桌面「本地 sidecar 引擎」在用户机上跑回合，但**不把 BYOK key 下发到客户端**——经服务端推理代理出网，由服务端解析真实凭据与模型：

- **`POST /v1/inference/token`**：用 cookie 会话换一枚 **scoped inference token**（限流铸发），响应带 `token` + `expires_in_sec` + **服务端解析出的 `model`**（`resolve_user_chat_model`）。
- **`POST /v1/inference/v1/chat/completions`**：sidecar 用 `Authorization: Bearer <inference-token>` 调用。服务端 `inference_user` 解析用户 → `preflight_llm_credentials`（同一道计费闸：BYOK 有 key 直通、无 key 走免费档 fallback + **per-call** `enforce_quota`，耗尽返 429 `FREE_TIER_EXHAUSTED`）→ `build_provider` 转发（unary / SSE）→ 按 call 级凭据来源落账 `cost_calls` / `cost_events`。
- **模型服务端权威**：sidecar 可能仍发 `settings.platform_model`（如 `deepseek-v4-flash`），但 BYOK 会覆盖为用户自己的 `default_model`——以服务端解析为准（`proxy.py::_llm_request_from_payload`）。

→ 见代码：`api/routes/inference/`（`token.py` 铸发 + `proxy.py` 转发）。sidecar 整体见 [`双模式工作区.md`](/docs/02-架构/双模式工作区.md)。

---

## 四、多厂商 provider 路由（真·多模型辩论 / BYOK）

按 **`provider/model` 前缀路由到不同厂商**（`llm/provider/router.py::ProviderRouter` + `llm/provider/openai_compatible.py::OpenAICompatibleProvider`，`llm/factory.py::build_router` 据已配厂商 key 组装；空 key = 不注册、回退默认，普通对话零行为变化）。这是「真·多模型辩手」（辩论各方各自指定模型）的执行支点，见 [`辩论编排设计.md §7.5`](/docs/03-AI核心/辩论编排设计.md)。

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

**平台目录多模型 + 每模型凭据覆盖**（成本配额与计费 §〇·六 F3）：`PLATFORM_MODELS`（逗号分隔）列出平台目录的多个模型；运营中转「一 key 一模型」时用 `PLATFORM_MODEL_CREDENTIALS`（单行 JSON `{model id → {"api_key"?, "base_url"?}}`）给指定模型绑独立 key / base_url，缺字段回退 `PLATFORM_API_KEY` / `PLATFORM_BASE_URL`，空 = 全部共用默认那把 key。凭据解析单点在 `llm/resolve.py::platform_llm_credentials(model=…)`（命中覆盖表用覆盖 key，否则默认；`build_provider` 据此选对上游，计费仍按 `source=platform` 入账）；三个调用点按本回合模型解析——云管线 `conversations/_helpers.py::_preflight_turn_llm`、sidecar `inference/proxy.py`、后台档 `resolve_model_config`（按 purpose 降档后的模型名）。平台可用性判定（gate 503 与 `billing/preference.py::is_platform_available`）= 默认 key **或**任一覆盖条目有 key。改这两个变量同样须重启后端。

**Sub2API（可选诊断）**：配 `SUB2API_ADMIN_*` 后，platform 模式 503 时可自动探测账号状态（`sub2api_probe.py`），**非当前上游**。

进一步定位：curl 直连 OpenAI 兼容端点（`POST {PLATFORM_BASE_URL}/chat/completions` + Bearer）分辨代理层 vs 上游；查日志关键字 `inference.proxy_upstream_error` / `llm.` 上游错误。
