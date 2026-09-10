---
name: 4drawio
description: "数学建模非数据型图示绘制阶段。根据 ANALYSIS_MODELING_REPORT.md、RESULTS_REPORT.md 和已有 figures/ 生成技术路线图、子问题求解流程图、模型结构图、数据处理流程图等 DrawIO 图，并导出论文可引用 PDF。"
allowed-tools: Bash(*), Read, Write, Edit, Grep, Glob, Agent, WebSearch, WebFetch
---

# DrawIO 非数据图示绘制

## Formal grouped v3 分流

正式模式新 run 默认采用 [两次审批工作流](../_references/GROUPED_GATE_WORKFLOW.md)。先检查 `compliance/HUMAN_GATES.json` 的 schema：3.0 使用该文件的三阶段连续流程，本页以下逐 G1–G6 人工等待/approve 指令仅适用于旧 schema 2.0；数学、结果、页面、AI 披露检查仍执行。不存在 Gate 文件时由入口初始化 grouped v3；training/reference 继续原无人工门禁流程。


本 skill 承接 `3coding-visual`。它只负责论文中的**非数据型图示**，例如技术路线图、求解流程图、模型结构图、数据处理流程图、变量关系图、指标体系图等。

本阶段是条件模块。vNext run 只有当前 profile 的 `drawing` 阶段激活 `non-data-figures` 才调用本 skill，并先用 `_references/harness/scripts/validate_harness_profile.py --stage drawing --require non-data-figures` 校验；未激活时由编排器直接跳过，不为证明“已检查”而创建空图或冗余报告。旧项目没有 profile 时沿用下文的必要性判断，并记录 legacy 状态。

## 数学建模规范参考

如需领域判断，读取 `../_references/math_modeling_norms.md` 中的“图表与可视化”和“非数据图工具选择”小节。该文件只作为规范知识库，不要求为了凑数量生成额外图示。

正式赛题还必须读取 `../_references/knowledge/cards/foundations/problem-rules-first.md`；所有图示只能表达已经批准且符合当届题面、附件和官方更正的路线。

先读取 execution mode、artifact tier、capability snapshot 与 route ledger。本阶段不新增人工 Gate；确需绘图时用 `reasoning_route.py` 创建一个常规 `single` 有界任务，并在完成后复评。formal mode 还须验证 G1–G5；training_run 只表达已通过 G5 双审验证的路线与结论。Tier 1 只在图示确实提高论证时生成，不为满足模板凑图。若绘图暴露实质技术冲突，返回最早受影响阶段，不能用提高 effort 掩盖。

## 阶段边界

- 本阶段负责：DrawIO 源文件、非数据图 PDF、图示生成记录。
- 本阶段不负责：折线图、柱状图、散点图、热力图、箱线图、雷达图等数据图。这些由 `3coding-visual` 生成。
- 本阶段不重跑模型、不修改 `code/`，不改写 `reports/RESULTS_REPORT.md` 的数值结论。

formal mode 开始前运行：

```bash
python <本仓库实际路径>/_references/scripts/human_gate.py verify \
  --file compliance/HUMAN_GATES.json \
  --project-root . \
  --require G1 G2 G3 G4 G5 \
  --check-artifacts
```

正式模式校验失败时停止。如果绘图过程暴露出模型路线、数据口径或结果解释之间存在实质冲突，不得在图中自行修正；training_run 保留旧图和旧决策并自动回拨最早受影响阶段，formal mode 则失效最早受影响的 G2–G5 门禁。仅调整版式、配色、节点位置和不改变语义的简称不触发新版本或重新审批。

## 必须产出

在当前工作目录创建或更新：

```text
figures/
  fig_roadmap.drawio
  fig_roadmap.pdf
  fig_flow_q1.drawio
  fig_flow_q1.pdf
  ...
reports/DRAWIO_REPORT.md
```

如果某类图不需要生成，必须在 `reports/DRAWIO_REPORT.md` 中说明原因。是否生成 `fig_roadmap` 由实际解释需求决定。

读取这些文件的目的不是提取数据作图，而是理解论文方法、章节结构、子问题关系和已有图表，避免重复。

## 工作流程

### Step 1: 盘点已有图表和需求

先读取以下文件（存在则读取）：`reports/ANALYSIS_MODELING_REPORT.md`、`reports/RESULTS_REPORT.md`、`figures/` 目录列表。

然后从前序文档提取非数据图需求，输出一个清单：

