---
name: 2analysis-modeling
description: "数学建模赛题分析与建模设计阶段。训练使用独立候选 G2 Tournament 与自动快照；正式比赛和隔离评测使用 G1–G3，产出兼顾 Reliability 与争奖上限的可实现路线。"
allowed-tools: Bash(*), Read, Write, Edit, Grep, Glob, Agent, WebSearch, WebFetch
---

# 赛题分析与建模设计

## Formal grouped v3 分流

正式模式新 run 默认采用 [两次审批工作流](../_references/GROUPED_GATE_WORKFLOW.md)。先检查 `compliance/HUMAN_GATES.json` 的 schema：3.0 使用该文件的三阶段连续流程，本页以下逐 G1–G6 人工等待/approve 指令仅适用于旧 schema 2.0；数学、结果、页面、AI 披露检查仍执行。不存在 Gate 文件时由入口初始化 grouped v3；training/reference 继续原无人工门禁流程。


## Harness profile 入口

vNext run 开始本阶段前，先用 `_references/harness/scripts/validate_harness_profile.py --stage analysis` 校验 run ledger 指向的当前 `HARNESS_PROFILE(.vN).json` 与冻结的 `ARTIFACT_GOVERNANCE.json`。`training_run` 必须激活 `g2-tournament`，`reference_case_ingestion` 使用 reference profile，不得误走完整 G2/Solver/G5 链。若运行中需要专项知识或特殊模型指南，生成只增不减的新版 profile 后再加载。旧项目没有 profile 时只能按 legacy 运行，并在报告中明确记录该证据缺口。

## 数学建模规范参考

非 evaluation_run 才读取 `../_references/knowledge/INDEX.md` 作为轻量路由表；evaluation_run 只使用冻结题面、结果契约和通用规则，不打开案例检索入口。vNext 只在当前 profile 激活 `knowledge-retrieval` 后，按子问题主问题族和最大风险加载 1–3 张最相关的 active 知识卡；触发条件在分析中才出现时，先生成带 `knowledge_retrieval_required` 的追加 profile。旧项目按 legacy 路由。若索引尚无对应卡，再读取 `../_references/math_modeling_norms.md` 的相关小节。知识卡和旧文件只提供方法与防错依据，不替代本阶段的分析报告结构。

正式赛题无条件先读取 `../_references/knowledge/cards/foundations/problem-rules-first.md`。当届题面、附件、官方更正与专项交付要求优先于所有方法卡、历史获奖论文和社区资料。

每个子问题的候选模型说明应记录实际使用的知识卡 ID；若没有使用知识卡，记录所依据的题面、数据、原始信源或旧知识章节。不得为了展示知识库而机械套用无关模型。

如果项目存在 `compliance/AI_USAGE_LOG.md`，本阶段采纳 AI 对题意、假设、候选模型、核心算法或策略的分析后，必须如实记录对应环节、人工修改和核验方式。不能把这些用途归类成语言润色。

先读取 compliance/CASE_MODE.yaml、artifact tier、`run/MODEL_CAPABILITY_SNAPSHOT.json` 与 `../_references/MODEL_REASONING_ROUTER.md`。training_run/reference_case_ingestion 不运行人工门禁，但使用独立 route ledger；training_run 必须读取 `../_references/G2_TOURNAMENT_SPEC.md` 并执行候选比选。下文“formal mode”统一指 evaluation_run、live_competition 和 release_candidate；它们再读取 `../_references/human_gate_spec.md`，本阶段负责 G1、G2、G3。每个 Gate 任务先完成独立路由生命周期，任务完成后才生成审批包、呈现给用户并等待明确决定。

### G1–G3 推理路由

- G1 formal 默认请求 `high/single`；关键歧义需要更深推理时提高实际 effort。
- G2 training 保持用户当前实际 effort 并请求 `independent_candidates`；formal 默认 `ultra/independent_candidates`。无法取得隔离回执时降级为 `single` 并披露 anchoring 风险。
- G3 formal 默认 `max/single`；training 沿用当前实际 effort。只有确有独立形式化比较价值且运行时可证明时才请求非 single topology。

每次用 `reasoning_route.py assess` 建立任务；只有来自 `reasoning_effort_interface` 的有效设置回执才能 `apply`。请求和实际不同须显式 `--allow-degraded`，不可安全回退则 `block`。任务结束绑定输出并 `reassess`。Gate 批准不参与路由应用；用户拒绝升级时采用透明基线、分段推导、约束回代或小规模精确验算，并在 `STRATEGY_CONTEXT.md` 记录证据限制。

## 必须产出

在当前工作目录的 `reports/` 子目录中创建或更新：

- `reports/ANALYSIS_MODELING_REPORT.md`：
  - 赛题分析、子问题拆解、数据与附件理解、评价标准、关键歧义和假设预检。
  - 变量、符号、模型假设、目标函数、约束条件、求解算法、各子问题实现口径、代码阶段任务清单
- `reports/STRATEGY_CONTEXT.md`：门禁模式记录 G1–G3 决策；参考案例记录自动解释、比选、快照、依据、风险和验证证据。保持紧凑，不复制完整聊天。

