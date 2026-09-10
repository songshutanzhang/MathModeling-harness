# 三档 Artifact Governance

Artifact tier 只决定交付链强度，不降低数学正确性、题面规则、结果追溯或污染隔离要求。

## Tier 1：Training Fast Path

适用于 `training_run` 和新参考案例的高频能力训练。必须保留：

- `results/results.json` 与稳定 `result_id`；
- 核心方程、定义、假设、验证报告和 limitations；
- `figures/` 及生成数据/入口；
- `paper/paper.md`（语义论文，不要求 Word 排版）；
- `run/LIGHTWEIGHT_MANIFEST.yaml`；
- `run/MODEL_CAPABILITY_SNAPSHOT.json` 与 `run/REASONING_ROUTE_LEDGER.jsonl`；
- G2 Tournament、G5 双盲评审和必要的 AI 使用事实。

DOCX、PDF、逐页 PNG、完整 metadata 与正式披露文本可选。Tier 1 不能声称“提交就绪”。历史 `reference_case_ingestion` 若只做知识案例，继续保留七阶段快照产物，不强制追补不存在的完整求解论文；新摄取 run 仍记录 capability snapshot 与 route ledger。下一次实质重跑时升级为 `training_run`。

## Tier 2：Milestone Audit

在 Tier 1 语义产物之上，执行 Word/PDF 同源、逐页渲染、图表清晰度、引用、metadata、manifest 和 AI 披露压力测试。默认每 4 个完整训练 case 至少一次；Writer、figure、citation、result binding、document generation 或 pagination/metadata 机制变化时立即触发。上一次 Tier 2 失败时下一次不得降级。

## Tier 3：Competition / Official Eval

适用于 `evaluation_run`、`live_competition`、release candidate 和最终能力验收。完整执行 Word、PDF、全部页面 PNG、metadata、manifest、AI disclosure、匿名性、引用、artifact hash、最终合同和 G6。不得因额度或时间自动降级。

## 动态解析

```bash
python _references/harness/scripts/resolve_artifact_governance.py \
  --mode training_run --completed-since-tier2 4 \
  --output compliance/ARTIFACT_GOVERNANCE.json
```

输出必须在本次运行开始时冻结。后续风险事件只能向更高 tier 升级，不能在同一 run 中降级。
