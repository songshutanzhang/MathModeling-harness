> **grouped v3 执行映射**：本页保留 Word/PDF/页面、结果与披露的技术检查。HUMAN_GATES.json 为 3.0 时，以 `_references/GROUPED_GATE_WORKFLOW.md` 为审批权威；进入写作/终审只验证路线批准及 G3/G4 技术检查，并直接验证冻结 G5 bundle。不要在论文尚未生成前调用 `--require G5`（v3 的 delivery checkpoint 在完整材料形成后才记录）；不要执行本页 legacy 的逐 Gate approve/等待。完整最终审核后 `grouped_gate.py check --phase delivery`，展示整包，再且仅再请求一次最终批准。最终确认后才能 `verify --require G1 G2 G3 G4 G5 G6`。

# 条件交付流程

仅在入口选择相应 tier 后读取。以下脚本/相对路径以 skill 根目录或标注的仓库根为基准。保留旧检查项作为迁移回滚路径。

## Tier 2/3 输入

- `reports/ANALYSIS_MODELING_REPORT.md`；
- `reports/RESULTS_REPORT.md`；
- `results/results.json`；
- `reports/DRAWIO_REPORT.md`（存在时）；
- `reports/STRATEGY_CONTEXT.md`；
- Tier 2 training milestone 的 G2/G5 冻结证据，或 Tier 3 evaluation/live 项目的 `compliance/HUMAN_GATES.json` 与 G1–G5 审批包；
- `compliance/AI_USAGE_LOG.md`；
- `figures/` 中的真实图表和生成数据；
- 上一轮 DOCX或用户直接修改后的 DOCX。

## Tier 2/3 必须产出

```text
paper/
  论文_working.docx
  revisions/
    WORD_LOOPS.json
    loop-NNN/
      论文_loop-NNN.docx
      CHANGESET.md
      STRATEGY_CONTEXT.md
      LOOP_MANIFEST.json
  qa/
    loop-NNN/
      论文_loop-NNN.pdf
      page-*.png
reports/
  STRATEGY_CONTEXT.md
submission/
  论文.docx
  论文.pdf
  FINAL_DELIVERY.json
```

中间 loop 的 Word 必须可编辑。已经交付的 loop 不得覆盖；用户反馈进入下一编号。

## Step 0：验证 G1–G5

Tier 2 的 training milestone 先验证 G2/G5 冻结证据与语义 manifest，不要求人工 G1–G6；Tier 3 的 evaluation_run/live_competition/release_candidate 执行下列人工门禁校验。

```bash
python <本仓库实际路径>/_references/scripts/human_gate.py verify \
  --file compliance/HUMAN_GATES.json \
  --project-root . \
  --require G1 G2 G3 G4 G5 \
  --check-artifacts
```

失败时停止定稿。可以整理不改变技术含义的局部排版，但不能把未批准模型或候选结论写成最终正文。

本阶段不新增独立 Gate，也不复用 G1–G5 已结算 route。普通 Word 写作、排版与逐页修复创建自身的常规 `single` route task；若写作暴露题意、模型、数值或结论问题，Tier 2 training milestone 保留当前 loop 并按冻结证据自动回拨，Tier 3 evaluation/live 项目失效最早受影响 Gate 并回到其阶段创建新 route。G6 route 由 `6verity` 在审核前独立评估，写作 loop 完成不能替代 G6 路由或批准。

同时执行结果事实源验收；失败时不得开始写入关键数值：

```bash
python <本仓库实际路径>/_references/knowledge/scripts/validate_results.py \
  results/results.json --project-root . --check-artifacts --final
```

## Step 1：恢复最小必要上下文

先读取 `reports/STRATEGY_CONTEXT.md`、当前冻结决策编号和上一轮 `CHANGESET.md`：Tier 2 使用 G2 route selection 与 G5 Decision，Tier 3 使用 G1–G5 审批编号。按本轮范围只加载相关报告小节和论文页，不默认把整篇论文、全部聊天和所有历史审批包同时塞入上下文。

如果 `STRATEGY_CONTEXT.md` 尚不存在，从 `../../_references/strategy_context_template.md` 创建并替换占位符。它是活跃策略账本，不是完整对话归档。

每轮开始时记录：

- 本轮编号、输入 Word 和上一交付版本；
- 本轮内容修改、排版修改和明确不处理事项；
- 当前 G2/G5 冻结决策编号（Tier 2）或 G1–G5 审批编号（Tier 3）；
- 尚待用户回答的策略问题。

## Step 2：初始化或吸收 Word 工作稿

当前模板/转换链首次使用时，先用 `../scripts/word_conversion_canary.py` 的短样例检验原生分式、根式、下标、字段引用、合并表头及源码缩进；经真实渲染与逐页目视检查后再扩展全文。该脚本只输出结构检查，不能自报视觉通过。模板或转换器改变后重做适用的短样例。

