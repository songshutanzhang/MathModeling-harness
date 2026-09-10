# 数学建模 Harness 推理路由规范（vNext）

## 1. 权威边界

推理路由和人工 Gate 是两个状态机：

- `run/REASONING_ROUTE_LEDGER.jsonl` 记录模型、`reasoning_effort`、执行拓扑、生效回执、输出和任务后复评；
- `compliance/HUMAN_GATES.json` 只记录 formal mode 的业务批准、拒绝、修改和失效；
- Gate 只能引用已完成且已复评的路由事件，不能应用模型设置；
- training/reference 不创建 `HUMAN_GATES.json`，但仍使用推理路由账本。

机器状态只使用运行时真实值：`model_id`、`reasoning_effort` 和 `topology`。`High/Max/Ultra` 可用于人类说明，但不得作为机器生效证据，也不得把“模型理论支持”写成“本任务已经生效”。

## 2. 运行时能力快照

每个 run 开始时，从当前产品实际暴露的界面或编排器能力生成 `run/MODEL_CAPABILITY_SNAPSHOT.json`。至少记录：

- 当前 `model_id` 与当前有效 `reasoning_effort`；
- 各模型支持的 effort；
- 是否支持逐任务覆盖、会话中更新和 effective-setting receipt；
- 可证明的 topology 及其最低 effort；
- quota/budget 是否是硬约束。

未知能力写 `unknown` 或不声明；不得推测。用下列命令给快照加自校验哈希：

```bash
python <repo-root>/_references/harness/scripts/reasoning_route.py snapshot-seal \
  --input run/MODEL_CAPABILITY_SNAPSHOT.source.json \
  --output run/MODEL_CAPABILITY_SNAPSHOT.json
```

运行环境、模型或额度策略变化时，开始新 run；不要修改已封存快照。

## grouped v3 推理配置

新 grouped v3 采用“路线较高强度—实装基线—最终 Ultra 多视角”。运行 `grouped_gate.py route-plan --file compliance/HUMAN_GATES.json --project-root . --snapshot run/MODEL_CAPABILITY_SNAPSHOT.json` 读取建议：路线选当前模型可用的 high 以上强度（优先 max/xhigh，Ultra 可用作必要后备），G3/G4 沿用冻结 snapshot.current，G5/G6 请求 ultra 和 dual_review/ensemble。该命令只给建议，不应用设置；用既有 assess 的 --requested-effort/--requested-topology 明确传入，仍须真实 receipt 才可 apply。可用模型不同则按实际能力与预算选择并重新冻结运行配置，不伪造切换。

G5/G6 严格规格无法兑现时保留待审，不自动降级后冒称满足本轮用户要求。普通 Word 导出、文件打包沿用基线，不把整个最终阶段的机械操作都升级到 Ultra。以下默认表用于 legacy v2；grouped 显式请求覆盖表中 G3 max 等默认项。

## 3. 最低充分路由

常规执行沿用当前有效 effort 和 `single` topology。只有高价值、有界任务才提高纵向推理深度或请求独立拓扑：

| 任务 | formal 默认请求 | 说明 |
| --- | --- | --- |
| G1 题意解释 | `high/single` | 关键歧义可提高 effort |
| G2 候选生成 | `ultra/independent_candidates` | 候选必须同源冻结、不同上下文 |
| G2 裁决 | `max/single` | 纵向比较，不伪装独立性 |
| G3 形式化 | `max/single` | 约束、目标与验证计划 |
| G4 实现 | `high/single` | 异常诊断可单独重评 |
| G5 双审 | `ultra/dual_review` | Failure Hunter 与 Ceiling Reviewer 隔离 |
| G5 裁决 | `max/single` | 汇合冻结评审后决策 |
| G6 终审 | `ultra/ensemble` | 仅在真实多视角拓扑可用时成立 |

training_run 不把默认 effort 强行抬到 frontier：使用用户当前实际 effort。G2/G5 仍请求独立拓扑；如果当前能力无法同时兑现，则明确降级为 `single`，降低证据置信度，并保留冻结输入、异质候选、盲评和可靠性门。候选数、G5 复核轮数按问题风险和预算决定，不按固定 token 配额机械裁剪。

## 4. 路由生命周期

每个有界任务严格执行：

```text
assessed → applied | degraded | blocked → completed → reassessed
```

- `assessed`：记录请求与回退方案；
- `applied`：有效回执与请求完全一致；
- `degraded`：有效设置与请求不同，且调用方显式接受保守回退；
- `blocked`：没有安全可行路由；
- `completed`：绑定本任务输出；
- `reassessed`：任务结束后回到当前基线，防止高强度无限继承。

