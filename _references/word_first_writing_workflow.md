# Word-first 数学建模论文写作循环

本规范只对 Artifact Governance Tier 2/3 生效。Tier 1 training fast path 使用 `paper/paper.md` 作为语义交付，不创建 Word loop、不渲染页面，也不得声称提交就绪；Writer 仍必须从 semantic artifact package 和 result_id 写作，不能改变 Solver 数值事实。

## 单一事实源

论文正文的唯一可编辑事实源是 `paper/论文_working.docx`。Typst/LaTeX 可在用户明确要求时用于公式或模板迁移辅助，但不能与 DOCX 并列成为两个需要人工同步的正文源。PDF 只能由当前 DOCX 导出，不能反向编辑后再合并回 Word。

## 项目产物

```text
paper/
  论文_working.docx
  revisions/
    WORD_LOOPS.json
    loop-001/
      论文_loop-001.docx
      CHANGESET.md
      LOOP_MANIFEST.json
    loop-002/
      ...
  qa/
    loop-001/
      论文_loop-001.pdf
      page-001.png
      page-002.png
      ...
reports/
  STRATEGY_CONTEXT.md
submission/
  论文.docx
  论文.pdf
  FINAL_DELIVERY.json
```

已经交付的 `paper/revisions/loop-NNN/` 和对应 `paper/qa/loop-NNN/` 不得覆盖。用户反馈和直接修改从新 loop 开始。

## 每个 loop 的固定流程

1. **恢复上下文**：读取 `USER_WORKFLOW_PREFERENCES.md`、`STRATEGY_CONTEXT.md`、当前 G1–G5 决策和上一轮 `CHANGESET.md`，只按需加载论文相关章节。
2. **定义本轮范围**：列出内容修改、策略问题、排版修改和不在本轮处理的事项。策略发生变化时先失效对应人工门禁。
3. **编辑 Word**：从上一轮 DOCX 或用户修改版复制为 `论文_working.docx`，做最小、可追踪的修改。不得从 PDF 回填正文。
4. **结构检查**：检查标题层级、分页、图表、公式、交叉引用、参考文献、占位符和匿名性。
5. **渲染**：通过 `5writing/scripts/word_loop.py render` 调用 documents skill 的 `render_docx.py --emit_pdf`，将当前 DOCX 导出为 PDF 和逐页 PNG，并记录渲染前后 DOCX 哈希及输出哈希。
6. **视觉检查**：在 100% 缩放下检查每一页，修复裁切、重叠、空白、表格、图片、公式、字体、页眉页脚和页码问题；每次版式敏感修改后重新渲染。
7. **冻结轮次**：只有全部页面检查通过，且 `RENDER_RECEIPT.json` 仍与当前 DOCX、PDF、PNG 一致，才把 DOCX、PDF、PNG、变更摘要、策略上下文哈希和页数写入新 `loop-NNN`，状态为 `qa_passed`。
8. **交付**：每轮向用户交付版本化 DOCX 和 PDF 视觉快照，但必须标注为同轮排版快照，不作为可编辑正文。
9. **吸收反馈**：用户提问先回答并更新策略上下文；用户明确修改或上传修改版 DOCX 时，创建下一轮，不覆盖旧轮次。

## 策略上下文预算

`reports/STRATEGY_CONTEXT.md` 是策略问答的活跃上下文，不是完整聊天归档。保持以下内容：

- 当前 G1–G5 决策编号和结论；
- 当前采用策略及三至五条关键依据；
- 仍有现实可能采用的备选方案；
- 关键假设、风险、失败判据和验证证据路径；
- 最近用户问题、回答结论和是否触发变更；
- 下一次需要用户决定的事项。

闭环讨论压缩成结论，不复制整段对话。回答策略问题时优先加载相关审批包、分析报告或结果报告的小节；只有发现冲突才扩展上下文。用户提问不自动改变门禁状态。

## 用户直接修改 Word

- 保留用户文件原件，复制为下一轮 working 文件。
- 对上一交付版和用户修改版执行文本与逐页视觉 diff，区分内容变化与重排噪声。
- 不回滚用户修改；对不明确、影响模型含义或数值一致性的改动先询问。
- 用户修改触及假设、算法、目标约束、数据口径或结论时，失效最早受影响的 G1–G5 并重新审批。

## 最终化

最终 Word 必须：

- 无占位符、未处理批注和悬而未决的修订；
- 清理作者、最后修改者、自定义属性和修订会话标识等个人元数据；
- 保持可编辑，不设置只读保护；
- 通过 DOCX 结构检查、逐页视觉检查和匿名性检查。

最终 PDF 必须从最终 Word 在同一 finalization 操作中导出。最终 Word 与 PDF 同时写入 `submission/` 并记录哈希、页数、来源 loop 和视觉 QA 状态。G6 必须同时锁定两者；其中任一文件变化都需要重新导出、复核和审批。
