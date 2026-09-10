---
name: 1start-mathmodel
description: "数学建模工作流入口。按 training、reference ingestion、evaluation 或 live competition 模式解析治理档位，组织 G2/G5、求解、写作与验证。"
allowed-tools: Bash(*), Read, Write, Edit, Grep, Glob, Agent, WebSearch, WebFetch
---

# 数学建模工作流入口

## Formal grouped v3 分流

正式模式新 run 默认采用 [两次审批工作流](../_references/GROUPED_GATE_WORKFLOW.md)。先检查 `compliance/HUMAN_GATES.json` 的 schema：3.0 使用该文件的三阶段连续流程，本页以下逐 G1–G6 人工等待/approve 指令仅适用于旧 schema 2.0；数学、结果、页面、AI 披露检查仍执行。不存在 Gate 文件时由入口初始化 grouped v3；training/reference 继续原无人工门禁流程。


本 skill 只负责模式识别、共享硬约束、阶段编排和恢复边界。模式细节按需读取，避免把训练、历史摄取和正式赛规则同时装入上下文。

## 1. 先确定运行模式

读取工作区 `<repo-root>/USER_WORKFLOW_PREFERENCES.md`，再按以下优先级确定 `execution_mode`：

1. 项目已有 `compliance/CASE_MODE.yaml`：以其中 `mode` 为准。
2. 2016–2022 完整能力训练：`training_run`。
3. 只整理历史知识且需要七阶段兼容产物：`reference_case_ingestion`。
4. 待发布 Harness 的完整提交链验证：`release_candidate`。
5. 2023–2025 隔离评测：`evaluation_run`。
6. 正式比赛、正式求解或论文提交：`live_competition`。

只读取当前模式的说明：

- `training_run`：读取 [references/training-run.md](references/training-run.md)。
- `reference_case_ingestion`：读取 [references/reference-ingestion.md](references/reference-ingestion.md)。
- `evaluation_run`、`live_competition` 或 `release_candidate`：读取 [references/gated-run.md](references/gated-run.md)。

同时冻结 `competition_year` 与知识暴露状态，用 `_references/harness/scripts/contest_rules.py` 解析本轮适用规则并保存来源哈希。历史年份不得调用当届固定措辞检查器；2026 CUMCM 只有 resolver 选中 `CUMCM-2026-LIVE` 后才执行 2026 专项检查。

## 2. 冻结治理档位和运行 profile

所有模式先读取 `<repo-root>/_references/ARTIFACT_GOVERNANCE.md`，用实际仓库路径运行：

```bash
python <repo-root>/_references/harness/scripts/resolve_artifact_governance.py \
  --mode <execution_mode> \
  --output compliance/ARTIFACT_GOVERNANCE.json
```

再根据冻结的 tier 生成最小活动模块集：

```bash
python <repo-root>/_references/harness/scripts/resolve_harness_profile.py \
  --governance compliance/ARTIFACT_GOVERNANCE.json \
  --output run/HARNESS_PROFILE.json
```

既有输出不可覆盖；输入、风险事件或里程碑计数变化时生成 `HARNESS_PROFILE.vN.json`，并用 `--supersedes` 绑定上一版。同 mode 可升 tier，不能降低冻结最低要求。先用 governance 的 `--supersedes` 生成新版治理，再用 profile 的 `--supersedes` 绑定前驱；不得覆盖旧文件。临时条件保留历史阶段作用域，不自动进入后续阶段。治理 resolver 决定最低 tier，profile resolver 读取并哈希绑定该决定，不能自行选择或降级 tier。

进入阶段前用 `validate_harness_profile.py --stage <stage> --require <module>` 核对当前 profile、governance 哈希、版本链和该阶段必需模块。每阶段只加载 `stage_modules`，不加载整轮活动模块并集。运行中若产生新版 profile，下游从 run ledger 读取当前版本，并把上一版传给 `--previous`。

默认映射：

| Tier | Profile | 用途 |
| --- | --- | --- |
| Tier 1 | Draft | 训练语义链 |
| Tier 2 | Audit | 里程碑交付压测 |
| Tier 3 | Contest | 评测、正式赛、发布候选 |

特殊模型、专项知识、非数据图和恢复控制只在 profile 条件触发时加载。实验模块除了显式 opt-in，还必须先登记可验证执行契约；当前没有实验模块进入执行白名单，且任何实验都不能改写 Core 或取消 Guard。

随后读取 `<repo-root>/_references/MODEL_REASONING_ROUTER.md`，用 `reasoning_route.py` 从当前运行时真实界面能力生成并封存 `run/MODEL_CAPABILITY_SNAPSHOT.json`。所有模式都使用独立的 `run/REASONING_ROUTE_LEDGER.jsonl`；只有 formal mode 额外启用人工 Gate。不得从模型文档、别名或自述推断当前 effective effort。

