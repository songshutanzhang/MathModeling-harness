# B 题复盘后的执行补充

本页用于初始化新运行、恢复中断、冻结优化路线或进入 Word 交付。保留原有治理档位和两次人工批准安排；已有授权先核验与导入，不增加一次确认。历史评测不原地迁移，也不把开发小样作为新的盲测分数。

## 赛前封版入口

用 `scripts/contest_release.py seal --source-root <技能仓库> --output-dir <新封版目录> --python <实际解释器> --package numpy --package scipy` 封存发布闭包及解释器/包版本。已有封版目录拒绝覆盖。check 验证全部文件和环境；run 在验证后调用封版内运行器，例：`contest_release.py run --release <封版目录> -- status --project-root <案例目录>`。默认 state-dir 为案例下 .runtime；比赛数据和输出放在封版目录之外。封版只固定工具代码和记录的数值环境，不包含模型服务或 Word 安装。

外部节点可先用 `run_orchestrator.py draft-external --project-root <案例> --state-dir .runtime --task-id <节点> --receipt run/draft.v1.json` 生成草稿。它只读取已有事实、列出缺少的产物，status 保持 draft、未知成本为 null、approval 的 authorization 为 null；不开始/完成任务，也不替用户批准。实际工作核验后另存完成回执，再交原 complete-external 验证。

命令输出按 attempt 保存在 `.runtime/logs/<task_id>/attempt-NNNN/stdout.log` 和 stderr.log；started/completed/failed 事件记录定位路径。日志为子进程原始字节，执行期间可读取文件，终端不再逐行回显。打开日志失败则回退终端输出并记录 log_unavailable，不重试命令、不覆盖数学结果。日志可能含工具输出中的敏感信息，按原工作目录访问范围保存，不自动放进提交材料。

## 全流程任务图

`scripts/run_orchestrator.py` 的计划版本保持 `schema_version: "1.0"`，新增可选字段兼容旧计划。新项目把求解、候选登记、G5、写作、打包及已有的人工批准节点全部放入 tasks；不要只登记数值子进程。

- 命令节点继续使用 command、inputs、sources、dependencies、outputs。
- 由模型、人工或外部工具完成的节点写 `execution: "external"`，声明相同的输入/输出与依赖，省略 command。开始时运行 `start-external --task-id ID`；完成后运行 `complete-external --task-id ID --receipt run/receipt.v1.json`。
- 外部回执绑定 run_id、task_id、start 返回的 task_identity、`status: "completed"` 和 outputs 的 path/sha256。无法直接观测的 wall_clock_seconds、tokens 使用 null。回执文件按版本保存；文件存在不等于节点完成。
- cost_category 分为 numeric、llm、tool、writing、review、waiting。等待不算活动工作时间；未知成本保留 missing_observations，不能用已观测数值秒数声称整个运行用时完整。
- 给有总时限的运行设置带时区的 deadline，以及 budget_seconds、final_review_reserve_seconds。子进程 timeout 同时受剩余预算、终审保留和截止时间约束。外部工作由操作者按同一截止时间控制；缺失遥测不会被补成零。
- `status` 从事件推导 current_stage、next_tasks、provenance_pending、成本与批准维度。若计划有 human_gate_ledger，同时读取 grouped gate 的正式状态，保留资格、数学、交付、授权的区分。

所有相对参数均相对于 `--project-root`。从仓库根调用时传案例根；进入案例目录后传 `--project-root .`，两种方式的 `--state-dir .runtime` 指向同一目录。不要再给 state-dir 添加案例前缀。

`recover` 不回收仍有存活所属进程的命令节点；遗留发布事务先回滚，再隔离 staging。外部节点恢复为等待其回执，已有有效批准不失效。多文件发布以 completed 事件作为逻辑提交点，读者只能消费已提交输出；这不是文件系统提供的多文件同时原子切换。

## 原批准与能力例外

外部 approval 节点的回执增加 authorization，使用以下字段：

```json
{
  "run_id": "this-run",
  "scopes": ["approve-route"],
  "decision": "accepted",
  "original": {"path": "compliance/user-original.txt", "sha256": "原件哈希"},
  "artifacts": [{"path": "reports/route.md", "sha256": "用户已看过的版本哈希"}],
  "exception": true,
  "uncertified_fields": ["effective_reasoning_effort"],
  "alternative_evidence": [{"path": "run/observed-capability.json", "sha256": "替代证据哈希"}]
}
```

这是从真实授权原件生成的索引，不能由模型自行创造用户同意。已有 grouped v3 批准继续使用 grouped_gate.py 的 import-approval 和原批准包哈希；不重置旧账本、不重复询问。新索引的 scopes 必须覆盖对应节点 ID。

能力预检例外使用 `runtime_capability` scope，并明确 accepted_failures。通过 dependency_preflight.py 的 `--exception-receipt`、`--project-root`、`--run-id` 应用。只能接受逐项匹配的 route 能力缺项，不能豁免缺文件、数学硬错或交付错误。可执行状态可以为 executable，qualification 必须保持 not_certified；grouped gate 状态也不再将这种 executable 映射为资格 PASS。严格 route/topology 认证本身不因此成立。

grouped v3 的阶段回执可显式引用 capability_exception 和 run_id；例外原件须有 `gate:route`、`gate:execution` 或 `gate:delivery` 的对应 scope，并绑定该阶段报告及全部产物。程序仍先检查阶段技术要求、G5、Word/PDF 和披露，再处理运行资格例外；不创造 route/topology completed 记录。严格 submission_ready 保持 false，满足最终技术检查及批准时单独显示 accepted_exception_delivery_ready，避免混淆。旧的 pending 快照不改写，新 checkpoint/approval 由追加事件产生。

## 计算与来源依赖

