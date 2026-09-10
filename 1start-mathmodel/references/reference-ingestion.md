# Reference Case Ingestion

只用于历史知识整理，不等同完整训练或正式求解。保持兼容的七阶段链：

```text
01-read → 02-cold-start → 03-compare → 04-learn → 05-backcast → 06-synthesize → 07-card
```

## 边界

- 不创建或等待 `HUMAN_GATES.json`。
- 解答性材料只能在 cold-start 与 compare 冻结后打开。
- 每阶段创建不可覆盖的哈希快照。
- 记录 `00-input/SOURCE_VISIBILITY.yaml`、`audit/SOURCE_EXPOSURE_LEDGER.jsonl` 与 `audit/PROCESS_CHAIN.json`。
- 机器日志为事实源；人类文档只保留阶段结论和污染/改进信息。
- 记录 `run/MODEL_CAPABILITY_SNAPSHOT.json` 与 `run/REASONING_ROUTE_LEDGER.jsonl`；不因没有人工 Gate 而省略实际 effort 证据。
- 若活动 skill 与仓库副本漂移，先修复，不创建案例目录。

## 必需产物

- `CASE_MANIFEST.yaml`
- `compliance/CASE_MODE.yaml`，其中 `human_gates: disabled`
- 七阶段目录及快照
- `reports/ANALYSIS_MODELING_REPORT.md`
- `reports/STRATEGY_CONTEXT.md`
- 必要的 AI 使用事实记录
- `run/HARNESS_PROFILE.json`、`run/MODEL_CAPABILITY_SNAPSHOT.json` 和 `run/REASONING_ROUTE_LEDGER.jsonl`

若后来要把同一题用于正式求解或论文提交，必须创建独立运行上下文并重新启用门禁，不能沿用摄取阶段的自动决策。