账本为 append-only 哈希链。任何非 `single` 声明都必须另有 topology receipt，证明：共享上下文为 false、各执行单元 context_id 唯一、可见输入哈希相同、隔离输出逐文件绑定。

## 5. 标准命令

评估任务；training 不带 `--gate-id`，formal 必须带：

```bash
python <repo-root>/_references/harness/scripts/reasoning_route.py assess \
  --ledger run/REASONING_ROUTE_LEDGER.jsonl \
  --snapshot run/MODEL_CAPABILITY_SNAPSHOT.json \
  --mode training_run \
  --task-id g2-candidates-v1 \
  --stage analysis \
  --task-class g2_candidate_generation
```

由实际 `reasoning_effort` 接口完成设置后，把接口返回的有效值写入符合 `model_application_receipt.schema.json` 的不可变回执。脚本不替产品切换设置。随后应用回执：

```bash
python <repo-root>/_references/harness/scripts/reasoning_route.py apply \
  --ledger run/REASONING_ROUTE_LEDGER.jsonl \
  --snapshot run/MODEL_CAPABILITY_SNAPSHOT.json \
  --receipt run/route-receipts/g2-model.json \
  --topology-receipt run/route-receipts/g2-topology.json \
  --task-id g2-candidates-v1 \
  --project-root .
```

若实际只能 `single`，使用真实回执并显式加 `--allow-degraded`；不得伪造 topology receipt。任务完成后绑定输出并复评：

```bash
python <repo-root>/_references/harness/scripts/reasoning_route.py complete \
  --ledger run/REASONING_ROUTE_LEDGER.jsonl \
  --task-id g2-candidates-v1 \
  --project-root . \
  --output modeling/g2/ROUTE_SELECTION.yaml

python <repo-root>/_references/harness/scripts/reasoning_route.py reassess \
  --ledger run/REASONING_ROUTE_LEDGER.jsonl \
  --snapshot run/MODEL_CAPABILITY_SNAPSHOT.json \
  --task-id g2-candidates-v1
```

G2/G5 在候选或双审输出形成后生成不可变绑定：

```bash
python <repo-root>/_references/harness/scripts/reasoning_route.py bind \
  --ledger run/REASONING_ROUTE_LEDGER.jsonl \
  --snapshot run/MODEL_CAPABILITY_SNAPSHOT.json \
  --project-root . \
  --task-id g2-candidates-v1 \
  --bundle-kind g2 \
  --frozen-input-sha256 <PROBLEM_FREEZE_SHA256> \
  --output modeling/g2/ROUTING_BINDING.json
```

G2/G5 校验必须传入 route ledger、snapshot 和 project root；否则只允许识别历史 legacy bundle，不能声称 vNext topology 已核验。

最终校验：

```bash
python <repo-root>/_references/harness/scripts/reasoning_route.py validate \
  --ledger run/REASONING_ROUTE_LEDGER.jsonl \
  --snapshot run/MODEL_CAPABILITY_SNAPSHOT.json \
  --project-root . \
  --require-settled
```

## 6. Formal mode 与人工操作

如果当前界面不能由 Harness 直接改变 effort，先记录 `assessed`，再请用户在产品的 reasoning-effort 控件中选择目标值。只有 `source=reasoning_effort_interface` 的有效设置回执可进入 `apply`；聊天中的“已切换”、Gate 批准、模型自述或配置文档都不能替代回执。

无法取得有效回执时：

- 可安全回退：记录真实当前值，并由调用方显式接受 `degraded`；
- 低强度下无法合理保证关键结论：记录 `blocked`，说明原因；
- 用户拒绝升级后不反复催促，采用已经声明的保守路线。

Formal Gate 的 `approve` 还必须引用对应 Gx 的 completed + reassessed 路由事件。旧 `HUMAN_GATES.json` v1 不具备这种证据，不能自动升级为 v2；应保留归档，并对活动版本重新评估、重新展示审批包、重新批准。

## 7. 不变量

- 更高 effort 不是正确性的证据；Reliability FAIL 不得被 Competition Upside 覆盖。
- `single` 中顺序生成多个文件不等于独立候选或双审。
- 路由不能绕过官方规则、来源隔离、数值验证、人工 Gate 或 G6。
- 高 effort 完成后必须复评；相邻任务需要继续使用时，也创建新 task/event。
- 缺少成本遥测时记录 `missing`，不得用文件数或主观感受代替 token、延迟或上下文峰值。
