---
name: 5writing
description: "数学建模竞赛论文撰写阶段。Tier 1 将 Solver 语义产物转换为 paper.md；Tier 2/3 使用 DOCX 唯一可编辑事实源并执行版本化 Word/PDF/逐页 QA。"
allowed-tools: Bash(*), Read, Write, Edit, Grep, Glob, Agent, WebSearch, WebFetch
---

# Word-first 竞赛论文撰写

## Formal grouped v3 分流

正式模式新 run 默认采用 [两次审批工作流](../_references/GROUPED_GATE_WORKFLOW.md)。先检查 `compliance/HUMAN_GATES.json` 的 schema：3.0 使用该文件的三阶段连续流程，本页以下逐 G1–G6 人工等待/approve 指令仅适用于旧 schema 2.0；数学、结果、页面、AI 披露检查仍执行。不存在 Gate 文件时由入口初始化 grouped v3；training/reference 继续原无人工门禁流程。


本 skill 承接 `3coding-visual` 和 `4drawio`。先读取 `compliance/ARTIFACT_GOVERNANCE.json`：Tier 1 只生成语义论文 `paper/paper.md`；Tier 2/3 才进入 Word-first，正文只在 Word 中维护，每个写作 loop 交付可编辑 DOCX，PDF 只能由同轮 DOCX 导出。

vNext run 进入本阶段前，先用 `_references/harness/scripts/validate_harness_profile.py --stage writing` 核对 profile 与 governance。所有完整求解 profile 的写作阶段必须激活 `semantic-package` 与 `semantic-writer`；只有激活 `word-delivery` 时才读取 Word-first 细节并执行 DOCX/PDF loop。Draft profile 不得因本 skill 被调用而隐式升级交付层级。旧项目没有 profile 时按冻结 tier 走 legacy 分支，并记录证据缺口。

## 必须读取

- 所有 tier：`../USER_WORKFLOW_PREFERENCES.md`、`../_references/ARTIFACT_GOVERNANCE.md`、冻结的 tier/profile、`problem-rules-first.md` 与写作相关规范；
- Tier 2/3 且 `word-delivery` 已激活：再读取 `../_references/word_first_writing_workflow.md`；
- Tier 3 的 evaluation/live/release：再读取 `../_references/human_gate_spec.md` 与 `../_references/MODEL_REASONING_ROUTER.md`；
- 先读取 `run/CONTEST_RULES.json`；仅当 resolver 选中 2026 CUMCM 时，Tier 2/3 再读取 `../_references/cumcm_2026_compliance.md`。

当届题面、附件和官方更正中的专项要求无条件优先。论文结构、图表、结论和附录必须覆盖 `ANALYSIS_MODELING_REPORT.md` 的全部赛题硬规则 `rule_id`，不得用历史获奖论文或模板替代题目实际要求。
- 仅规则年份为 2026 的 Tier 2/3 CUMCM/国赛项目，在没有官方或赛区 Word 模板时读取 `references/cumcm_word_template.md`，并使用 `assets/CUMCM_2026_论文模板.docx` 初始化工作稿。历史回顾任务使用该年份的官方格式来源，不用 2026 模板覆盖。

实际创建或编辑 DOCX 时，如果运行环境提供 `documents` skill，必须调用并遵守其依赖加载、Word 编辑、渲染和逐页检查要求。若不可用，才使用 `python-docx` 与 LibreOffice/Word 导出替代，并在本轮 QA 记录中说明。

## Tier 1：Semantic Writer

读取 `run/SEMANTIC_ARTIFACT_PACKAGE.yaml`、建模/结果/验证报告、`results.json` 和图表索引，生成 `paper/paper.md`。Semantic package 至少包含 equations、definitions、assumptions、result IDs、figure references、conclusions、limitations 和 validation evidence。Writer 只能转换表达形式，不得改变数值、模型事实或不确定性；冲突时返回 Solver。

Tier 1 检查章节、公式、图表引用、result_id、摘要正文一致性和引用真实性，不创建 DOCX/PDF/页面 PNG，不初始化 Word loop，也不得声称提交就绪。新 run 使用 lightweight manifest schema `1.1`，由 `validate_lightweight_manifest.py` 绑定 paper、results、figures 与当前 `HARNESS_PROFILE` 哈希；历史 `1.0` 只作兼容验证。以下 Word-first 输入、产物和 Step 0–8 仅适用于 Tier 2/3。


## Audit / Contest 条件流程

仅当 `word-delivery` 激活时读取 [references/word-delivery.md](references/word-delivery.md)。该流程保留版本化 DOCX、同源 PDF、全部页面 QA、metadata、finalize 和 route task；Tier 2 只形成里程碑结论，Tier 3 才进入 G6。全文前先做短转换样例；首次全页检查后，相同页位且 PNG 哈希相同的页面可复用旧 QA，变化页逐页检查，这不是抽样。写作开始/完成回执与增量 QA 格式见 [全流程执行补充](../_references/harness/WORKFLOW_UPGRADE.md)。