### 新项目

优先使用比赛官方、赛区或用户提供的 DOCX。只有 `run/CONTEST_RULES.json` 选中 2026 CUMCM 且没有上位 Word 模板时，才从 `../assets/CUMCM_2026_论文模板.docx` 复制为 `paper/论文_working.docx`，按 `cumcm_word_template.md` 替换全部 `{{TOKEN}}` 字段。历史年份使用该年份的规则来源；其他比赛没有 Word 模板时依据当前比赛格式创建工作稿。不得让现有 Typst/LaTeX 模板成为第二正文源。

初始化 loop 注册表：

```bash
python <本 skill 实际路径>/scripts/word_loop.py init \
  --registry paper/revisions/WORD_LOOPS.json \
  --project-root . \
  --working-docx paper/论文_working.docx
```

注册表存在时不得重新初始化。

### 用户修改已有 Word

保留用户上传或修改文件的原件，复制为新的 `论文_working.docx`。与上一轮执行文本和逐页视觉 diff，区分内容变化与分页噪声。不要回滚用户修改；遇到含义不明、数值冲突或模型策略变化时先询问。

如果修改触及题意、假设、算法、目标约束、数据口径或关键结论，Tier 2 保留当前 loop 并回拨最早受影响的冻结阶段，Tier 3 失效最早受影响的 G1–G5、重新审批后再继续本轮。

## Step 3：撰写与编辑 DOCX

使用真正的 Word 样式、标题层级、题注、编号和交叉引用，不用手工空格、假标题或文本编号模拟结构。表格使用明确列宽和重复表头；图片、公式和题注尽量保持同页。

正文必须来自前序真实产物：

- 数值、单位、区间、排名和约束状态来自已通过校验的 `results/results.json`；
- `RESULTS_REPORT.md` 只提供与 `result_id` 对应的解释、方法和上下文，二者冲突时停止并回到计算阶段重新生成；
- 模型公式与算法来自已批准的建模报告；
- 图表来自 `figures/` 及对应生成数据；
- 不得为行文完整而编造数值、参考文献、实验或结论。

每个进入摘要、结论、表格或图注的关键数字都要在本轮 `CHANGESET.md` 记录 `result_id`。舍入只发生在展示层，保留原单位、方向和不确定性；禁止从图片像素、旧 Word 或聊天记录手抄数值。

Word 无法稳定嵌入现有 PDF 图表时，保留 PDF 源文件，并在 `figures/word/` 生成兼容的 SVG/EMF 或足够分辨率的 PNG 副本。不得通过截图引入模糊文字；图表副本必须与源图同数据、同版本。

### CUMCM 2026 结构

- 电子版第一页为摘要专用页，页码从 1 开始；
- 不生成目录；
- 正文不超过 30 页，附录另计；
- AI 工具使用声明位于参考文献之前；
- 附录包含支撑材料文件列表和全部完整可运行代码；
- 正文和文档元数据均不得泄露姓名、学校或赛区。

## Step 4：策略问答 loop

用户可能在任意 loop 询问模型策略。回答前读取 `STRATEGY_CONTEXT.md`、相关人工审批包及对应分析/结果小节，并优先说明：

1. 当前采用什么方案；
2. 为什么采用，依据和验证证据是什么；
3. 哪些备选方案仍然可行；
4. 当前方案的假设、风险和失败条件；
5. 如果改变策略，会影响哪些门禁、代码、结果、图表和论文页。

用户的询问不等于批准、否决或修改指令。只回答问题时更新账本中的“最近策略问答”，不改变模型和 Word。用户明确要求采用、替换、回退或重新计算时，才失效最早受影响门禁，并把实施放入下一 loop。

闭环讨论压缩成一到三条结论；保留证据路径和决策编号，不复制完整聊天，以便为下一次策略追问预留上下文。

## Step 5：每轮 DOCX 渲染与视觉 QA

每个有意义的编辑批次结束后，都必须执行：

```text
DOCX → PDF + page-*.png → 逐页 100% 检查 → 修复 DOCX → 重新渲染
```

使用 documents skill 捆绑的 `render_docx.py`，通过本 skill 的包装命令渲染。包装器会在渲染前后核对 DOCX 哈希，并为 PDF 和逐页 PNG 生成 `RENDER_RECEIPT.json`：

```bash
python <本 skill 实际路径>/scripts/word_loop.py render \
  --project-root . \
  --docx paper/论文_working.docx \
  --output-dir <本轮临时渲染目录> \
  --renderer <documents skill 实际路径>/render_docx.py
```

渲染输出必须写入新的临时目录，不能直接覆盖已经冻结的 `paper/qa/loop-NNN/`。

逐页检查：

