# vNext 候选运行契约

首次初始化运行器时读取。活动发布必须包含入口实际引用的依赖闭包；结构验证不能替代模型质量、真实 Word 交付、held-out 或最终发布验证。

新运行的全流程任务图、能力例外、计算/来源依赖、性能小样、候选 1.1 和结构机会处置以 [WORKFLOW_UPGRADE.md](WORKFLOW_UPGRADE.md) 为执行补充。旧格式继续读取，历史资格和评测分数不回填；新增 checks 要由实际消费节点调用。

## 启动预检与统一运行入口

正式计算前先运行 `dependency_preflight.py`。它同时检查活动入口的本地引用、仓库发布清单、Python 包/外部程序和冻结 capability snapshot 中的 effort、topology、有效设置回执接口。状态为 `blocked` 时不得启动计算；报告可执行范围和缺项，不在事后伪造回执。随后用 `run_orchestrator.py init` 绑定 `RUN_PLAN.json` 与预检回执，再以 `run-all` 或 `run --task-id` 执行有界任务。

每个任务声明 command、inputs、sources、dependencies、outputs、packages、configuration、最大 attempt 和预计耗时。命令只向 `HARNESS_OUTPUT_DIR` 写 staging 输出；全部声明输出存在后才原子发布并记录 completed。completed 回执绑定传递源码、输入、依赖任务输出、运行时版本、命令与任务配置。只改论文措辞不会使未依赖论文的数值任务失效；修改光学内核等传递源码会生成新任务身份。文件存在而 completed 回执缺失时一律不算成功。

`recover` 将遗留 running marker 记为 interrupted，把部分 staging 产物移入 quarantine，保留已验证输出和外部门禁账本。额度恢复且 problem/objective identity 未变时延续同一 run 并增加 attempt；执行配置变化生成新 revision；题意、目标或数据定义变化需新 experiment/run。总预算可为独立终审设置 `final_review_reserve_seconds`，普通任务不得侵占该尾部窗口。

## Profile 与条件

`resolve_artifact_governance.py` 冻结 mode/tier；`resolve_harness_profile.py` 生成 profile 1.1 并绑定治理与 policy 哈希。合法组合：training Tier 1/2、reference Tier 1、evaluation/live/release Tier 3。已有 profile 1.0 用旧版本验证器读取；不原地伪迁移。

Draft→Audit：先 `resolve_artifact_governance.py --mode training_run --requested-tier tier2 --supersedes <old-governance> --output <new-governance>`，再 `resolve_harness_profile.py --governance <new-governance> --supersedes <old-profile> --output <new-profile>`。下游校验传 `--previous <old-profile>`。升级不降低已冻结模块要求。

`condition_detectors.py` 仅从显式 signal 和证据产生事件；special_route、knowledge_gap、diagram_requested、upside_requested 由 condition-detectors 负责，failure、timeout、budget_exceeded 由 recovery-detector 负责。`--stage` 只授予该阶段；下一阶段需新的事件。新增条件文件通过 `--previous` 携带既有历史事件；profile 通过 `--condition-events` 绑定文件及证据哈希。重模块不判断自身是否加载。简单 API/旧调用的 `--condition` 保持兼容，标记 explicit_caller_input；不能用它声称自动检测已观测。

恢复事件发生后，编排器在受影响阶段创建新 profile，读取已有最后良好快照与最早受影响合同。单事件最多两次局部重试，每次独立 call_id/attempt；相同硬失败再次出现或预算耗尽时停止重试，回到最后良好快照，无法证明快照有效则记录需要用户处理。formal Gate 失效按原协议传播。恢复程序不自动删除产物、不覆盖冻结 evidence。检测器和装配已实装，真实数学任务的恢复成功率仍待前向实测。

## G5 分责

- Reliability：`validate_g5_bundle.py --bundle <bundle> --reliability-only`，消费 Failure Hunter、Solver Response、Independent Validation、G5 Decision 和 Evidence Package。开放硬错误、证据漂移或独立验证未通过都不能 accept。结果 schema/数值语义仍由 `validate_results.py` 与独立复算接管；G5 包结构校验不是结果数学正确性的证明。
- Upside：`validate_g5_upside.py --bundle <bundle>` 独立检查上限评审的输入隔离及评分。默认继续 Baseline 的双评审行为；单变量消融时才用 profile 的 `--disable-upside-review`。关闭时新 Response 只引用 Failure Hunter，Decision 增加 `review_protocol: reliability_only` 供 collector 识别；旧包继续用无该开关的兼容 validator。
- Rescue：仍为 EXPERIMENTAL，白名单为空。最多一次、预算、触发阈值、独立验证和稳定 fallback 的完整实验绑定未完成前拒绝执行。

