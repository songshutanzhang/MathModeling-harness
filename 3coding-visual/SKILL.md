---
name: 3coding-visual
description: "数学建模编程实现与数据图表生成阶段。根据 ANALYSIS_MODELING_REPORT.md 编写可复现代码、运行求解、验证约束、输出 RESULTS_REPORT.md 并生成论文可用的数据驱动图表 PDF。"
allowed-tools: Bash(*), Read, Write, Edit, Grep, Glob, Agent, WebSearch, WebFetch
---

# 编程实现与数据图表生成

## Formal grouped v3 分流

正式模式新 run 默认采用 [两次审批工作流](../_references/GROUPED_GATE_WORKFLOW.md)。先检查 `compliance/HUMAN_GATES.json` 的 schema：3.0 使用该文件的三阶段连续流程，本页以下逐 G1–G6 人工等待/approve 指令仅适用于旧 schema 2.0；数学、结果、页面、AI 披露检查仍执行。不存在 Gate 文件时由入口初始化 grouped v3；training/reference 继续原无人工门禁流程。


本 skill 承接 `2analysis-modeling`。目标是把 `reports/ANALYSIS_MODELING_REPORT.md` 里的模型和算法落实为可复现程序，跑出可信结果，并生成论文中需要的数据型图表。

vNext run 进入本阶段前，先运行 `_references/harness/scripts/validate_harness_profile.py --stage coding`，要求当前阶段激活 `solver-execution`、`results-contract` 与 `semantic-package`，并核对其 governance 哈希和版本链。若模块未激活，本阶段不得继续；`reference_case_ingestion` 默认不调用本 skill。旧项目缺少 profile 时按 legacy 运行，但必须把缺失记录到验证报告。

## 数学建模规范参考

非 evaluation_run 才读取 `../_references/knowledge/INDEX.md` 作为轻量路由表；evaluation_run 只使用冻结题面、结果契约和通用规则，不打开案例检索入口。vNext 仅在当前 profile 激活 `knowledge-retrieval` 后，根据已批准模型、软件与最大实现风险加载 1–3 张最相关卡；实现阶段才识别出的需求先写入追加 profile。旧项目按 legacy 路由。索引无对应卡时再读取 `../_references/math_modeling_norms.md` 的相关小节。知识卡和旧文件只提供实现与防错依据，不新增固定产物。

本阶段固定加载 `KB-RULE-RESULT-TRACEABILITY`；涉及单位、训练验证、数值迭代、约束或参数扰动时，再从索引加载相应 Wave 1 卡。

`RESULTS_REPORT.md` 应记录实际使用的知识卡 ID、对应检查及结论；知识卡不能替代真实代码测试、约束回代或数据证据。

编码与结果必须逐条兑现 `ANALYSIS_MODELING_REPORT.md` 中的赛题硬规则 `rule_id`。若实现需要偏离当届题面、附件或官方更正，停止并返回分析阶段及人工门禁，不能以软件限制或历史案例为由静默替换。

如果项目存在 `compliance/AI_USAGE_LOG.md`，本阶段采纳 AI 生成或修改的数据处理、算法实现、代码调试、结果解释或作图逻辑后，必须记录用途、采纳范围、人工修改和可复现核验结果。

先读取 execution mode、artifact tier、`run/MODEL_CAPABILITY_SNAPSHOT.json`、`../_references/MODEL_REASONING_ROUTER.md` 与 `../_references/G5_BLIND_REVIEW_SPEC.md`。下文“formal mode”统一指 evaluation_run、live_competition 和 release_candidate；formal mode 再读取 human gate 规范并验证 G1–G3，本阶段负责 G4/G5。training_run 不运行人工 Gate，但保留独立 route ledger、冻结运行口径、Evidence Package、双审和自动回拨；reference_case_ingestion 默认不进入本阶段。

G4 默认 `High`；参数不稳定、不收敛、初始化/随机种子/网格敏感、异常处理改变结果或存在未解释数值异常时建议 `Max`。只有普通调试后仍跨模型、代码和数值层失败，且独立排查有明确价值时才考虑 `Ultra`。G5 使用 `High` 或 `Max`；结果反直觉、证据链复杂、敏感性或不确定性会改变结论时建议 `Max`。完整训练、评测或正式题的中心结论需要独立 Failure Hunter 与 Ceiling Reviewer 时建议 `Ultra`；两个 reviewer 必须只读同一冻结 Evidence Package，彼此不可见。

本阶段同时维护 `reports/STRATEGY_CONTEXT.md` 中的 G4/G5、参数口径、结果解释、验证证据和用户策略问答。保持结论化摘要，不粘贴完整运行日志或聊天。

## 阶段边界

- 本阶段负责：代码、实验运行、结果、结果表、数据驱动图表。
- 本阶段不负责：技术路线图、算法流程图、系统架构图、概念示意图。这些交给 `4drawio`。
- 本阶段不写论文正文，只为 `5writing` 提供可信数值和图表资产。

formal mode 开始前运行：

