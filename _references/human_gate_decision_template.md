> grouped v3 使用 [路线决策书](gate-templates/route-decision.md)、[中间结果报告](gate-templates/execution-results.md) 和 [最终评审报告](gate-templates/final-review.md)。以下模板只用于旧 v2 单 Gate 审批。

# TODO：Gx 人工审批包（TODO：决策编号）

- 当前状态：`PENDING`
- 本审批通过后解锁：TODO

## 决策范围

TODO：说明本次需要人工决定的事项，接下来会进行的工作，以及明确不在本次审批范围内的事项。

## 输入及版本

| 输入文件或数据 | 版本/摘要 | 与本决策的关系 |
| --- | --- | --- |
| TODO | TODO | TODO |

## 候选方案与备选方案

| 方案 | 核心思路 | 优点 | 风险/代价 | 适用条件 |
| --- | --- | --- | --- | --- |
| 基线方案 | TODO | TODO | TODO | TODO |
| 备选方案 | TODO | TODO | TODO | TODO |

## 推荐方案与依据

TODO：给出推荐，尽量详细。用户可能会对此环节产生质疑，应保持原则并耐心解释。

## 关键假设与风险

- TODO

## 验证计划

- TODO：指标、基线、约束、敏感性或失败判据。

## 回拨点

- TODO：可恢复的文件版本、提交、快照或重跑入口。

## 推理强度路由（独立于审批）

- 路由 task_id / event_id：TODO
- 实际 `model_id` / `reasoning_effort` / `topology`：TODO
- 有界任务范围：TODO
- 请求与实际路由是否一致：TODO：applied / degraded
- effective-setting receipt：TODO
- topology receipt：TODO：`single` 时为不适用；否则给出路径和哈希
- 回退方案与证据限制：TODO
- 证据边界：只有 `reasoning_effort_interface` 回执证明设置生效；Gate 批准不构成路由应用。

## AI 合规分类

- AI 是否参与本审批包：TODO：是/否
- 实际用途类别：TODO
- 采纳与人工核验方式：TODO

> 人工决定必须由用户在看到本审批包后明确给出，并记录到 `compliance/HUMAN_GATES.json`。AI 不得预填“已批准”。Gate 只能引用已完成且已复评的路由事件，不能应用或推定模型设置。