Failure Hunter 初审保持冻结。修复后由 `g5_disposition.py` 追加 `FINDING_DISPOSITIONS.jsonl`：每个关闭/重开事件绑定初审、当前 Solver Response、当前 Independent Validation、复验证据及 reviewer 身份；只有通过且明确覆盖该 finding 的 independent validator 可追加。`G5_DECISION.yaml` 必须绑定最新 disposition chain head，并把 `hard_failures` 写成程序归并后的当前开放集合。Solver 自报关闭、旧回复哈希和旧复验哈希均无效。

输入/文件隔离称 artifact-isolated 或 input-isolated。模型实例和上下文独立性只依据运行器可验证的 receipt，未知项记录 null，不能用不同文件名或随机 UUID 冒充独立调用。

## 真实遥测与 vault

每次调用写符合 `schemas/run_telemetry.schema.json` 的事件；事件文件是 run ledger 的成本子账本，不复制模型路线状态。字段包括 run/case/dataset role、实际 model/effort/context/instance、输入与配置哈希、profile 版本、stage、attempt、执行顺序、可见/隐藏输入、来源暴露、各项 metrics、人工介入和失败类别。未知字段用 null，metric evidence 为 missing。cached_tokens 为输入 Token 的子集，不能再次相加。

```text
python run_telemetry.py record --directory <case>/run/telemetry --event <event.json>
python run_telemetry.py run --directory <case>/run/telemetry --event <template.json> -- <command> <args>
python run_telemetry.py summary --directory <case>/run/telemetry --output <summary.json>
python run_telemetry.py vault --directory <case>/run/telemetry --output <stage-summary.md>
```

`run` 实测本地子进程 wall-clock 与一次工具调用；不推断模型 Token。相同 call_id 相同事件可幂等导入；冲突拒绝。重试必须新 call_id 且递增 attempt。分阶段 duration 相加是调用时间总和，不是并发端到端延迟。缺失项继续 missing，已观测 subtotal 单独显示。子进程正常退出后遥测写入失败不改变数学命令的退出码，但阻止成本结论；进程被强制杀死可能没有完结事件，应按 missing 处理，不补零。

vault 从事件派生 stage/decision/failure/prune/gate 摘要，按 call_id 定位原记录。collector 自动读取 `<case>/run/telemetry` 到新 `telemetry` 字段；旧的总成本字段继续 missing，避免把未完整采集的子进程成本当作整个 run 的成本。

## 内容寻址证据

为新 G5 run 准备 sources JSON 数组：每项包含相对于 case root 的 path、原始 origin、retention（full / excerpt / hash_only）、reviewer_visible。外部材料只保存允许留存部分；excerpt 必须是实际可见的精确 UTF-8 片段。局部生成的 Evidence Package、模型合同、results、图表及验证输入可 full。reviewer 必须实际从这些冻结输入读取，不能在事后把新快照绑定到旧评审。

```text
python evidence_snapshot.py capture --root <case> --store <case>/evidence-store --sources <sources.json>
python evidence_snapshot.py verify --manifest <store>/manifests/<hash>.json --root <case>
python evidence_snapshot.py verify --manifest <manifest> --replay-to <new-empty-root>
```

manifest 与对象内容寻址并记录 schema、validator hash、访问时间、原始来源和 reviewer 可见片段。verify 区分 historical snapshot valid 与 current source drifted；hash_only 的可见输入不能重放。回放只恢复评审输入，不认可当前结果或改写旧分数。历史快照状态不可被新快照改写。

## 检查责任与迁移

装配及绑定归 profile；数值事实归 results contract/independent validation；G5 reliability 负责决策硬门；页面错误归 page audit；匿名性、披露和最终同源文件归 contest compliance。年份与模式由 `contest_rules.py` 解析并绑定规则来源哈希；`check_cumcm_2026.py` 必须显式传 `--competition-year 2026`，不得用于 2023 回顾性作品。

候选用 `candidate_registry.py` 登记。晋级必须有同 evaluator、预算、精度和共同样本组的强基线及至少一项结构消融；嵌套问题始终把上一级可行 incumbent 注入候选池，防止扩大可行域后退化。`math_search_tools.py` 提供分式目标的边际外部性判据和 3–5 分区联合搜索；只有穷尽声明的离散域时才给零 gap，其他情况明确保留启发式范围。

跨阶段数学检查由 `validate_once.py --check results|g2|g5 ...` 缓存成功回执。默认保留 whole-case 兼容身份；新 run 用 `--input` 与 `--source` 声明完整传递闭包，使无关论文措辞不触发数值重算。验证器资源、依赖版本和命令参数始终绑定；输入变化或失败重新执行。页面 QA、人工批准和最终独立重渲染不缓存。
