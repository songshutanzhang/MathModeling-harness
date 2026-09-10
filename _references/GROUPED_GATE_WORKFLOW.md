# 两次审批、三阶段工作流（grouped v3）

适用于 evaluation_run、live_competition、release_candidate。用户已选择中间自动推进：正常路径只在路线决策和最终交付时请求人工批准。training/reference 保持无人工 Gate。新 formal run 使用本协议；已有 HUMAN_GATES.json schema 2.0 继续旧协议，不迁移或继承批准。

## 总顺序

```text
高强度读题、路线比选、可读决策书（G1–G2）
      ↓ 人工批准路线与执行边界（第一次）
基线强度形式化、编码、运行、排查、结果报告（G3–G4）
      ↓ 技术检查通过后自动继续
Ultra 结果盲审 → 修复和独立验证 → 写作与完整交付 → Ultra 最终多视角审查（G5–G6）
      ↓ 人工批准当前交付版本（第二次）
提交就绪；上传仍按用户实际授权执行
```

G1–G6 是检查责任标识。`checked` 表示已有技术证据，`approved` 只表示实际人工授权；不批量伪造六条人工批准。收到明确针对当前包的“按这个方案继续”可以是有效批准，不要求用户重复输入专用口令；沉默、询问和要求解释都不等于批准。

恢复时若明确批准已保存在项目内的结构化记录中，用 `import-approval` 校验其 source hash、当前 checkpoint hash 和 checkpoint artifacts hash 后追加到同一审计链。完全相同的导入幂等；错误绑定、同 decision_id 的不同证据或漂移文件都拒绝。导入是已有用户决定的证据适配，不是脚本替用户批准。

## 第一阶段：路线决策（G1–G2）

在同一连续阶段完成题面/附件理解、歧义整理、问题拆解、基线与候选比较、可行性试验和工具评估；不先等待 G1 批准才开始 G2。默认请求 high 以上的可用强度，复杂路线比较用更高强度；只记录实际设置回执。路线未批准前可做有界数据剖析和候选小原型，不把探索结果当作正式结论。

交付 `reports/ROUTE_DECISION.vN.md`，使用 [gate-templates/route-decision.md](gate-templates/route-decision.md)。读者无需熟悉数模术语即可理解：

- 每问在现实中求什么、输入与输出、题目硬约束、各问如何相连。
- 歧义的不同解释会怎样改变结果；假设的依据、可检验性和失败后果。
- 一个透明基线与有效候选，比较适用条件、可解释性、复杂度、数据需求和争奖潜力。
- 推荐算法的通俗解释、关键公式/变量/单位、可复现步骤和小例子；先解释“为什么适合”，再给技术细节。
- 工具及选择原因、依赖、预期运行预算、验证方案、备用路线与下一步任务。
- 一页决策摘要：需要用户确认的实际取舍、不确定性、推荐选择，以及选择后会自动发生的工作。

这里的“可复现思路”是可公开验证的方法说明、计算推导、算法流程和证据，不是模型内部逐步思维记录。不能把篇幅长或术语多当作可读性。

同时冻结 `run/EXECUTION_CONTRACT.vN.json`：fixed_assumptions、allowed_changes、reapproval_triggers 为非空字符串列表；max_local_retries、max_wall_clock_seconds 为正整数；continue_after_execution_report=true。预算按当前用户约束与题目规模填写，不用模板统一数值。路线批准覆盖这个边界内的 G3/G4 自动执行及进入最终审查。

G2 的候选、Critic、prototype、selection 和路由绑定继续由原验证器检查；冻结 G1/G2 两项技术证据后，一次展示并批准整个路线包。不同用户反馈形成新版本，不重复批准没有变化的旧材料。

## 第二阶段：实装与运行结果（G3–G4）

G3：固化目标函数、约束、变量、指标、验证计划和模型合同，自动做一致性检查。G4：按批准的边界处理数据、设定参数、编码、基线对照、约束回代、敏感性/不确定性分析、运行与排查。默认使用初始化时冻结的基线 model/effort，不把每个形式化或普通调试任务自动升级到 Ultra。个别有界诊断确需偏离基线时，receipt 的 effort_exceptions 以 G3/G4 为键写具体原因，实际设置仍由 route receipt 绑定；超出已批准预算须另行请求用户决定。

生成 `reports/EXECUTION_RESULTS.vN.md`，使用 [gate-templates/execution-results.md](gate-templates/execution-results.md)。包含实际命令/环境/seed、结果编号与单位、各问关键结论、基线比较、已做排查和局限。遗留问题逐项写出证据、已排除原因、影响范围、下一步需要什么审查；不把“需要更强模型”当作跳过普通验证的理由。

问题分三类：

1. 阻断错误：违反题面硬规则、不可行、泄漏、不可复现等，必须修复，不能携带 FAIL 自动交付。
2. 需要用户取舍：改变已批准路线/关键假设/硬约束、预算越界、接受会实质改变结论的风险，失效受影响阶段并展示精简差异决策包。
3. 非阻断不确定性：证据有限、解释待核对、潜在上限不足等，可明确标注影响和 next_check，自动转最终高强度审查。关键结论受影响时不得写成已确定。

生成 execution 技术 receipt，G3/G4 检查通过且处于已授权范围内后 `check --phase execution`，无需人工 approve。此时数值可用于候选论文草稿，但核心 claims 仍待 G5 独立验证；旧“G3/G4 未获逐项人工批准不得运行”的条款仅属于 legacy v2。

## 第三阶段：最高强度评审与完整交付（G5–G6）

