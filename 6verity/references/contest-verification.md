> **grouped v3 执行映射**：本页保留 Word/PDF/页面、结果与披露的技术检查。HUMAN_GATES.json 为 3.0 时，以 `_references/GROUPED_GATE_WORKFLOW.md` 为审批权威；进入写作/终审只验证路线批准及 G3/G4 技术检查，并直接验证冻结 G5 bundle。不要在论文尚未生成前调用 `--require G5`（v3 的 delivery checkpoint 在完整材料形成后才记录）；不要执行本页 legacy 的逐 Gate approve/等待。完整最终审核后 `grouped_gate.py check --phase delivery`，展示整包，再且仅再请求一次最终批准。最终确认后才能 `verify --require G1 G2 G3 G4 G5 G6`。

# 条件交付流程

仅在入口选择相应 tier 后读取。以下脚本/相对路径以 skill 根目录或标注的仓库根为基准。保留旧检查项作为迁移回滚路径。

## Tier 3 输入

1. `paper/revisions/WORD_LOOPS.json` 和全部 loop manifest；
2. 最新冻结的 Word loop；
3. `submission/论文.docx`、`submission/论文.pdf` 和 `submission/FINAL_DELIVERY.json`；
4. `reports/ANALYSIS_MODELING_REPORT.md`、`RESULTS_REPORT.md`、`DRAWIO_REPORT.md` 和 `STRATEGY_CONTEXT.md`；
5. `results/results.json`；
6. `compliance/HUMAN_GATES.json`、审批包和回拨快照；
7. `compliance/AI_USAGE_LOG.md`、论文 AI 声明和使用 AI 时的 `AI工具使用详情.pdf`；
8. `code/`、`results/`、`figures/` 和支撑材料压缩包。

## Step 0：验证 G1–G5（仅 Tier 3）

```bash
python <本仓库实际路径>/_references/scripts/human_gate.py verify \
  --file compliance/HUMAN_GATES.json \
  --project-root . \
  --require G1 G2 G3 G4 G5 \
  --check-artifacts
```

失败时立即停止。不得通过编辑 JSON、删除事件或重新初始化来绕过未审批、已失效或哈希变化。

G1–G5 验证通过后、开始最终跨材料审核前，为 G6 创建独立 route task。formal 默认请求 `ultra/ensemble`，但只有数学正确性、模型、数值、图表、摘要正文、论证、评委视角和 AI 披露确实由不同上下文独立审核，并有 topology receipt 时才能记为 ensemble；材料多或耗时长本身不是证据。运行时不能兑现时显式降级为 `single`，按逐项清单和事实源哈希做保守终审；局部技术异常回拨 G1–G5，不用高 effort 掩盖。

G6 审核开始前必须取得 `reasoning_effort_interface` 的有效设置回执并 apply；请求与实际不同则显式 degraded。审核结束绑定审查输出并 reassess，之后才生成 G6 审批包。用户拒绝提高 effort 时不反复请求，采用已声明回退；无论实际强度如何都不能替代 G6 审批。若终审发现重大问题，失效最早受影响 Gate，回拨后创建新的有界 route task。

随后验证统一结果事实源：

```bash
python <本仓库实际路径>/_references/knowledge/scripts/validate_results.py \
  results/results.json --project-root . --check-artifacts --final
```

Schema 通过只是结构门槛；仍需复算代码并检查数值含义。

## Step 1：验证 Word loops 和双格式最终交付

先验证所有冻结 loop 未被覆盖，再验证最新 loop 的最终清理和交付文件：

```bash
python <本仓库实际路径>/5writing/scripts/word_loop.py verify \
  --registry paper/revisions/WORD_LOOPS.json \
  --project-root . \
  --loop-id all

python <本仓库实际路径>/5writing/scripts/word_loop.py verify \
  --registry paper/revisions/WORD_LOOPS.json \
  --project-root . \
  --loop-id latest \
  --final-ready \
  --final-manifest submission/FINAL_DELIVERY.json
```

检查器必须确认：

