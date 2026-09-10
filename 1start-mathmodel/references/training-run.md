# Training Run

用于 2016–2022 完整能力训练。目标是能力增长、异质路线探索与可迁移证据，不运行人工 Gate。

## 启动

公开版不包含训练题库、选择器历史或能力记录。由使用者在仓库外提供训练题目；在 cold-start 前冻结选题理由、输入哈希和暴露状态。不要尝试读取原维护者的训练目录。

默认 Artifact Tier 为 Tier 1；每四个完整训练 case 或 Writer、figure、citation、result binding、document/pagination/metadata 机制变化时升级 Tier 2。风险事件只能升级，不能在同一 run 中降级。

## 必需流程

1. 冻结 `modeling/g2/PROBLEM_FREEZE.json`。
2. 用独立 reasoning route 评估 G2；沿用用户当前实际 effort，请求 `independent_candidates`。运行时无法证明独立拓扑时诚实降级为 `single`。
3. 生成跨范式候选；候选只读取 Problem Freeze，统一 schema 输出，并以 `ROUTING_BINDING.json` 绑定有效设置与拓扑回执。
4. 构建盲 Critic 输入，执行原型竞争并冻结 `ROUTE_SELECTION.yaml`。
5. 实现 Solver，生成 `results/results.json`、验证报告、figures 与语义产物包。
6. 冻结 G5 Evidence Package；用独立 route 执行 Failure Hunter 与 Ceiling Reviewer，之后才汇合 Solver Response 与 Independent Validation。
7. 生成 `paper/paper.md`；Tier 1 不启动 Word loop，也不得声称提交就绪。
8. 每个高价值任务完成后 `reassess`；回拨只执行预注册的有限次数并保留旧分支、原因与成本记录。

G2 保留候选异质性；Reliability 硬错误不可被 Competition Upside 覆盖。高上限路线进入下一阶段前必须绑定下界控制或 fallback。

## 必需产物

```text
compliance/CASE_MODE.yaml
compliance/ARTIFACT_GOVERNANCE.json
modeling/g2/PROBLEM_FREEZE.json
modeling/g2/candidates/
modeling/g2/ROUTE_SELECTION.yaml
review/g5/
results/results.json
reports/ANALYSIS_MODELING_REPORT.md
reports/RESULTS_REPORT.md
reports/VALIDATION_REPORT.md
figures/
paper/paper.md
run/HARNESS_PROFILE.json
run/MODEL_CAPABILITY_SNAPSHOT.json
run/REASONING_ROUTE_LEDGER.jsonl
run/LIGHTWEIGHT_MANIFEST.yaml
```

新 run 的 `LIGHTWEIGHT_MANIFEST.yaml` 使用 schema `1.1`，并以
`harness_profile.path` / `harness_profile.sha256` 绑定当前 profile；历史 `1.0`
清单只作兼容读取，不能作为 vNext profile 已绑定的证据。

不要创建 `compliance/HUMAN_GATES.json`。训练失败由独立路由账本和自动回拨处理；仅在连续失败、状态不可恢复、证据污染或资源预算耗尽时暂停并上报。