inputs 和 sources 进入计算身份；上游完成身份递归核验，依赖身份和输出共同绑定。只修改未被求解器依赖的论文措辞不会使数值任务失效。

Python 命令默认通过 `scripts/audited_python.py` 执行，读取未声明的项目文件会失败并阻止发布。声明整棵实际源码目录及计算数据，避免漏掉进口模块与题面提取文本。审计是 Python open 事件检查，不是操作系统沙箱；原生库、自建子进程和非 Python 工具需有各自的读取清单/追踪证据。不能将其描述为已证明任意程序的所有读取闭包。

仅用于来源说明的文件可放在 provenance_inputs，其变化显示 refresh_required，不重算数学。来源更新应生成独立 sidecar，绑定当前 provenance_manifest、task_identity、numerical_outputs，再用 `refresh-provenance --receipt ...` 验证。数值输出中旧的来源记录保留为历史，不改写冻结数学文件。

Python 包预检读取任务实际解释器的版本；不要用另一个环境中的已安装包推断任务依赖可用。JSON 发布支持 NumPy 数组与标量，仍拒绝 NaN/Infinity。

## 性能小样与结构上限

批准搜索范围前，把代表性小样作为命令节点实测。`scripts/performance_pilot.py` 从真实 completed 事件导出 PILOT，保存任务身份、输出和实际秒数。estimated_seconds 仍然只是预估。先测数值小样不意味着 LLM、写作或整项工作的成本已经测得。

对分区数、方向范围或离散参数边界记录递增搜索 history，每项包含 limit、selected_value、objective。`scripts/search_evidence.py opportunity` 在连续收益且最优值贴边时要求以下三种回执之一：

1. probe_completed：一次扩展后的候选证据、实测成本、同一 history 哈希及预授权的最大范围/秒数。authorization 使用 search_extension scope。
2. measured_stop：绑定真实执行回执的小样成本已超出剩余授权预算；仍有余量时不能以预算为由停止。
3. outside_authorization：绑定原批准的 search_scope 与 maximum_limit，记录为何扩展超出已批范围。保留明确决定，不自动越界，也不重复无界回拨。

只有“论文已披露局限”不能关闭结构上限信号。G5 的数学可靠性与剩余机会分开：正式运行的 g5 检查引用 reliability_bundle，直接调用已有 G5 验证器；opportunities 中列出上述处置。通过正确性检查并不自动证明搜索已足够。

## 公平候选与定义诊断

新优化运行登记 candidate_evidence 1.1：冻结真实 evaluator 文件；definition 包含 id、denominator、aggregation；声明共同 precision、sample_group、seeds；actual_budget 绑定 evaluations、observed_seconds 和实测回执；raw_metrics/objective/feasible 与原始产物一致。1.0 可读取，但不再声称 strict_ablation。

candidate_registry.py 晋级只比较同协议候选，保留上级可行 incumbent；不同实际评估次数或种子不能混入严格消融。晋级回执保存被排除的候选和理由，不能只展示获选者。

冻结前运行题型适用的定义测试。`scripts/definition_probe.py` 给出区间覆盖的平底、交换、贴合、嵌套和裁边界示例，输出可行性与排序变化。它是开发模板，不替具体题目选定分母。其他题型换成对应退化性质，不机械套用声呐定义。

写作等消费节点的 checks 可引用 definition、opportunity、g5、candidate_promotion 类型及哈希绑定 evidence。运行器在身份计算和执行前真正调用检查；candidate_promotion 会重算晋级结果并核对冻结回执，不能把“文件已经存在”当作检查已接入。

## Word 与 P2 开发示例

只有激活 word-delivery 才调用 `../../5writing/scripts/word_conversion_canary.py`，先生成短稿，用当前真实模板/转换器检查公式、字段、表头和源码，然后渲染并查看每页。结构检查只输出 structural_pass，不替代视觉 QA。Windows 可用 `../../5writing/scripts/render_with_word.py` 接入已安装 Word；通过 DOCX_RENDERER 指定运行依赖提供的 render_docx.py。

word_loop.py 的 delta-plan 比较上一已通过 loop 与当前渲染回执。仅在相同页位、PNG 哈希相同且旧 QA 完整时复用；新增或变化页逐页检查，删除页还需完整性检查。填好回执后用 snapshot 的 --delta-qa-receipt 冻结。首次交付及最终独立重渲染仍按原规范执行。

`scripts/terrain_route_demo.py` 是合成地形的共同评价器示例，比较轴向、局部方向、等深折线及分区边界/局部路线组合，记录端点、接缝、转场和三种种子。记录实际搜索次数，不把更大联合预算称为严格等预算消融；保留简单 incumbent，复杂路线没有收益就不晋级。

示例同时提供矩形面积几何下界、有限测线库的覆盖 LP 下界和校准余量。LP 下界只适用于声明的有限库；采样零漏测不等于连续覆盖。合成残差的单点边际校准以交换性为前提，小样本无法支持全域同时保证时返回不足，不能把任意浅化量当作置信区间。

## 可复现验收

- `scripts/run_workflow_canary.py --output-dir <新的空目录>`：真实数值与 NumPy 发布、1.1 候选晋级、外部评审/写作恢复、批准复用、例外与缺失成本；外部消息明确为合成 fixture。
- `scripts/terrain_route_demo.py --output-dir <开发目录>`：方向/分区与鲁棒性开发示例。
- tests/test_workflow_recovery.py、tests/test_search_evidence.py 和 Word delta QA 测试负责负例；旧 P0–P2 与 grouped gate 测试继续回归。

真实盲测质量、完整外部调用成本、实际地形的覆盖证明仍需新的未暴露题前向验收。本轮不得修改旧题结果后再宣称盲测提升。
