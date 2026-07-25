# AgentCore

面向大众的 **Multi-Agent AI 工作台**——真正的 Agent 团队协作，而非「单 Agent + 子任务派发」。

你是老板：定目标、拍板；由 AI CEO 带队的多个 Agent 分工、协商、互审，共同完成复杂任务。协作过程全程可见。

> A multi-agent AI workspace built around real agent-team collaboration.

官网：[fashitianxia.xyz](https://fashitianxia.xyz)

## 核心能力（速览）

- **多 Agent 团队协作**：CEO 按需 `delegate`、协商、辩论、升级决策——不是父任务硬拆子任务
- **过程可观测**：协作图、阶段卡、检查点、工具与引用可回看
- **双模式工作区**：云端案卷 + 本地目录；桌面 Sidecar 承接本地文件 / 终端 / 预览
- **模型接入灵活**：默认 BYOK；也可走平台网关
- **多端**：桌面（主客户端）、手机 Web / Capacitor、管理后台、可选 AI 小镇观测端

产品心智与品牌 → [`docs/01-产品/产品定位与品牌.md`](docs/01-产品/产品定位与品牌.md)  
术语 → [`docs/01-产品/术语表.md`](docs/01-产品/术语表.md)

## 架构一览

```text
┌─────────────────┐     REST / SSE      ┌──────────────────────────┐
│  apps/desktop   │ ◄─────────────────► │  apps/server (FastAPI)   │
│  Electron+React │   (+ 本地 Sidecar)   │  runtime · LLM · tools   │
└────────┬────────┘                     └────────────┬─────────────┘
         │                                           │
         │ 共享契约                                   │ Postgres / Redis
         ▼                                           ▼
┌─────────────────┐                     ┌──────────────────────────┐
│   packages/     │                     │  deploy/ · 基础设施      │
│ contract / UI   │                     └──────────────────────────┘
└────────┬────────┘
         │
    ┌────┴────┬──────────────┐
    ▼         ▼              ▼
 apps/mobile  apps/admin   apps/town（可选 Unity）
```

权威归属与读序 → [`docs/02-架构/架构地图.md`](docs/02-架构/架构地图.md)  
AI 运行时入口 → [`docs/03-AI核心/运行时总览.md`](docs/03-AI核心/运行时总览.md)  
前端入口 → [`docs/04-前端/前端地图.md`](docs/04-前端/前端地图.md)

## 仓库结构

| 路径 | 说明 |
|------|------|
| [`apps/server`](apps/server/README.md) | FastAPI 后端 · runtime 执行引擎 · LLM 网关 |
| [`apps/desktop`](apps/desktop/README.md) | Electron + React 桌面客户端（主产品面） |
| [`apps/mobile`](apps/mobile/README.md) | 手机 Web / Capacitor |
| [`apps/admin`](apps/admin/README.md) | 运营管理后台 |
| [`apps/town`](apps/town/README.md) | AI 小镇（Unity / AgentTown）观测客户端 |
| [`apps/website`](apps/website/README.md) | 官网 |
| [`apps/promo`](apps/promo/README.md) | 宣传片 / Remotion 素材 |
| `packages/` | 跨端契约与工具包（非业务实现） |
| `docs/` | 设计文档（What / Why）；总入口见下 |
| `deploy/` | Docker Compose、部署脚本与环境模板 |
| `conformance/` | SSE / fold 协议对账向量 |
| `demos/` | 产品磁带录制与可控回放 |
| `evals/` | 能力评估与合成场景 |

更细的目录边界 → [`docs/02-架构/项目结构.md`](docs/02-架构/项目结构.md)

## 文档从哪读

设计文档总入口与**任务路由全表**权威：**[`docs/索引.md`](docs/索引.md)**。跨工具 AI 最短入口：**[`AGENTS.md`](AGENTS.md)**。下表只是常用子集指针，勿与索引抢权威。

| 我要… | 先读 |
|------|------|
| clone 后跑通前后端 | [`本地开发`](docs/02-架构/本地开发.md) |
| 理解分层 / 契约归属 | [`架构地图`](docs/02-架构/架构地图.md) |
| 改 AI 执行 / 编排 / SSE | [`运行时总览`](docs/03-AI核心/运行时总览.md) |
| 改桌面 / 手机 UI | [`前端地图`](docs/04-前端/前端地图.md) |
| 查术语 | [`术语表`](docs/01-产品/术语表.md) |
| 贡献与 PR 自检 | [`CONTRIBUTING.md`](CONTRIBUTING.md) |
| 安全漏洞（勿开公开 Issue） | [`SECURITY.md`](SECURITY.md) |

权威分层：`docs/01`–`05` = What/Why（给人 + AI；⏳ 未落地蓝图以代码与文内短指针为准）；包级 How-to / 命令见各 `apps/*/README`；开发用 AI 细则在本地 `.cursor/rules/`（How，gitignore、**勿** `git add -f`，贡献者可不读）。详细提案 / `docs/06-规划/` **不在公开树**（仅维护者本地）。

## 快速开始

完整步骤（环境变量、账号、Windows 清树重启、小镇等）见 **[`docs/02-架构/本地开发.md`](docs/02-架构/本地开发.md)**。

前置环境（与根 `package.json` `engines` / `packageManager` 对齐）：

- Node.js **22+**
- pnpm **10**（仓库锁定 `pnpm@10.28.1`）
- Python **3.12+**
- [uv](https://docs.astral.sh/uv/)
- Docker & Docker Compose

最短路径概览：

```bash
# 1. 基础设施（Postgres / Redis / SearXNG）
docker compose -f deploy/docker-compose.dev.yml up -d

# 2. 依赖
pnpm install
cd apps/server && uv sync && cd ../..

# 3. 后端（详见本地开发 §2）
cd apps/server
cp .env.example .env   # 生成 ENCRYPTION_KEY 等
uv run alembic upgrade head
uv run python -m agentcore

# 4. 桌面端（另开终端，仓库根）
cp apps/desktop/.env.example apps/desktop/.env.local
pnpm -C apps/desktop dev
```

可选：手机 Web `pnpm -C apps/mobile dev`（`:5175`）；管理后台见 [`apps/admin/README.md`](apps/admin/README.md)。

## 常用开发命令

在**仓库根**执行（细节与范围开关见本地开发「常用命令」）：

| 命令 | 作用 |
|------|------|
| `pnpm gen:types` | OpenAPI / EventType / InteractionKind → 跨端类型 |
| `pnpm conformance` | SSE fold / 投影协议对账（改协议后必跑） |
| `pnpm release:gate` | 与 CI 同构的本地发布门禁 |
| `pnpm test:server:unit` | 后端单元测试（跳过 integration） |
| `pnpm --filter agentcore-desktop test` | 桌面端单元测试 |

改 schema / SSE / fold 后：先 `pnpm gen:types`，再 `pnpm conformance`，勿只 gen 漏对账。

## 开源与贡献

本仓库（[`Lawofall/AgentCore`](https://github.com/Lawofall/AgentCore)）为对外公开的产品 monorepo，许可证 [MIT](./LICENSE)。

- 贡献指南：[CONTRIBUTING.md](./CONTRIBUTING.md)
- 行为准则：[CODE_OF_CONDUCT.md](./CODE_OF_CONDUCT.md)
- 安全报告：[SECURITY.md](./SECURITY.md)（请勿用公开 Issue 报漏洞）

公开切分前的开发历史已私有归档；请对本仓库提 Issue / PR。

## 第三方资产

AgentTown 3D 资产来源、许可与 Mixamo 再分发警示见  
[`apps/town/Assets/TownAssets/README.md`](apps/town/Assets/TownAssets/README.md)。
