# code-capability vendor（R 真仓快照）

Pinned 开源仓源码树（去 `.git`、无 `node_modules`）+ 每仓 `SOURCE.json`。  
**禁止**评测/CI 现拉 upstream `main`；复现请按各仓 `SOURCE.json` 的 `fetch_url` / tag。

## 布局

```text
vendor/<name>@<sha12>/
  SOURCE.json    # upstream · pin · license · size_gate · install/test 要点
  LICENSE*       # 保留上游许可证
  …              # 剥离后的源码树
```

名单与闸结果见上级 [`../README.md`](../README.md)「R 真仓」表。

## 复现 fetch（维护者本地）

1. 读目标仓 `SOURCE.json` 的 `fetch_url`（GitHub tag tarball）与 `commit`。
2. 解压后删除 `.git` / `.github` / `node_modules` 及 `SOURCE.json` 内 `stripped` 所列目录。
3. 写入/更新 `SOURCE.json`（`fetched_at`、粗计 `size_gate.app_loc_*`）。
4. 可选：仓库根跑 `python evals/code-capability/vendor/_fetch_r0b.py` 批量拉取 V01–V06/V08–V09（**V10 zod 须 pin v3 线**，见脚本内注释；勿默认拉 latest v4）。

闸不过（LOC>15k / 难装 / 无脚本测）→ 同角色换备用池并**显式改 SOURCE**，禁止 silently 换仓。

单仓剥离后仍过大 → 该仓改为「附资产 URL + 本地缓存脚本」写进 `SOURCE.json`（不上 Git LFS，除非另议）。

## 铁律

- 评测只对 **copytree 副本** 写盘；禁止直绑本目录改业务源。
- 依赖装在评测沙箱/临时副本，**不要**把 `node_modules` / venv 写回 vendor。
