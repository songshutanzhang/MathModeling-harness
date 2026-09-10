# Formal 模式路由

新 formal run 使用 [GROUPED_GATE_WORKFLOW.md](../../_references/GROUPED_GATE_WORKFLOW.md)，由 grouped_gate.py init 初始化 schema 3.0，正常路径只有路线与最终交付两次人工审批。已有 3.0 继续该流程；已有 2.0 才读取以下历史流程。不自动迁移已有批准。

---

# Evaluation / Live Competition / Release Candidate

适用于隔离评测、正式比赛、正式求解与发布候选。固定 Tier 3，启用 G1–G6；Gate 是治理 Checkpoint，不是第二 Solver。

## 启动必读

- `<repo-root>/_references/human_gate_spec.md`
- `<repo-root>/_references/MODEL_REASONING_ROUTER.md`
- `<repo-root>/_references/word_first_writing_workflow.md`
- CUMCM 2026 项目再读 `<repo-root>/_references/cumcm_2026_compliance.md`

若项目没有 `compliance/HUMAN_GATES.json`，运行：

```bash
python <repo-root>/_references/scripts/human_gate.py init \
  --file compliance/HUMAN_GATES.json \
  --project-root .
```

已存在时只运行 `status` 或 `verify`，不得覆盖历史。初始化 Word loop 注册表同理：

```bash
python <repo-root>/5writing/scripts/word_loop.py init \
  --registry paper/revisions/WORD_LOOPS.json \
  --project-root . \
  --working-docx paper/论文_working.docx
```

## 项目事实源

- `plan.md`：模式、用户偏好、阶段责任、风险与预期产物。
- `todo.md`：G1–G6 与各阶段状态。
- `compliance/AI_USAGE_LOG.md`：实际 AI 用途、采纳、修改和人工核验。
- `compliance/HUMAN_GATES.json`：门禁状态、输入哈希和事件链。
- `run/MODEL_CAPABILITY_SNAPSHOT.json`：当前运行时可验证的模型与拓扑能力。
- `run/REASONING_ROUTE_LEDGER.jsonl`：有界任务路由、回执、输出和复评哈希链。
- `compliance/gates/`、`compliance/checkpoints/`：不可覆盖审批包与回拨快照。
- `reports/STRATEGY_CONTEXT.md`：策略问答的紧凑上下文。
- `paper/revisions/WORD_LOOPS.json`：不可覆盖的写作轮次。

主文档固定使用 Word `.docx` 作为唯一可编辑事实源；每个有意义 loop 冻结新 DOCX，PDF/PNG 只由同轮 DOCX 派生。最终交付 DOCX + 同源 PDF。

## Gate 顺序

- G1：题意解释与关键假设。
- G2：候选模型与核心算法。
- G3：目标、约束与验证计划。
- G4：数据处理与生产运行口径。
- G5：结果解释与关键结论。
- G6：最终论文与提交材料。

每个 Gate 对应的有界任务先用 `reasoning_route.py` 完成 assess、有效设置回执、apply/degraded、complete 和 reassess，再生成无占位符审批包并向用户展示。只有用户看到内容后的明确批准才可 `human_gate.py approve`；批准命令必须传入 route ledger 与 capability snapshot。没有 `reasoning_effort_interface` 回执时，不得声称设置已生效。

较早门禁发生实质变化时，用 `human_gate.py invalidate` 失效最早受影响 Gate 及下游状态，不直接编辑 JSON。进入下游阶段前运行 `verify --require ... --check-artifacts`；非零立即停止。

## Tier 3 交付

完整执行 Word、PDF、全部页面 PNG、metadata、manifest、AI disclosure、匿名性、引用、artifact hash 与最终合同。2026 国赛由 `5writing` 生成正文 AI 声明和 `AI工具使用详情.pdf`，由 `6verity` 作为硬门槛验收。
