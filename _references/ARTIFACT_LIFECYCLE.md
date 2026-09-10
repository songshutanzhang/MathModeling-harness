# 流式产物生命周期与安全清理

运行产物分为 `scratch → produced → promoted/frozen → disposable → deleted`。Solver 可把大体积中间输出写入 run-local `scratch/`，但进入论文、结果或审计链的内容必须先 promotion：复制/生成到稳定路径、记录 SHA-256、父产物和生成入口，再允许清理 scratch。

禁止仅凭扩展名、目录名或“看起来没用”删除。真题、附件、论文全文、清洗后的唯一数据、results、figures、冻结快照、Word revisions、manifest、AI 日志和来源账本默认受保护。

未来 run 使用：

```bash
python _references/harness/scripts/artifact_lifecycle.py record --ledger run/ARTIFACT_EVENTS.jsonl ...
python _references/harness/scripts/artifact_lifecycle.py verify --ledger run/ARTIFACT_EVENTS.jsonl
```

清理必须两阶段：先生成只读计划并审阅，再用计划文件的 SHA-256 精确确认；目标变化、哈希变化、符号链接、越出工作区或缺少 durable replacement 时拒绝执行。

```bash
python _references/harness/scripts/cleanup_artifacts.py inventory --project-root .
python _references/harness/scripts/cleanup_artifacts.py validate-plan --project-root . --plan cleanup-plan.json
python _references/harness/scripts/cleanup_artifacts.py apply --project-root . --plan cleanup-plan.json --confirm-plan-sha256 <HASH>
```

旧 `.tmp/`、OCR 与页图没有 lifecycle ledger 时只进入 inventory，不自动删除；应先证明已被文本、哈希或正式产物替代。
