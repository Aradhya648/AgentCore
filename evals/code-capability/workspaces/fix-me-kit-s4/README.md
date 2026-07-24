# fix-me-kit（P3 试件）

故意带 3 个已知 Bug 的最小 Python CLI，供半真「读仓定位 + 最小修复」。

- 验收：[`GOLDEN.md`](GOLDEN.md)
- 固定 prompt：[`PROMPT.md`](PROMPT.md)

```powershell
python -m pytest -q    # 修复前应 3 failed
python -m fixme --help
```