- 每轮都有版本化 DOCX、同轮 PDF、逐页 PNG、变更摘要和策略上下文快照；
- 冻结文件及 manifest 哈希未变化；
- 最终 Word 可编辑，无批注、未处理修订、个人元数据、自定义属性、修订会话标识或只读保护；
- 最终 PDF 与 Word 来自同一已通过视觉 QA 的 loop；
- 最终 DOCX 和 PDF 同时存在，任一文件变化都会失败。

## Step 2：CUMCM 2026 专项合规

CUMCM/国赛项目以 Word 作为论文源运行：

```bash
python <本 skill 实际路径>/scripts/check_cumcm_2026.py \
  --competition-year 2026 \
  --paper-source submission/论文.docx \
  --ai-used yes \
  --ai-log compliance/AI_USAGE_LOG.md \
  --ai-details-pdf submission/supporting-materials/AI工具使用详情.pdf \
  --paper-pdf submission/论文.pdf \
  --support-archive <实际 ZIP/RAR 路径> \
  --body-pages <正文实际页数> \
  --final
```

未使用 AI 时传 `--ai-used no` 并采用官方未使用声明。无支撑材料时按官方措辞在附录说明并省略压缩包参数。脚本检查 DOCX 正文、目录、AI 声明顺序、附录、匿名性、正文页数、Word/PDF 大小和支撑材料。

本工作流最终同时交付 Word 和 PDF；如果竞赛上传入口规定只提交一种论文文件，应按当年系统要求选择上传，不在同一入口擅自提交两份。

## Step 3：Word 结构和编辑状态

对最终 DOCX 做结构检查：

- OOXML 包、正文、样式、图片关系和字体引用完整；
- 使用真实标题层级、编号、题注和交叉引用；
- 没有手工空格模拟缩进、文本伪编号或损坏字段；
- 图表、公式和表格没有缺失资源；
- CUMCM 不含目录，摘要页和页码符合规范；
- 没有占位符、内部路径、工作流文件名或工具引用标记；
- 没有批注、悬而未决的修订、文档保护和个人元数据。

结构脚本通过不代表视觉通过，两者都必须执行。

## Step 4：内容与策略一致性

逐项核对：

- Word 中的题意、假设、模型、目标函数和约束与 G1–G3 及建模报告一致；
- 数据清洗、参数、随机种子和运行口径与 G4 及代码一致；
- 数值、排名、误差、图表、约束和结论与 `results/results.json`、其文件哈希、`RESULTS_REPORT.md` 及 G5 一致；
- 摘要、正文、表格、图注和结论中的每个关键数字都能回到唯一 `result_id`，且单位与舍入不改变含义；
- `STRATEGY_CONTEXT.md` 中未解决的问题没有被论文擅自写成确定结论；
- 用户的策略询问没有被错误记录为批准或修改；
- 所有公开资料和参考文献真实存在并在正文标注。

发现冲突时不得在 Word 里发明折中结论。失效最早受影响的 G1–G5，回到相应阶段重新计算或审批，然后创建新的 Word loop。

## Step 5：独立重新渲染和逐页视觉检查

从 `submission/论文.docx` 重新渲染 PDF 和逐页 PNG到新的临时目录。不得直接信任写作阶段留下的截图；验收阶段需要独立复核。

使用 documents skill 的 `render_docx.py --emit_pdf`。在 100% 缩放下检查每一页：

- 页面数、A4 尺寸、页边距、页码、摘要页和附录；
- 标题、正文、公式、上下标、参考文献和中英文字体；
- 表格越界、重复表头、跨页断裂、单元格裁切；
- 图片清晰度、题注、图文对应和交叉引用；
- 重叠、裁切、乱码、孤行和异常大片空白；
- Word 导出 PDF 与最终交付 PDF 的页面数和视觉内容是否一致。

所有页面必须检查，不能抽查。发现视觉问题时只修复 Word，重新冻结 loop、finalize 并复核；不得直接修补 PDF。

渲染器不可用时必须写 `FAIL`，因为用户明确要求 PDF 作为视觉合规分析载体，最终交付不能跳过这一环。

## Step 6：代码、图表和支撑材料

- 从统一入口轻量或完整复现代码；
- 检查程序输出与 Word 数值一致；
- 确认图表源数据、Word 内嵌副本和原 PDF 图表语义一致；
- 检查附录列出全部支撑材料和完整代码；
- 检查 ZIP/RAR 内容、文件名、大小和匿名性；
- 使用 AI 时确认压缩包包含准确命名的 `AI工具使用详情.pdf`。

