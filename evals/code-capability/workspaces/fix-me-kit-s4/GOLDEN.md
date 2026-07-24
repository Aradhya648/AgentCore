# P3 fix-me-kit · 黄金验收

> **角色**：B 半真并行专用。仓内已有可运行但**故意错误**的实现；Agent 应最小修复。  
> **并行**：开跑前复制本目录。

## 预埋缺陷（修复前应失败）

| ID | 位置 | 症状 |
|----|------|------|
| B1 | `fixme/mathops.py` · `add` | 误作减法，`add(2,3)` → `-1` |
| B2 | `fixme/greet.py` · `greet` | 名字未标题化且缺逗号，`greet("ada")` → `Hello ada` 而非 `Hello, Ada` |
| B3 | `fixme/cli.py` · `multiply` 子命令 | 参数解析把第二个操作数写死成 `1` |

基线自检（修复前，工作区根）：

```powershell
python -m pytest -q
```

预期：**3 failed**（对应上面三坑）。若不是，先停——试件已漂移。

## 通过标准（全部满足才 Pass）

1. `python -m pytest -q` → **全绿**（退出码 0）。
2. 手工抽检：

```powershell
python -m fixme add 2 3          # → 5
python -m fixme greet ada        # → Hello, Ada
python -m fixme multiply 4 5     # → 20
```

3. **最小修复**：不应删除测试、不应重写整个包、不应引入与三坑无关的大重构（报告里列出 diff 文件列表）。
4. 附 `conversation_id` / `trace_id`。

## 非要求

- 不要求改 CLI 帮助文案风格；不要求加新子命令；不要求 git commit。