```text
DRAWIO PLAN CHECKLIST:
[ ] fig_roadmap      技术路线图，放在问题重述/绪论
[ ] fig_flow_q1      问题一求解流程图
[ ] fig_flow_q2      问题二求解流程图
[ ] fig_flow_q3      问题三求解流程图
[ ] fig_pipeline     数据处理流程图
[ ] fig_model        模型结构/变量关系图
```

清单不是固定模板，要根据题目实际删减或增补。不要为了凑图生成无意义图示。

### Step 2: 判定图类型

常见图示选择：

| 图类型 | 文件名建议 | 适用场景 |
| --- | --- | --- |
| 技术路线图 | `fig_roadmap` | 展示整体解题路线、章节逻辑、方法串联 |
| 子问题求解流程图 | `fig_flow_q1`, `fig_flow_q2` | 展示单个子问题的输入、判断、算法、输出 |
| 数据处理流程图 | `fig_pipeline` | 展示数据清洗、特征构造、建模输入 |
| 模型结构图 | `fig_model` | 展示模块关系、变量关系、模型层次 |
| 指标体系图 | `fig_index_system` | 展示目标层、准则层、指标层 |
| 决策树/规则图 | `fig_decision_tree` | 展示分类规则、设备选择、策略分支 |

不要用 DrawIO 画这些图：

- 结果对比柱状图
- 预测误差曲线
- 灵敏度曲线
- 相关性热力图
- 分布图和箱线图

### Step 3: 生成 DrawIO 源文件

每张图一个 `.drawio` 文件，放在 `figures/`。

DrawIO 内容要求：

- 文字语言与论文语言一致。
- 节点文字短，必要时双行，不堆长句。
- 同类节点样式统一。
- 箭头方向清晰，避免交叉。
- 图中不写大段解释，解释留给论文正文。
- 不使用装饰性阴影和过度渐变。

生成大 XML 时，分段写入，避免截断。示例：

```bash
mkdir -p figures
cat << 'XMLEOF' > figures/fig_roadmap.drawio
<mxfile>
  <diagram name="Page-1">
    <mxGraphModel>
      <root>
        <mxCell id="0"/>
        <mxCell id="1" parent="0"/>
        <!-- nodes and edges -->
      </root>
    </mxGraphModel>
  </diagram>
</mxfile>
XMLEOF
```

### Step 4: 导出 PDF

优先用可用的 DrawIO 命令导出 PDF：

```bash
DRAWIO_BIN="$(command -v drawio 2>/dev/null || command -v draw.io 2>/dev/null || command -v draw.io.exe 2>/dev/null || true)"
if [ -n "$DRAWIO_BIN" ]; then
  "$DRAWIO_BIN" --export --format pdf --crop --output figures/fig_roadmap.pdf figures/fig_roadmap.drawio
else
  echo "DrawIO command not found; keep .drawio source and record export failure."
fi
```

如果无法导出 PDF，保留 `.drawio`，在 `reports/DRAWIO_REPORT.md` 记录失败原因和建议导出命令。

### Step 5: 自检和修复

每张图必须检查：

- `.drawio` 文件非空。
- 若导出成功，`.pdf` 文件非空。
- 节点没有明显重叠。
- 箭头不穿过核心节点。
- 字号、颜色、边框风格一致。
- 文件名和图意一致。
- 没有与 `3coding-visual` 的数据图重复。

发现问题要修 `.drawio` 并重新导出，不要只在报告里解释。

### Step 6: 写生成记录

创建 `reports/DRAWIO_REPORT.md`，至少包含：

```markdown
# DrawIO 图示生成报告

## 图示清单
| 文件 | 类型 | 来源依据 | 用途 | 状态 |
| --- | --- | --- | --- | --- |

## 未生成图示及原因

## 导出与自检记录

## 给论文阶段的嵌入建议
```

嵌入建议只说明每张图适合放入哪个章节和建议 caption，不生成 `*_typst_includes.typ`。最终图表嵌入由 `5writing` 按当前 tier 使用 Markdown 或 Word 完成。

## 质量要求

- 图示服务论文论证，不为装饰而画。
- 每张图必须能对应到`reports/ANALYSIS_MODELING_REPORT.md` 中的真实方法。
- 数据型图表不得在本阶段重复生成。
- 论文阶段引用的非数据图都应有 `.drawio` 源文件和 PDF，或者在 `reports/DRAWIO_REPORT.md` 说明导出失败。
