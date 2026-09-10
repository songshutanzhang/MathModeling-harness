# G2 独立候选 Tournament

## 目的

G2 不再只要求“给出若干候选并自评”，而是冻结问题解释后，让不同候选在互不可见条件下形成，按统一 Schema 盲比选，再用小型原型验证关键分歧。稳定基线必须参赛；新颖性不允许覆盖硬错误。

## 触发

- `training_run`：候选数按题目风险、范式空间和实际预算决定，至少 2 条；沿用用户当前实际 effort，不强制抬升到 frontier。
- `reference_case_ingestion`：新案例在 S03 比选中采用；历史已冻结案例保持兼容。
- formal mode：默认请求 `ultra/independent_candidates`；只有 effective-setting receipt 与 distinct-context topology receipt 同时存在时才称为独立候选，否则以 `single` 展平执行并披露非独立性。

## 隔离顺序

```text
PROBLEM_FREEZE.json
→ reasoning route + candidates/*.yaml（拓扑回执证明彼此不可见；single 时不作此声明）
→ BLIND_CRITIC_INPUT.json（删除候选来源与长篇辩护）
→ CRITIC_REVIEW.yaml
→ PROTOTYPE_RESULTS.yaml
→ ROUTE_SELECTION.yaml
```

候选只允许读取题面冻结包、数据剖析冻结包和预先声明的知识卡。不得读取其他候选、Critic 结论或参考论文解答正文。候选声明 `other_candidate_ids_seen: []` 只是内容契约；独立执行还必须由 topology receipt 证明。

## 比选原则

Critic 对匿名标签分别评价：题意/约束正确性、结构利用、可验证性、baseline 强度、预期上限、实现成本和失败模式。任何 `reliability_gate: FAIL` 的路线不能获胜。盲评只决定原型优先级；最终路线必须结合原型结果，不以文字评分直接替代验证。

验证器：

```bash
python _references/harness/scripts/g2_tournament.py build-blind --bundle <g2-dir>
python _references/harness/scripts/g2_tournament.py validate \
  --bundle <g2-dir> \
  --route-ledger run/REASONING_ROUTE_LEDGER.jsonl \
  --capability-snapshot run/MODEL_CAPABILITY_SNAPSHOT.json \
  --project-root .
```

新 run 必须生成 `<g2-dir>/ROUTING_BINDING.json`。不传路由参数的校验只兼容历史 bundle，不证明独立 topology。正式赛/评测集的 G2 仍需人工批准；Tournament 和模型路由都不能替代 Gate。
