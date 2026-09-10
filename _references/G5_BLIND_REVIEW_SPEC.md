# G5 隔离可靠性与上限评审

## 输入冻结

Solver 完成候选结果后先生成 `EVIDENCE_PACKAGE.json`。只包含原题/规则哈希、假设、数学模型、results.json、关键图表、baseline 与验证证据；不得包含 Solver 的获奖预期、长篇自辩、G2 Critic 意见或其他 Reviewer 结论。

## 两个独立角色

1. `Failure Hunter`：寻找题意、数学、约束、泄漏、过拟合、数值、复现、因果越界和证据链硬错误。
2. `Ceiling Reviewer`：寻找过度保守、结构利用不足、伪创新、弱 baseline、可被更简洁强模型替代以及评委不可感知的亮点。

两者只读取同一 Evidence Package。只有 `dual_review` topology receipt 证明不同 context_id、相同冻结输入和隔离输出时，才可称为相互独立；YAML 自述只能证明 artifact-isolated 协议。Reliability 与 Competition Upside 分开评分；存在未关闭 hard failure 时必须拒绝 `accept`。

## 修复后的追加裁决

Failure Hunter 文件冻结后不改写 finding。Solver 生成新 `SOLVER_RESPONSE.yaml`，Independent Validator 对当前哈希复验，并在 `INDEPENDENT_VALIDATION.yaml` 中记录 `reviewer_role: independent_validator`、稳定 `reviewer_id` 和实际覆盖的 `verified_failure_ids`。确认关闭或重新打开某项 finding 时运行：

```bash
python _references/harness/scripts/g5_disposition.py append \
  --bundle <g5-dir> --project-root . \
  --event-id <unique-id> --finding-id <failure-id> --action closed \
  --reviewer-id <与Independent Validation一致的ID> \
  --verification-scope <实际复验范围> --evidence <证据路径>
```

事件追加到 `FINDING_DISPOSITIONS.jsonl`，绑定原初审、当前回复、当前复验和证据哈希。Decision 的 `disposition_chain_head` 必须等于最新事件哈希，`hard_failures` 必须等于归并后的开放 finding。Solver 身份不能关闭 finding；任一绑定文件变化都会使旧裁决失效。

## 回拨

- `local_fix`：不改变路线的局部修复，回到 G4/结果验证。
- `return_to_g4`：数据、参数、实现或生产运行口径变化。
- `return_to_g2`：当前路线正确但上限明显不足，或存在根本更强的数学结构。

`evaluation_run` / `live_competition` 的 `G5 → G2` 成本较高，必须先明确告知用户范围、代价和回拨点并获得批准；训练模式可按预注册最大回拨次数自动执行。任何回拨都失效受影响的 Gate/快照，不能覆盖旧证据。

验证器除审查两个角色的隔离与评分来源外，还必须重新计算 Evidence Package 中所有 `path` + `sha256` 外部 artifact 的哈希；只校验评审文件内部哈希而不核对候选结果、图或验证证据，属于硬失败。候选结果应绑定不可变快照，不能指向后续会被独立审计覆盖的可变文件。

验证器：

```bash
python _references/harness/scripts/validate_g5_bundle.py \
  --bundle <g5-dir> \
  --route-ledger run/REASONING_ROUTE_LEDGER.jsonl \
  --capability-snapshot run/MODEL_CAPABILITY_SNAPSHOT.json \
  --project-root .
```

新 run 必须生成 `<g5-dir>/ROUTING_BINDING.json`。不传路由参数仅用于历史兼容，不能给出执行拓扑独立性结论。

## vNext 分责入口

默认继续双评审协议，以保持 architecture 消融的 Baseline 行为。`g5-reliability-gate` 可使用 `validate_g5_bundle.py --reliability-only` 独立阻断硬错误；`g5-blind-upside-review` 使用 `validate_g5_upside.py`，没有批准结果的权限。关闭上限评审仅用于显式预注册消融；ceiling-rescue 保持关闭。新 run 的内容寻址快照、遥测和历史回放参见 [harness/RUNTIME_CONTRACT.md](harness/RUNTIME_CONTRACT.md)。

## grouped v3 的批准边界

G5 双审、Solver Response 与独立复验通过后，路线授权范围内的定稿和材料准备自动继续，不再单独等待人工 G5 批准。改变路线、关键假设、硬约束或越过预算才回到对应差异决策。最终完整交付及多视角终审形成后，请求第二次且最后一次正常人工审批，详见 GROUPED_GATE_WORKFLOW.md。审批次数减少不取消任何 hard failure 阻断。
