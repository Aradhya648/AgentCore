# Town story packs（单一真相源）

AI 小镇 Offline Demo / 后端 `scripted` 路径共用的故事剧本包。

## 编辑

只改本目录的 `demo-story-packs.json`（全量 schema：对白/交易/投票 + Unity 表现字段 + 后端 mood/relation/summary 机制字段）。

然后：

```bash
pnpm gen:story-packs
```

会物化到：

- `apps/town/Assets/StreamingAssets/Fixtures/demo-story-packs.json`（Unity 仍从此路径读；忽略机制字段）
- `apps/server/agentcore/simulation/data/demo-story-packs.json`（随后端包分发；`scripted.py` 运行时读取）

## 校验

```bash
pnpm gen:story-packs:check   # canonical ↔ 两端产物一致
```

CI contracts job 会跑 check，防止再度双维护。