## Step 7：AI 使用一致性

交叉核对 `AI_USAGE_LOG.md`、G1–G5 决策、`STRATEGY_CONTEXT.md`、论文声明和 `AI工具使用详情.pdf`：

- 实际用途类别一致；
- 采纳、人工修改和核验情况有证据；
- 策略问答中的 AI 解释没有被漏记为实际影响作品的使用；
- 对外材料保持必要、匿名，不泄露内部聊天、哈希或回拨路径；
- 人工门禁审批没有被用来替代真实 AI 用途披露。

## Step 8：生成待批准验收报告

写入 `reports/VERIFY_REPORT.md`：

```markdown
# 验证和验收报告

## 结论
PENDING_G6 / FAIL

## Word loops 与最终双格式

## G1–G5 与策略一致性

## CUMCM/比赛格式

## 数值、图表和引用一致性

## DOCX 结构与编辑状态

## PDF 逐页视觉检查

## 代码与支撑材料

## AI 使用合规

## 警告和仍需处理的问题
```

技术检查全部通过但尚未取得 G6 时，结论只能是 `PENDING_G6`。

## Step 9：G6 最终人工审批

生成 G6 审批包，至少列出：

- 最终 Word 与 PDF 的文件名、哈希、页数和同源 loop；
- Word 可编辑状态、元数据清理和视觉 QA 结论；
- 支撑材料、AI 声明、详情 PDF 和全部 WARN；
- “按当前版本提交”“返回修复后重新审批”两个真实选项；
- 比赛上传入口最终应选择的格式。
- G6 路由评估编号、AI 建议、automatic 的事先告知与运行时回执或 manual 的用户选择、实际回退措施；明确该记录不是提交批准，且没有运行时回执时不得写成系统已切换。

把审批包呈现给用户并停止。之前对模型、写作或某个 loop 的批准不能扩张成最终提交授权。

用户明确批准当前版本后，用 `human_gate.py approve --gate G6` 记录，并至少把以下文件作为审批 artifact：

- `submission/论文.docx`；
- `submission/论文.pdf`；
- `submission/FINAL_DELIVERY.json`；
- 支撑材料压缩包（存在时）；
- `AI工具使用详情.pdf`（使用 AI 时）。

最后运行：

```bash
python <本仓库实际路径>/_references/scripts/human_gate.py verify \
  --file compliance/HUMAN_GATES.json \
  --project-root . \
  --require G1 G2 G3 G4 G5 G6 \
  --check-artifacts
```

只有返回 `RESULT: PASS` 才把验收报告改为 `PASS`。G6 后任何 Word、PDF、manifest 或支撑材料变化都必须先失效 G6，重新渲染、复核和审批。

## 硬错误

- 缺少 Word loop 注册表、版本化 DOCX 或策略上下文快照；
- 覆盖已交付 loop，或冻结文件/manifest 哈希变化；
- 最终 DOCX/PDF 缺一，或不来自同一通过 QA 的 loop；
- PDF 被单独编辑，或只检查 PDF 没有回到 Word 修复；
- 最终 Word 有占位符、批注、修订、个人元数据、自定义属性或保护；
- 没有逐页检查全部 PDF 页面；
- G1–G6 缺失、未批准、已失效、越级、审计链损坏或 artifact 哈希变化；
- 用户策略询问被当作批准或修改指令；
- Word 的模型、数值、图表、结论或引用与真实产物冲突；
- CUMCM 目录、页数、大小、匿名性、附录或 AI 声明不合规；
- 已使用 AI 但日志、声明、详情 PDF 或人工核验证据不一致；
- 代码不可运行，必要支撑材料缺失或与论文不符；
- `results/results.json` 缺失、契约/哈希/引用校验失败、存在 NaN/Infinity，或论文关键数值无法回到 `result_id`；
- G6 未明确批准却写 `PASS` 或“提交就绪”。

## 警告

- 备用图片未引用；
- 某章节过短、图表解释不足或参考文献偏少；
- Word 与 LibreOffice/Word 渲染存在轻微但不影响内容的分页差异；
- 完整复现耗时过长，仅完成有依据的轻量复现。