```bash
python <本仓库实际路径>/_references/scripts/human_gate.py verify \
  --file compliance/HUMAN_GATES.json \
  --project-root . \
  --require G1 G2 G3 \
  --check-artifacts
```

正式模式校验失败时停止。若实现发现模型、目标函数或约束需要改变，formal mode 先失效最早受影响的 G2 或 G3；training_run 则保留当前分支并创建带原因的新版本，自动回拨至 G2 Tournament 或 G3 数学契约。任何模式都不得在代码中静默改变冻结方案。


### Step 1: 代码结构

按 `plan.md` 中"项目目录结构"创建 `code/` 和 `figures/` 骨架，再开始写代码。子问题数不一定是 3，按赛题实际数量调整。


### Step 2: 逐子问题实现

按子问题顺序实现，不要一次性写完不跑。

每个子问题必须完成：

1. 读取所需数据。
2. 实现模型或算法。
3. 验证约束。
4. 输出核心结果。
5. 绘制丰富的图表。
6. 将计算事实写入 `results/results.json`，再在 `reports/RESULTS_REPORT.md` 中按 `result_id` 解释方法、关键数值和校验结果。

生产计算、候选比较和独立数值复验都作为 `run/RUN_PLAN.json` 中的有界任务由 `run_orchestrator.py` 执行。程序写入 `HARNESS_OUTPUT_DIR`；声明输出全部完成后才发布。恢复时先运行 `recover`，仅重做输入、传递源码、依赖输出、配置或运行时身份变化的任务。没有 completed 回执的半成品和仅凭文件存在的缓存都不得复用。

优化类问题必须先保证可行解，再优化目标值。预测类问题必须做训练/验证划分或合理误差评估。评价类问题必须说明指标方向、归一化方法和权重来源。

优化候选用 `candidate_registry.py` 保存晋级表。强基线、结构消融和候选必须共享 evaluator、预算、精度及 sample_group；上一级可行 incumbent 必须进入嵌套问题候选池。最终冻结另用未参与选择的随机状态复验。对于分式目标，显式计算被删项自身损失、对其余项的外部性恢复和剩余硬约束；不要只按单项贡献排序后声称已充分优化。

新候选使用 1.1 回执绑定原始指标、分母/聚合定义、实际评估次数、种子和评价器源码。连续收益且贴着结构上限时，执行一次预授权探针或留下实测停止/超范围决定；仅披露局限不能关闭该项。G5 正确性与剩余机会分开，写作消费节点用 checks 真正调用候选晋级和机会处置验证，格式见 [全流程执行补充](../_references/harness/WORKFLOW_UPGRADE.md)。

允许在隔离输出目录中进行数据剖析、小样本试跑和参数范围探索。在形成正式清洗规则、异常处理、关键参数、随机种子、训练/验证划分和生产运行入口前，为 G4 创建独立 route task，记录有效设置回执。任务完成后 complete/reassess；formal mode 再生成 G4 审批包并呈现给用户。路由完成不是 G4 批准，G4 未明确批准时不得把试跑输出写成最终结果或覆盖已批准口径。

### Step 3: 结果文件格式


AI 在实现、求解和作图过程中，必须把关键中间过程保存成数据并做好记录，例如清洗后的数据摘要、模型参数、迭代历史、约束检查、灵敏度分析过程、图表所用数据和运行日志。中间数据优先保存到 `results/`、`figures/` 或 `code/outputs/`，并登记路径、SHA-256、生成活动和关联 `result_id`。

生产运行必须生成 `results/results.json`，结构遵循 `../_references/knowledge/schemas/results.schema.json`。G5 决策前 `run.status` 和解释性 `claim.status` 保持 `candidate`；training_run 只有在 G5 bundle 校验通过且 G5 Decision 为 `accept` 后才可改为 `approved`，formal mode 还必须取得用户对当前 G5 审批包的明确批准。禁止写入 JSON 非标准的 `NaN` 或 `Infinity`。

候选结果先执行：

```bash
python <本仓库实际路径>/_references/knowledge/scripts/validate_results.py \
  results/results.json --project-root . --check-artifacts
```

`reports/RESULTS_REPORT.md` 推荐结构：

```markdown
# 计算结果

## 运行环境
## 数据读取与预处理
## 问题一结果
## 问题二结果
## 问题三结果
## 灵敏度分析
## 约束与一致性校验
## 与建模报告的一致性说明
## results.json 的 result_id 与证据索引
## 可复现运行方式
```

所有关键数据和图表结果都必须登记在 `results/results.json`，并在 `reports/RESULTS_REPORT.md` 中引用相应 `result_id`。Markdown 报告不能成为与 JSON 并列、需要人工同步的第二数值事实源。

