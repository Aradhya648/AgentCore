# AgentCore 官网

协作智能平台 AgentCore 的对外官网（单页，纯品牌 + 功能展示）。

## 技术栈

- **Next.js（App Router）** + TypeScript，`output: "export"` 静态导出
- **Tailwind CSS v4**（CSS-first 配置，复用桌面端 OKLCH 品牌 token，hue 255）
- 零运行时后端：构建产物为纯静态文件，可部署到 Vercel / 阿里云 OSS / Nginx

## 本地开发

```bash
pnpm install
pnpm dev      # http://localhost:3000
```

## 构建

```bash
pnpm build    # 产物输出到 out/（静态文件）
```

## 结构

```
src/
  app/
    layout.tsx        # SEO 元信息 + 全局样式
    page.tsx          # 单页：Hero（左文右图 + 协作步骤）/ 痛点 / 能力 / 理念 / 角色 / 对比 / 生态
    globals.css       # 品牌 OKLCH token + 工具类 + 动画
  components/
    CollaborationNetwork.tsx  # Hero 背景协作网络动效（canvas，尊重 reduced-motion）
    HeroFlow.tsx              # Hero 右侧「一次协作」竖向流程图（SVG）
    Reveal.tsx                # 滚动入场封装
```

## 设计依据

文案与定位取自 `docs/01-产品/产品定位与品牌.md`；视觉沿用桌面端品牌色体系（见 `.cursor/rules/color-tokens.mdc`），整体暗色科技调，以「可见的协作网络」为母题。