不要在本阶段写论文正文，不要生成最终 `paper/`，不要把图表排版任务提前到这里。


## 工作流程


### Step 1: 子问题拆解

formal mode 在本步骤开始前先完成 G1 route 的 assess/apply；该路由只覆盖本次题意解释与拆解任务，不是 G1 批准。任务完成后 complete/reassess，再把 route event 引用写入审批包。

只把题面中明确编号的顶层问题当作子问题，例如“问题一/二/三”“Problem 1/2/3”。不要把小问、背景描述、数据说明、提交要求误当成独立子问题。

在拆解前先建立：

```markdown
## 赛题硬规则清单

| rule_id | 官方位置 | 规则摘要 | 影响范围 | 验证方式 | 证据路径 | 状态 |
| --- | --- | --- | --- | --- | --- | --- |
```

清单必须覆盖题目数量、指定对象、数据/时间/空间范围、单位、评价指标、模型或算法专项要求、约束、禁止事项和交付物。任何自行假设都不能冒充题面规则。官方材料更新时，失效全部受影响门禁和产物。

在 `ANALYSIS_MODELING_REPORT.md` 开头明确写：

根据题目动态调整问题数量

本赛题共 X 个子问题。

每个子问题要说明：

- 输入数据和已知条件。
- 决策变量或预测对象。
- 目标函数或评价指标。
- 约束条件。
- 与其它子问题的依赖关系。
- 绘制哪些图像或表格来展示结果。

### Step 2: 假设敏感性预检

列出关键歧义，不要急着定模型。对影响结果的歧义至少给出两种解释，并用简单验算或逻辑递进判断选择。

必须在 `ANALYSIS_MODELING_REPORT.md` 中包含：

```markdown
## 假设敏感性预检

### 模糊表述及解释
...

### 快速验算与递进性检查
...

### 最终采用的解释
...

### 绘制的图像和对比表格


```

如果某个假设会让后续问题的新增条件没有边际效果，要回头调整解释.

完成题意拆解、歧义对比和关键假设预检后按模式分支：

- training_run：在未暴露解答性材料的 cold-start 中冻结题意解释、替代解释、失败条件与证据路径，生成不可覆盖的自动快照后直接进入 Step 3。
- reference_case_ingestion：依据官方材料、数量验算和递进一致性自动采用证据最强的解释，保留实质性替代解释及失败影响；运行 snapshot_reference_case_stage.py 生成 read 快照后直接进入 Step 3。
- formal mode：生成 G1 审批包与审批前快照并呈现给用户；G1 未明确批准时停止，批准后才记录审批并继续。

所有模式都把选择、依据、风险和证据路径写入 STRATEGY_CONTEXT.md。用户的普通询问不自动改模。

### Step 3: 数据理解与建模路线

候选生成前完成 G2 新 route；training 使用当前实际 effort，formal 请求 `ultra/independent_candidates`。G2 完成后重新评估 G3，不继承上一任务设置。

对每份附件做数据理解：

- 数据来源、文件哈希、行列规模、主键和字段解释。
- 缺失、异常、重复、合并基数、单位和时间/空间口径不一致。
- 可直接用于建模的变量。
- 需要派生的指标及其父字段、公式和单位。

按风险从知识路由中加载题意歧义、数据血缘、缺失/异常或单位缩放卡；不要一次性加载所有卡。数据分析必须为每份输入预留 `dataset_id`，以便代码阶段写入 `results/results.json`。

然后给出总体路线：

```text
题面 -> 数据清洗(EDA) -> 子问题一模型 -> 子问题二模型 -> 。。。。 -> 结果检验 -> 论文展示
```

对每个子问题给出透明基线、候选模型和核心算法路线，说明适用条件、数据要求、复杂度、主要风险与验证办法。先冻结 `PROBLEM_FREEZE.json`；候选按统一 Candidate Schema 独立生成，彼此不可见，尽量覆盖机理、统计/数据驱动、优化/图/动态/随机等不同数学视角。用 `g2_tournament.py build-blind` 生成去身份盲评包，经 Blind Critic 排序后只对关键分歧做小型 prototype，再冻结 route selection。training_run 自动执行 Tournament；reference_case_ingestion 只执行七阶段 cold-start/compare，不误走完整 G2；formal mode 把 Tournament 证据纳入 G2 审批包并在批准前停止。

优化题在合同中预注册最低探索配置：同 evaluator、预算、精度和共同样本组的强基线；至少一组只放开一个结构自由度的消融；嵌套问题把上一级可行解列为下一级 incumbent。候选结果由 `harness/scripts/candidate_registry.py` 登记和晋级，预算或计算口径不一致的高分候选不得混入公平排序。是否采用元启发式、精确法或分区搜索由题型决定，不能把算法名当作完成探索。

批准搜索边界前先测代表性小样，预先写明可自动扩展的范围与成本上限。对可能影响约束/排名的定义做题型适用的退化性质检验；覆盖问题可用平底、交换、贴合、嵌套、裁边界五类例子。具体回执及结构上限触发规则见 [全流程执行补充](../_references/harness/WORKFLOW_UPGRADE.md)。不要把一个案例的分母或固定分区数推广成通用要求。

