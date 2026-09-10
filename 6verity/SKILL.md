---
name: 6verity
description: "数学建模竞赛验证阶段。Tier 1 验证语义论文与 G2/G5 证据；Tier 2 做里程碑 Word/PDF 压测；Tier 3 完成正式提交一致性、合规和 G6。"
allowed-tools: Bash(*), Read, Write, Edit, Grep, Glob, Agent, WebSearch, WebFetch
---

# Word-first 验证和验收

## Formal grouped v3 分流

正式模式新 run 默认采用 [两次审批工作流](../_references/GROUPED_GATE_WORKFLOW.md)。先检查 `compliance/HUMAN_GATES.json` 的 schema：3.0 使用该文件的三阶段连续流程，本页以下逐 G1–G6 人工等待/approve 指令仅适用于旧 schema 2.0；数学、结果、页面、AI 披露检查仍执行。不存在 Gate 文件时由入口初始化 grouped v3；training/reference 继续原无人工门禁流程。


本 skill 是完整工作流最后一关。先读取 artifact tier；它不重新建模，不把 PDF 当作编辑源，也不在没有用户批准时自行提交。Tier 1/2 只形成训练或里程碑验收，Tier 3 才负责最终 DOCX/PDF、合规材料和 G6 授权。

vNext run 先用 `_references/harness/scripts/validate_harness_profile.py --stage verification` 校验当前 profile、governance 哈希与版本链。完整求解的验证阶段必须激活 `independent-validation` 和 `g5-reliability-gate`；Audit 再要求 `page-render-audit`，Contest 再要求 `human-gates` 与 `contest-compliance`。验证只执行当前 `stage_modules` 对应的检查，任何必需模块缺失都 fail closed。旧项目没有 profile 时按冻结 tier 执行 legacy 全检查并记录缺口。

## 必须读取

- 所有 tier：冻结的 tier/profile、`../_references/ARTIFACT_GOVERNANCE.md`、`../_references/G5_BLIND_REVIEW_SPEC.md`、`problem-rules-first.md` 与 `result-traceability.md`；
- Tier 2/3 且 `page-render-audit` 已激活：再读取 `../USER_WORKFLOW_PREFERENCES.md`、`../_references/word_first_writing_workflow.md` 与论文验收规范；
- Tier 3：再读取 `../_references/human_gate_spec.md`、`../_references/MODEL_REASONING_ROUTER.md` 和 `run/CONTEST_RULES.json`；只有规则 resolver 选中 2026 CUMCM 时读取 `../_references/cumcm_2026_compliance.md` 并运行 2026 固定措辞检查。

最终验收把当届题面、附件和官方更正视为最高优先级输入；必须逐条核对赛题硬规则 `rule_id` 已由模型、代码、结果、论文和提交材料兑现。任何未覆盖规则都是硬错误。

检查或重新渲染 DOCX 时，如果运行环境提供 `documents` skill，必须调用并遵守其结构检查和逐页渲染要求。PDF 只用于验证由 Word 导出的视觉结果，不能在 PDF 中单独修复正文。

## 分档入口

- Tier 1：验证 G2 Tournament、G5 输入隔离双评审包、`results.json`、验证报告、figures、`paper.md` 与 lightweight manifest；输出 `reports/TRAINING_VERIFY_REPORT.md`。不要求 Word/PNG/G6，结论只能是 `TRAINING_PASS/FAIL`，不能写提交就绪。
- Tier 2：在 Tier 1 之上执行版本化 DOCX、同源 PDF、全部页面 PNG、metadata、引用和 AI disclosure 压测；输出 `MILESTONE_PASS/FAIL`，不产生比赛提交授权。
- Tier 3：执行下列完整输入、Step 0–9 与 G6。evaluation_run/live_competition/release_candidate 不得降级。

所有 tier 先运行 G2/G5 协议校验；Reliability FAIL、open hard failure、未绑定 result_id 或 Competition Upside 试图覆盖硬错误时立即失败。

运行计划必须为最新版本独立终审保留 `final_review_reserve_seconds`。进入尾部窗口后冻结当前最好可行候选和最终评审输入，停止非必要探索；独立复验作为 `independent_review` / `final_review` 任务运行。评审中发生修复时生成新版本，旧回执因输入哈希变化自动失效，只复验变化范围及依赖它的下游，最终 manifest 必须绑定当前通过版本。

恢复或最终归并先读运行器 status，核对评审/写作/批准节点、来源刷新及正式 gate 状态。数学正确性、交付、授权与运行资格分别报告；已接受的规格例外仍是未认证，不因 executable 而写资格 PASS。结构机会处置与完整成本缺项一并进入结论，执行格式见 [全流程执行补充](../_references/harness/WORKFLOW_UPGRADE.md)。


## Audit / Contest 条件流程

Tier 2 读取 [references/contest-verification.md](references/contest-verification.md) 的 Word 结构、同源 PDF、全部页面与数值检查（Step 1、3–5），验证最新 milestone loop；不执行 final-ready/final-manifest、不要求 submission，也不执行 G1–G6。Tier 3 读取并执行完整流程。topology receipt 只能证明运行器可核验的上下文拓扑。

## 检查责任

profile validator 负责装配与哈希；G5 reliability 负责数学硬门；page-render-audit 负责版式；contest-compliance 负责最终提交。消费已有哈希绑定回执，输入变化才复验；正式最终独立重渲染继续保留。不得因去重漏掉语义或最终提交检查。

G5 新架构把 `g5-reliability-gate` 与 `g5-blind-upside-review` 分开。默认保留 Baseline 的上限评审；只有预注册消融显式 `--disable-upside-review` 才关闭它。关闭时用 `validate_g5_bundle.py --reliability-only`，响应只绑定 Failure Hunter；开启时继续使用兼容双评审入口并可独立运行 `validate_g5_upside.py`。旧 bundle 不重写。输入隔离只描述可见材料；模型独立性另查运行器回执。ceiling-rescue 不进入执行白名单。

同一输入的跨阶段重复数学检查统一使用 `harness/scripts/validate_once.py`（`--check results|g2|g5`，脚本路径相对于 `_references`）。缓存目录须在 case 外；新 run 声明数学 `--input` 与传递 `--source` 闭包，验证器和依赖版本始终绑定。输入变化自动重新执行，失败不复用；最终独立页面重渲染不走缓存。完整参数见运行契约。
