# 人工审批协议路由

新 formal run 使用 [GROUPED_GATE_WORKFLOW.md](GROUPED_GATE_WORKFLOW.md)：G1–G6 六项技术检查，路线和最终交付两次人工批准，中间结果自动推进；HUMAN_GATES.json schema 3.0。

已有 schema 2.0 使用以下历史六审批协议；不覆盖已有 run，不把旧批准自动迁移。training/reference 无人工 Gate。

---

# 数学建模人工决策门与回拨规范（v2）

## 1. 适用范围与职责

人工 Gate 只在 `evaluation_run`、`live_competition` 和 `release_candidate` 生效。training/reference 不初始化、不运行、不等待 `compliance/HUMAN_GATES.json`。

Gate 负责业务授权：展示选项、记录用户明确决定、锁定输入与回拨点、传播失效。模型与推理强度路由由 `MODEL_REASONING_ROUTER.md` 和 `run/REASONING_ROUTE_LEDGER.jsonl` 独立负责。Gate 不执行路由，也不能把批准解释成模型设置已经改变。

## 2. 门禁顺序

| Gate | 人工审批对象 | 通过后解锁 |
| --- | --- | --- |
| G1 | 题意解释、关键歧义、拆解和关键假设 | 详细模型设计 |
| G2 | 基线、候选模型和核心算法路线 | 固化建模路线 |
| G3 | 目标、约束、指标和验证计划 | 正式编码求解 |
| G4 | 数据口径、关键参数和生产运行 | 最终结果 |
| G5 | 结果解释、结论、敏感性和不确定性 | 定稿论文结论 |
| G6 | 最终论文、AI 声明、支撑材料和清单 | 提交就绪判定 |

依赖固定为 `G1 → G2 → G3 → G4 → G5 → G6`。只有 `approved` 解锁下游；其余状态均停止推进。

## 3. 审批前置条件

批准 Gx 前必须同时满足：

1. 对应有界任务已在独立路由账本中完成，并有任务后 `reassessed` 事件；
2. 有效模型设置由 `reasoning_effort_interface` 回执证明；非 `single` 另有隔离拓扑回执；
3. 审批包已经展示给用户且无占位符；
4. 用户对该 Gate 和该版本给出明确批准，而不是“继续”等笼统表达；
5. 所有上游 Gate 的产物、能力快照和路由引用仍通过哈希复核。

G2 审批包绑定 Problem Freeze、候选、Blind Critic、prototype、route selection 和 `ROUTING_BINDING.json`。G5 绑定 Evidence Package、两份隔离评审、Solver Response、Independent Validation、decision 和路由绑定。无法兑现独立 topology 时必须披露 `single` fallback 及有限置信度。

## 4. 审批包与记录

每个 Gate 使用 `human_gate_decision_template.md` 生成不可覆盖审批包，至少写明：

- 决策范围、解锁动作和不在范围内的事项；
- 输入文件、版本或哈希；
- 基线方案、有效备选、推荐理由、主要风险；
- 验证计划、失败判据和可恢复回拨点；
- 对应路由 task/event、实际 effort/topology、有效设置及隔离回执；
- AI 实际用途和人工核验方式。

批准记录保存匿名授权摘要，不写姓名、学校、学号、指导教师或赛区。AI 不得自行批准、根据沉默推定批准或预填“已批准”。

## 5. 状态与失效

- 输入、题意、关键假设、算法、参数口径、结论、路由回执或审批产物发生实质变化时，失效最早受影响 Gate 及全部下游；
- 不直接编辑 Gate JSON，使用 `invalidate`；
- 要求修改或拒绝也会清除当前决定并失效下游；
- 重新批准前必须重新完成对应路由任务并生成新审批包；
- G5→G2 等高成本回拨先展示成本、失效范围和恢复点，再取得明确授权；
- G6 必须同时锁定最终 DOCX、同源 PDF 和 `FINAL_DELIVERY.json`，任一变化都需重新检查和批准。

旧 schema v1 把路由状态嵌在 Gate 内，不能证明当前 effective setting。不得伪造迁移；保留旧文件作归档，对活动版本新建 v2 并重新完成路由和审批。

## 6. 标准命令

初始化：

```bash
python <repo-root>/_references/scripts/human_gate.py init \
  --file compliance/HUMAN_GATES.json \
  --project-root .
```

路由命令全部由 `reasoning_route.py` 执行。完成对应 route task 并取得用户明确批准后记录 Gate：

```bash
python <repo-root>/_references/scripts/human_gate.py approve \
  --file compliance/HUMAN_GATES.json \
  --project-root . \
  --gate G2 \
  --decision-id D-G2-001 \
  --packet compliance/gates/G2_D-G2-001.md \
  --selected-option "方案 B" \
  --rationale "用户明确给出的选择理由" \
  --verification "基线比较、约束检查和敏感性分析" \
  --rollback-checkpoint reports/ANALYSIS_MODELING_REPORT.pre-G2.md \
  --approval-evidence "当前任务中用户明确批准 G2 方案 B" \
  --ai-involvement yes \
  --ai-category "建模方案辅助分析" \
  --artifact reports/ANALYSIS_MODELING_REPORT.md \
  --route-ledger run/REASONING_ROUTE_LEDGER.jsonl \
  --capability-snapshot run/MODEL_CAPABILITY_SNAPSHOT.json
```

进入下游前验证状态、文件、路由引用和能力快照：

```bash
python <repo-root>/_references/scripts/human_gate.py verify \
  --file compliance/HUMAN_GATES.json \
  --project-root . \
  --require G1 G2 G3 \
  --check-artifacts
```

发生变更：

```bash
python <repo-root>/_references/scripts/human_gate.py invalidate \
  --file compliance/HUMAN_GATES.json \
  --project-root . \
  --gate G2 \
  --trigger upstream_changed \
  --reason "Problem Freeze 已形成新版本"
```

脚本返回非零时不得推进。`HUMAN_GATES.json` 是 append-only 审计状态的派生表示，不得手工修改。
