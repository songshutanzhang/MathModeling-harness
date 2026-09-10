# MathModeling Harness

可供 Agent 直接读取和调用的数学建模工作流：题意冻结 → 候选建模 → 求解与验证 → 图示 → 写作 → 交付检查。包含阶段 Skills、Python 运行器、审批与恢复协议、结果合同和回归测试。

**这是纯工作流发行版。没有题库、论文、比赛附件、训练/评测记录、学习笔记、资料索引或模型密钥。**

## 快速开始

需要 Python 3.11+ 和 Git。Windows、Linux、macOS 都可调用核心脚本。

```bash
git clone https://github.com/songshutanzhang/MathModeling-harness.git
cd MathModeling-harness
python -m venv .venv
```

激活虚拟环境：Windows PowerShell 用 `.venv/Scripts/Activate.ps1`；Linux/macOS 用 `source .venv/bin/activate`。也可直接调用该环境内的 Python，无需激活。

```bash
python -m pip install -r requirements.txt
python tools/audit_public.py
python harness.py setup
python harness.py check
python harness.py test
python harness.py smoke --output-dir ../mathmodel-smoke
```

`setup` 从已审查源码生成空白 Word 模板与模块矩阵；这些本地产物被 Git 忽略。`check` 核验阶段入口引用与 Python 依赖；它不认证模型能力、外部排版程序或数学结论。`smoke` 必须使用新的输出目录，以合成输入验证运行、恢复和候选检查。

## 让其他 Agent 调用

把下面的指令交给能读本地文件、执行 Python 的 Agent：

> 请读取此仓库的 AGENTS.md 和 1start-mathmodel/SKILL.md，以此仓库为 Harness 根目录。在仓库外创建赛题项目，使用我提供的题目与附件，先核验依赖和实际模型能力，再按工作流执行。不要下载或假定存在历史案例资料。

仓库自身包含完整相对引用；无需复制到某个厂商的全局 skills 目录。若宿主只能从特定目录发现技能，请将**整个仓库目录结构**作为一个根目录提供给它，避免只复制六个入口文件而遗漏 `_references`。模型服务与工具权限由宿主 Agent 提供，本仓库不是独立的大模型客户端。

| 阶段 | 入口 |
| --- | --- |
| 编排与模式 | [1start-mathmodel](1start-mathmodel/SKILL.md) |
| 分析与建模 | [2analysis-modeling](2analysis-modeling/SKILL.md) |
| 求解与数据图 | [3coding-visual](3coding-visual/SKILL.md) |
| 非数据图 | [4drawio](4drawio/SKILL.md) |
| 论文写作 | [5writing](5writing/SKILL.md) |
| 验证与交付 | [6verity](6verity/SKILL.md) |

核心运行器：`python harness.py run --help`。完整流程见 [运行契约](_references/harness/RUNTIME_CONTRACT.md) 与 [执行说明](_references/harness/WORKFLOW_UPGRADE.md)。训练输入由使用者自行提供；正式模式依据真实能力与适用规则执行，缺失能力会明确阻断或按协议记录降级。

## 文档与外部能力

核心测试使用合成文件。真实论文的 Word → PDF → 页面 QA 还需要排版和页面渲染工具；Windows 可使用安装的 Microsoft Word 与仓库中的适配脚本，其他环境通过 `DOCX_RENDERER` 接入提供兼容接口的渲染脚本。字体、图示工具、数值求解器按实际任务安装。所有页面必须实际查看后才确认视觉 QA。

2026 专项规则是版本化协议快照；比赛时仍需核验当届官方文件与更正。仓库通过测试不表示论文已符合当前比赛要求。

## 发布边界

见 [PUBLIC_RELEASE.md](PUBLIC_RELEASE.md)。默认拒绝新增文件：`.gitignore` 只放行逐文件白名单，审计脚本验证内容哈希、敏感特征、链接及 Git 已跟踪文件集合。修改公共文件需经复核后更新清单；不能通过放行资料目录解决检查失败。

许可证沿用仓库 [MIT License](LICENSE)。