- 页面数量、页边距、页码、摘要页和附录起始位置；
- 标题、正文、公式、上下标和中英文字体；
- 表格越界、单元格裁切、重复表头和跨页断裂；
- 图片清晰度、题注、交叉引用和图文相邻关系；
- 孤行、大片异常空白、重叠、裁切和缺字；
- CUMCM 无目录、匿名性及正文页数。

所有页面都要有有效检查，不能只抽查。版式敏感修改后必须重新渲染。首轮全页检查后可用 word_loop.py delta-plan 对比上一已通过 manifest：仅复用相同页位且 PNG 哈希相同的页；变化/新增页逐页检查，删除页检查内容完整性。用 --delta-qa-receipt 保存证据后才能冻结；最终独立重渲染保持原要求。若渲染器不可用，本轮不得声称视觉 QA 通过；可以交付明确标记为“未完成视觉检查”的 Word 草稿，但不能冻结为 `qa_passed` 或进入 G6。

## Step 6：冻结并交付当前 loop

准备无占位符的 `CHANGESET.md`，至少记录：

- 内容和排版变更；
- 用户策略问题及本轮回答结论；
- 是否触发 G1–G5 失效或重新审批；
- 视觉 QA 页数、修复项和剩余问题。

全部页面通过后运行：

```bash
python <本 skill 实际路径>/scripts/word_loop.py snapshot \
  --registry paper/revisions/WORD_LOOPS.json \
  --project-root . \
  --loop-id loop-NNN \
  --docx paper/论文_working.docx \
  --render-receipt <临时渲染目录>/RENDER_RECEIPT.json \
  --all-pages-reviewed \
  --strategy-context reports/STRATEGY_CONTEXT.md \
  --changeset <本轮变更文件>
```

每轮向用户交付 `论文_loop-NNN.docx`。PDF 可以同时提供作视觉对照，但必须明确它是同轮 DOCX 的只读排版快照。等待反馈时不要预先创建下一个空 loop。

## Step 7：参考文献与 AI 合规

只使用真实可核验的参考文献，并在正文引用处建立 Word 交叉引用或规范编号。引用公开资料必须能回到原始来源。

2026 CUMCM 项目还要：

1. 从 `AI_USAGE_LOG.md` 和 G1–G5 决策交叉核对实际 AI 用途；
2. 在参考文献之前写官方 AI 使用声明；
3. 使用 AI 时生成独立的 `AI工具使用详情.pdf`；
4. 对外只保留必要、匿名摘要，不公开内部审批聊天、哈希或回拨路径；
5. 人工审批不能替代 AI 实际用途披露。

## Step 8：最终化

最终 loop 在冻结前必须：

- 处理完所有批注和修订，不留悬而未决的编辑痕迹；
- 清理作者、最后修改者、自定义属性和修订会话标识；
- 保持 Word 可编辑，不设置只读保护；
- 从清理后的最终 Word 重新导出 PDF 和全部页面 PNG；
- 再次逐页检查，不能复用清理前的视觉结论。

冻结最终 loop 后运行：

```bash
python <本 skill 实际路径>/scripts/word_loop.py verify \
  --registry paper/revisions/WORD_LOOPS.json \
  --project-root . \
  --loop-id latest \
  --final-ready

python <本 skill 实际路径>/scripts/word_loop.py finalize \
  --registry paper/revisions/WORD_LOOPS.json \
  --project-root . \
  --loop-id latest \
  --output-dir submission
```

最终产物必须同时存在：

- `submission/论文.docx`：干净、匿名、可编辑；
- `submission/论文.pdf`：从同一最终 loop 的 DOCX 导出；
- `submission/FINAL_DELIVERY.json`：记录来源 loop、哈希、页数和视觉 QA 状态。

最终文件生成后交给 `6verity` 做一致性和 G6 审批。G6 前不得声称“提交就绪”。竞赛上传入口只接受一种格式时，按当年规则选择上传文件，不把本地双格式交付误解为必须同时上传。

## 可选的 Typst/LaTeX 辅助源

只有用户明确要求时，才可使用 `templates/` 下现有 Typst/LaTeX 模板辅助公式迁移或样式参照。必须满足：

- Word 始终是正文唯一事实源；
- 不维护两个需要人工同步的完整正文；
- 每轮交付和最终交付仍以 DOCX 为主、PDF 为其导出物；
- 辅助源不得进入论文或支撑材料，除非比赛明确要求。

## 硬错误

- 当前 loop 未交付版本化 DOCX；
- 直接修改 PDF 或从 PDF 回填正文；
- PDF 不是由同轮 DOCX 导出；
- 只抽查部分页面却标记视觉 QA 通过；
- 覆盖已经交付的 loop；
- 策略提问被错误视为用户批准或改模指令；
- Word 与结果、门禁、图表或 AI 日志不一致；
- 缺少 `results/results.json`、结果契约未通过，或论文关键数字没有 `result_id`；
- 最终只交付 Word 或只交付 PDF；
- 最终 Word 仍有批注、修订、个人元数据、保护或占位符。