若分式目标、局部删项或异质设计是核心，优先写出边际外部性项与可验证上界。可用 `harness/scripts/math_search_tools.py` 组织 3–5 个分区的联合搜索；只有穷尽声明的离散域或满足相应全局条件时才给全局 gap，其余明确为启发式改进。复杂度没有超过强基线且不能重复时从路线中删除。

候选必须显式给出 `novelty_source` 和可证伪的 `failure_modes`。创新分与 Reliability 分开；题意、硬约束、泄漏或可实现性失败的路线不得因新颖性获胜。G2 产物保存到 `modeling/g2/`，生成 `ROUTING_BINDING.json`，并用 route ledger、capability snapshot 和 project root 运行 Tournament 校验器；不带路由参数的 legacy 校验结果不能证明独立 topology。

每个子问题同时设计结果契约：预期 `result_id`、名称、单位、指标方向、数据切分、基线、约束、验证、不确定性和对应赛题 `rule_id`。这里只定义接口，不填入尚未计算的数值。

门禁模式的 G2/G3 决策以及参考案例的自动比选/快照结论都要同步压缩到 `STRATEGY_CONTEXT.md`，使后续阶段无需重新加载全部聊天。

### Step 4: 建模报告

formal mode 在固化数学形式、约束和验证计划前完成 G3 新 route。若实际 effort 低于请求，必须以 `degraded` 记录并落实透明基线、分段推导、约束回代或小规模精确验算等回退措施。

在 `ANALYSIS_MODELING_REPORT.md` 中写出可交给代码阶段实现的完整方案，并记录 Reliability 底线、Competition Upside 假设、评委可感知亮点及其原型证据。

每个子问题至少包含：

- 问题目标。
- 符号和变量。
- 模型假设。
- 目标函数。
- 约束条件。
- 求解方法。
- 输入输出。
- 代码实现要点。
- 结果校验方法。

公式要清楚到代码阶段能直接实现。算法描述要包含核心步骤、停止条件、复杂度或可行性说明。

推荐结构：

```markdown
# 建模报告

## 1. 总体建模框架
## 2. 数据处理方案
## 3. 符号说明
## 4. 问题一模型
## 5. 问题二模型
## 6. 问题三模型
    ....
## 7. 灵敏度分析与检验方案
## 8. 代码实现任务清单
## 9. results.json 预期结果契约
```

如果子问题数量不是 3 个，按实际题面调整章节，不要硬凑。

在目标函数、约束、指标方向、训练/验证或求解验证计划都明确后：training_run 冻结 G3 数学契约、失败判据、验证计划和 G2 route selection 哈希并自动继续；reference_case_ingestion 生成 synthesize 前的自动快照并继续知识整理；formal mode 生成 G3 审批包，写明失败判据、约束验证、基线比较和不确定性检查，G3 未批准时停止。

### Step 5: 给代码阶段的接口

training_run 先验证 Problem Freeze、候选输出与 topology receipt、Blind Critic、prototype、route selection 和 `ROUTING_BINDING.json`，且活动目录不得存在 `compliance/HUMAN_GATES.json`；通过后生成完整求解接口。reference_case_ingestion 验证 cold_start/compare、来源顺序和论文暴露状态后生成整理接口。formal mode 还要先运行人工门禁校验，只有返回 `RESULT: PASS` 才能生成正式代码接口：

```bash
python <本仓库实际路径>/_references/scripts/human_gate.py verify \
  --file compliance/HUMAN_GATES.json \
  --project-root . \
  --require G1 G2 G3 \
  --check-artifacts
```

在 `ANALYSIS_MODELING_REPORT.md` 末尾写一个“代码实现任务清单”，格式如下：

```markdown
## 代码实现任务清单

| 任务 | dataset_id | 预期 result_id/单位 | 基线 | 方法 | 约束/验证 | rule_id |
| --- | --- | --- | --- | --- | --- | --- |
| 问题一 | ... | ... | ... | ... | ... | ... |
| 问题二 | ... | ... | ... | ... | ... | ... |
```

代码阶段必须按 `_references/knowledge/schemas/results.schema.json` 生成 `results/results.json`。接口中不得预填虚构指标，只约定稳定 ID、单位、方向和证据要求。


## 质量要求

- 所有结论都能回到题面或数据。
- 不编造数据字段和数值。
- 不跳过歧义分析。
- 模型既要有数学表达，也要能被代码实现。
- 若数据不足或题面不清，要明确记录风险和替代方案。
- training_run/reference_case_ingestion 的输入或解释发生实质变化时生成新版本和新自动快照，不覆盖旧版本；其中 training_run 重新执行受影响的 Tournament 或数学契约冻结。formal mode 则标记最早受影响的 G1/G2/G3 为 `invalidated` 并重新审批。

## vNext 运行边界

evaluation_run 禁止训练选题、来源学习和案例知识卡检索；只读取冻结规则、结果契约和通用防错规范。不得绕过 profile 以“固定必读卡”加载案例答案。
