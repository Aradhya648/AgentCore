# AgentCore

面向大众的 Multi-Agent AI 工作台——真正的 Agent 团队协作，而非「单 Agent + 子任务派发」。

> A multi-agent AI workspace built around real agent-team collaboration.

官网：[fashitianxia.xyz](https://fashitianxia.xyz)

## Open source

License: [MIT](./LICENSE). Security reports: [SECURITY.md](./SECURITY.md). Contributions: [CONTRIBUTING.md](./CONTRIBUTING.md).

This repository ([`Lawofall/AgentCore`](https://github.com/Lawofall/AgentCore)) is the public product monorepo under MIT. Development history prior to the public cut is archived privately; please open Issues/PRs against this repository.

## 仓库结构

| 路径 | 说明 |
|------|------|
| `apps/server` | FastAPI 后端 · runtime 执行引擎 · LLM 网关 |
| `apps/desktop` | Electron + React 桌面客户端 |
| `apps/mobile` | 移动端 |
| `apps/admin` | 管理后台 |
| `apps/town` | AI 小镇（Unity / AgentTown） |
| `apps/website` | 官网 |
| `packages/` | 跨端共享契约与工具包 |

更细的目录说明见 [`docs/02-架构/项目结构.md`](docs/02-架构/项目结构.md)。

## 快速开始

完整步骤见 **[`docs/02-架构/本地开发.md`](docs/02-架构/本地开发.md)**。

前置环境（与根 `package.json` `engines` / `packageManager` 对齐）：

- Node.js **22+**
- pnpm **10**（仓库锁定 `pnpm@10.28.1`）
- Python **3.12+**
- [uv](https://docs.astral.sh/uv/)
- Docker & Docker Compose

最短路径概览：

```bash
# 1. 基础设施
docker compose -f deploy/docker-compose.dev.yml up -d

# 2. 依赖
pnpm install
cd apps/server && uv sync && cd ../..

# 3. 按本地开发文档启动后端与桌面端
```

## 第三方资产

AgentTown 3D 资产来源、许可与 Mixamo 再分发警示见
[`apps/town/Assets/TownAssets/README.md`](apps/town/Assets/TownAssets/README.md)。
