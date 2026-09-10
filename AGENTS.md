# 数学建模 Harness 调用入口

先读取 README.md，再读取 1start-mathmodel/SKILL.md；按当前模式与阶段按需加载其他 SKILL.md。
本仓库根目录即协议里的 `<repo-root>`，可直接作为活动技能根目录，不依赖维护者的安装路径。

- 首次运行按 README 安装 Python 依赖，执行 `python harness.py setup`。
- 将题目、附件、计算与论文产物放在仓库外的独立项目目录。
- 不假定已安装其他 Agent 插件，不假定模型或推理档位可切换。依据当前运行时真实能力生成快照；不可伪造独立评审或审批回执。
- 通用知识入口为空白公开配置；历史案例、来源资料与训练记录不随仓库提供。
- 修改公共代码后执行 `python -m pytest -q`。发布前维护 PUBLIC_MANIFEST.json 与 .gitignore 的逐文件白名单，并运行 `python tools/audit_public.py`。
- 禁止把任何实际任务文件、二进制文档、密钥、个人机器路径或私有历史加入白名单。
