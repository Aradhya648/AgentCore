# R4 冻结基线（回归棘轮）

权威来源：无 LLM 硬验收报告 `r{1,2,3}_baseline_latest.json`（R0 无矩阵报告，不设冻结文件）。

| 文件 | 分册 | 对比口径 |
|------|------|----------|
| [`r1.json`](r1.json) | Find/Fix | `summary.pass / summary.matrix_cells` |
| [`r2.json`](r2.json) | Extend | 同上 |
| [`r3.json`](r3.json) | Collab 硬 | 同上（`collab_diagnostics` 软字段不进 pass_rate） |

棘轮：**相对基线 pass_rate 回退 >10pp → Fail**（持平/更好 → 绿）。元数据见 [`manifest.json`](manifest.json)。

## 何时允许 `--update-baseline`

仅在以下情况显式 bump（必须带一句话 `--reason`）：

1. **有意改题面/仓 pin/硬 Check**，且对照矩阵预期分数变化；
2. **修复评测 harness 假红/假绿**后，新分数才是真能力；
3. **首次冻结**或人确认「新基线取代旧观察线」。

禁止：为让 CI/本地变绿而静默压低基线；禁止无 `--reason` 的 bump。

```text
python evals/code-capability/r4_regress.py --update-baseline --phase r1 \
  --from reports/r1_baseline_latest.json \
  --reason "V08 换 pin 后对照矩阵仍 100%，刷新冻结副本"
```