G5 在写作定稿前审查同一冻结 Evidence Package，分别运行 Failure Hunter（结构/数学/约束/数据/复现完整性）与 Ceiling Reviewer（建模选择、有效创新、基线强度、论证及争奖潜力）。两者在首次报告冻结前互不可见，也不读取 Solver 辩护、G2 推荐措辞或获奖预期。然后汇总分歧，Solver 逐条回应，Independent Validator 验证修复；可靠性 FAIL 不能被上限评分覆盖。

通过后进入 Word-first 写作和版式工具链；普通文件转换与排版沿用基线强度，最高强度用于有判断价值的 G5/G6 评审。结果修改形成新版本并重审相关证据；不改变批准路线的局部修复自动继续，改变路线或预算时重新请求用户决定。

G6 冻结最终论文和交付输入包，至少两个独立上下文分别给出 structure_reviewer 与 prize_reviewer 报告；首次意见冻结前互不可见。之后形成 `reports/FINAL_REVIEW.vN.md`，使用 [gate-templates/final-review.md](gate-templates/final-review.md)，逐条显示发现、严重性、证据、处理、复验及剩余局限。争奖潜力是论据充分的判断，不承诺奖项。

用户要求 Ultra 多视角：G5/G6 route 均请求 ultra，topology 分别 dual_review/ensemble，实际生效和不同上下文必须有回执。本协议不静默降级后仍标记“最高强度评审完成”；平台不能提供时保留待审状态，说明缺项，由用户决定是否另行接受更低证据规格。不同文件名不证明盲审，独立上下文也不自动证明统计独立。

最终交付 DOCX、同源 PDF、FINAL_DELIVERY.json、AI 日志与论文 AI 声明、适用时 AI工具使用详情.pdf、代码/数据说明/依赖/复现命令等支撑材料及最终评审报告。版式、匿名性、披露、引用、逐页 QA、压缩包、结果一致性仍使用现有检查器，不能以 grouped receipt 替代真实验证。

先完成全部交付物和评审，再一次展示待批准包；未批准时为 PENDING_FINAL_APPROVAL。用户批准绑定当前论文、AI 材料、支撑材料、报告和 manifest。上传是后续外部操作，只在已有实际上传授权时执行。

## 脚本与版本绑定

```text
python _references/scripts/grouped_gate.py init --file compliance/HUMAN_GATES.json --project-root . --mode live_competition
python _references/scripts/grouped_gate.py check --file compliance/HUMAN_GATES.json --project-root . --phase route --receipt compliance/gates/route.v1.json
python _references/scripts/grouped_gate.py approve --file compliance/HUMAN_GATES.json --project-root . --phase route --decision-id D-route-1 --checkpoint-hash <展示的当前hash> --approval-evidence <用户对该包的实际批准>
python _references/scripts/grouped_gate.py import-approval --file compliance/HUMAN_GATES.json --project-root . --approval-record compliance/gates/route-approval-import.json --expected-approval-sha256 <source-hash>
python _references/scripts/grouped_gate.py check --file compliance/HUMAN_GATES.json --project-root . --phase execution --receipt compliance/gates/execution.v1.json
python _references/scripts/grouped_gate.py check --file compliance/HUMAN_GATES.json --project-root . --phase delivery --receipt compliance/gates/delivery.v1.json
python _references/scripts/grouped_gate.py approve --file compliance/HUMAN_GATES.json --project-root . --phase delivery --decision-id D-delivery-1 --checkpoint-hash <展示的当前hash> --approval-evidence <用户对该版本的实际批准>
python _references/scripts/grouped_gate.py verify --file compliance/HUMAN_GATES.json --project-root . --require G1 G2 G3 G4 G5 G6
```

receipt 通用字段：schema_version=1.0、phase、report（Markdown 路径）、checks（该阶段两个 Gx 均为 pass）、issues（可空，非空项含 id/impact/next_check/status/blocking/requires_user_decision）、artifacts（角色→路径）、route_ledger、capability_snapshot。execution 另需 within_approved_scope=true、within_approved_budget=true；delivery 另需 ai_used 布尔值和 review_isolation=distinct_contexts。

必需 artifact 角色在 grouped_gate.py 的 REQUIRED_ARTIFACTS 中定义；运行 `status` 可见实际绑定和 checkpoint_event_hash。G5 topology 输入绑定 evidence_package；G6 topology 输入绑定 final_review_input（JSON 中 artifacts 按角色保存 paper_docx/paper_pdf/final_manifest/ai_log/ai_statement/supporting_materials，以及使用 AI 时的 ai_details_pdf 的 path/kind/sha256）。两次人类批准外不生成伪批准记录。所有 approval 证据必须来自实际用户消息，脚本不能自行证明消息来源。

`status --preflight run/PREFLIGHT.json` 同时输出四维状态：资格、数学、交付、授权。单一 FAIL 不吞并其他维度，且只有四维满足时 `submission_ready=true`。

变更使用 `invalidate --phase route|execution|delivery --reason <原因>`；route 失效重做第一次决定并清除下游，execution 失效只重跑和重审，不强制重做仍有效的路线批准，delivery 失效只重审并重新确认最终版本。保留旧文件与事件，不覆盖报告。

旧 `human_gate.py verify` 可读 v3：G1/G2 要求路线批准，G3/G4 要求中间技术通过，G5 要求最终阶段技术通过，G6 还要求最终批准。新 workflow 内必须按本文件顺序运行，不能进入旧 v2 的每 Gate approve 命令或提前执行最终 G6 验证。
