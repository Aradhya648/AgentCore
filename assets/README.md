# 根级品牌素材

仓库根 `assets/` 只放**跨应用、与运行时无关**的品牌资源（图标、Logo 源文件等）。

| 放这里 | 不放这里 |
|--------|----------|
| 安装包 / 官网 / 文档共用的图标 | 各 app 运行时静态资源 → 对应 `apps/*/public/` |
| 设计稿导出的 PNG/SVG 母版 | 小镇 3D 模型与纹理 → [`apps/town/Assets/TownAssets/`](../apps/town/Assets/TownAssets/README.md) |

应用内引用品牌图时，从本目录复制或经构建脚本同步到目标 `public/`，**不要在各 app 各存一份未同步的副本**。
