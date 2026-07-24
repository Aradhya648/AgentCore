# 宣传片静态资源（BGM 轨）

Remotion 的 `staticFile()` 从本目录（`public/`）解析资源。

## 加 BGM（用户后续自加，见 ../README.md「内容 / 品牌决策」）

1. 把背景音乐放到这里，命名为 **`bgm.mp3`**（或自定名）。
2. 打开 `src/videos/brand-30s/Video.tsx`，把顶部的 `BGM_FILE` 由 `null` 改为 `"bgm.mp3"`。
3. 重新渲染：`pnpm build`（输出 `out/promo.mp4`）。

> 未设置 `BGM_FILE` 时不挂载音轨，渲染不会因缺文件而失败——这是有意的「预留轨」。
> 音量在 `Video.tsx` 的 `<Audio volume={...} />` 调整；如需淡入淡出可加 `@remotion/media-utils` 的音量包络。