任何正式计算之前运行 `_references/harness/scripts/dependency_preflight.py`，检查仓库与活动 skills 的入口引用闭包、运行依赖和本轮 route 的 effort/topology/receipt 要求，保存 `run/PREFLIGHT.json`。若状态为 blocked，报告可执行范围和缺项；已有真实用户授权的能力例外按原件哈希解析，可执行状态与未认证资格分别记录。预检通过后，用 `_references/harness/scripts/run_orchestrator.py init` 绑定 `run/RUN_PLAN.json`、预检回执、problem/objective identity 和任务闭包。新运行把求解、评审、写作、打包及已有批准节点放入同一任务图；恢复先读 status，不重新询问有效批准。路径、外部回执、计算/来源依赖和成本分账见 [全流程执行补充](../_references/harness/WORKFLOW_UPGRADE.md)，初始化或恢复时读取。

## 3. 共享硬约束

- 当届题面、附件、官方更正和专项要求优先于知识库、历史论文与模板。
- 若存在 `<repo-root>/_references/knowledge/scripts/check_active_skill_drift.py`，启动案例前用实际活动 skills 根目录检查漂移；发布过程必须同步入口实际引用的完整依赖闭包。运行中不为通过检查自动覆盖活动技能，不一致时先完成可回退的发布或明确选择同一版本根。
- 非 evaluation_run 的领域判断先读知识索引并按风险加载卡片；evaluation_run 只读取冻结题面、结果契约与通用规则，不打开训练选题、来源学习或案例检索入口。
- 只有规则 resolver 选中 2026 CUMCM 时读取 `<repo-root>/_references/cumcm_2026_compliance.md`。
- 解答性材料只能在 cold-start 与 compare 冻结后打开；持续记录来源暴露并执行污染检查。
- `results/results.json` 是数值事实源；论文、图表与结论绑定稳定 `result_id`，Writer 不得改写计算事实。
- `3coding-visual` 负责数据图；`4drawio` 只在确有必要时负责非数据型概念图，不能重复画统计图。
- 机器可读日志是状态事实源；人类可读 vault 只保留阶段摘要、重大决策、失败模式、剪枝理由和 Gate 结论。
- 每个有界推理任务必须经过 `assessed → applied/degraded/blocked → completed → reassessed`；非 `single` topology 必须有独立上下文回执。
- 临时产物只有在 promotion、哈希核验和 durable replacement 已记录后才可清理；不得按目录名直接删除。
- 训练/参考摄取不创建 `HUMAN_GATES.json`；评测/正式赛不得绕过 G1–G6。

## 4. 阶段与责任

| 阶段 | Skill | 主要责任 |
| --- | --- | --- |
| 分析与建模 | `2analysis-modeling` | 题意、候选、G2、模型合同与验证计划 |
| 计算与数据图 | `3coding-visual` | 代码、结果合同、G5、验证证据、语义包与数据图 |
| 非数据图 | `4drawio` | 条件触发的流程图、结构图和路线图 |
| 写作 | `5writing` | 从冻结语义包生成 paper.md；Audit/Contest 才进入 Word loop |
| 验收 | `6verity` | G5、复现、一致性与当前 tier 对应的交付检查 |

进入下游阶段前验证上游合同。发生实质变更时，失效最早受影响的下游状态；保留旧分支、成本记录和最后良好快照。

## 5. 完成与遥测

每个完整 run 至少记录：活动 profile、能力快照、实际路由事件/effort/topology/降级、实际阶段、G2 候选与选择、G5 决策、结果哈希、来源暴露、异常与人工介入。Token、延迟、工具调用或上下文峰值若未被运行器采集，明确记为 `missing`，不得用文件数或主观判断伪装成精确测量。

运行历史回溯可用：

```bash
python <repo-root>/_references/harness/scripts/collect_run_records.py \
  --runs-root <private-workspace>/runs \
  --output <private-workspace>/run_records.jsonl
```

## vNext 运行边界

evaluation_run 禁止训练选题、来源学习和案例知识卡检索；只读取冻结规则、结果契约和通用防错规范。不得绕过 profile 以“固定必读卡”加载案例答案。

条件/恢复事件用 `condition_detectors.py --mode <mode> --signal <signal> --stage <stage> --evidence <file> --output <events.json>` 生成；profile 使用 `--condition-events` 消费。常驻 recovery-detector 只检测，recovery-controller 仅在指定阶段加载。运行器遥测、证据快照和有界恢复契约见 [../_references/harness/RUNTIME_CONTRACT.md](../_references/harness/RUNTIME_CONTRACT.md)，首次初始化运行时读取一次。