生产运行完成后先冻结 `review/g5/EVIDENCE_PACKAGE.json`，只含原题/规则、假设、数学模型、results、关键图表、baseline 与验证证据，不含 Solver 辩护、G2 Critic 意见或获奖预期。为 G5 创建 route task；Failure Hunter 专查硬错误，Ceiling Reviewer 专查路线保守、伪创新、弱 baseline 与评委不可感知的亮点。只有 `dual_review` topology receipt 才能证明两者来自互不可见上下文；`single` fallback 必须标成有限证据。生成 `ROUTING_BINDING.json`，Solver 响应后由 Independent Validator 验证修复，并用 route ledger、snapshot、project root 运行 `validate_g5_bundle.py`。

Failure Hunter 初审冻结后不覆盖。复验确认 finding 状态变化时，用 `g5_disposition.py` 追加绑定初审、当前 Solver Response、当前 Independent Validation 和具体证据的裁决；只有复验文件明确覆盖该 finding 的 independent validator 才能关闭。Decision 必须绑定最新 chain head 并列出归并后的当前开放项。

formal mode 在上述任务前完成 G5 route 的 assess/apply，输出形成后 complete/reassess，并把双审证据纳入 G5 审批包；未批准时保持草案。training_run 可按预注册最大次数自动 `local_fix`、`return_to_g4` 或 `return_to_g2`，但不能覆盖旧 evidence/review；正式模式的 `G5 → G2` 必须先明确告知成本并取得用户批准。任何 open hard failure 都禁止 accept，Competition Upside 不能覆盖 Reliability FAIL。

Tier 1 还必须生成 `reports/VALIDATION_REPORT.md`、`paper/paper.md` 所需的 semantic artifact package 和 `run/LIGHTWEIGHT_MANIFEST.yaml` 绑定的 results/figures 哈希；不要求 Word/PDF/逐页 PNG。

用户询问参数、算法表现或替代策略时先解释并更新策略上下文；只有明确要求改变数据处理、参数、算法或结论时才修改产物。formal mode 失效最早受影响的 G2–G5；training_run 保留旧版本并按影响范围自动回拨，不伪造人工失效事件。

正式模式 G5 批准后，运行以下校验再固化结果报告：

```bash
python <本仓库实际路径>/_references/scripts/human_gate.py verify \
  --file compliance/HUMAN_GATES.json \
  --project-root . \
  --require G1 G2 G3 G4 G5 \
  --check-artifacts

python <本仓库实际路径>/_references/knowledge/scripts/validate_results.py \
  results/results.json --project-root . --check-artifacts --final
```

### Step 4: 生成数据驱动图表

根据 `reports/ANALYSIS_MODELING_REPORT.md` 和 `reports/RESULTS_REPORT.md` 规划图表，生成 PDF 到 `figures/`。

典型图表：

- 预测类：真实值-预测值对比、误差分布、指标对比。
- 优化类：收敛曲线、成本对比、资源利用率、方案前后对比。
- 评价类：综合得分排序、雷达图、热力图、敏感性曲线。
- 数据理解：分布图、趋势图、相关性图、箱线图。

图表要求：

- PDF 矢量输出，适合论文。
- 不在图内写大标题，标题交给论文 caption（Typst 的 `caption:` 或 LaTeX 的 `\caption{}`）。
- 中文论文图表使用中文坐标轴和图例；英文论文使用英文。
- 不生成流程图/架构图/路线图。

图表可以由主程序或独立脚本生成，不强制固定脚本名。无论采用哪种方式，都必须保存图表对应的数据来源和生成记录。

每张数据图必须作为 `results.json` artifact 登记，包含文件哈希、生成入口和所支持的 `result_id`；没有数值证据关系的装饰性图表不进入论文。

如果冻结的 G4/G5 口径后数据、参数、运行输出或解释发生实质变化，training_run 保留旧 evidence/review 并创建新决策版本；formal mode 保留旧审批包、失效最早受影响门禁并用新决策编号审批。不得仅通过重画图表绕过重新确认。

## vNext 运行边界

evaluation_run 禁止训练选题、来源学习和案例知识卡检索；只读取冻结规则、结果契约和通用防错规范。不得绕过 profile 以“固定必读卡”加载案例答案。

G5 新架构把 `g5-reliability-gate` 与 `g5-blind-upside-review` 分开。默认保留 Baseline 的上限评审；只有预注册消融显式 `--disable-upside-review` 才关闭它。关闭时用 `validate_g5_bundle.py --reliability-only`，响应只绑定 Failure Hunter；开启时继续使用兼容双评审入口并可独立运行 `validate_g5_upside.py`。旧 bundle 不重写。输入隔离只描述可见材料；模型独立性另查运行器回执。ceiling-rescue 不进入执行白名单。

同一输入的跨阶段重复数学检查统一使用 `harness/scripts/validate_once.py`（`--check results|g2|g5`，脚本路径相对于 `_references`）。缓存目录须在 case 外；新 run 以 `--input`、`--source` 绑定完整数学输入和传递源码，验证器及依赖版本始终进入身份。输入变化自动重新执行，失败不复用；未被数值任务声明的论文措辞变化不触发数值重算。最终独立页面重渲染不走缓存。完整参数见运行契约。
