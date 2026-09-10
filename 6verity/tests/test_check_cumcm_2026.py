from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape


ROOT = Path(__file__).resolve().parents[2]
CHECKER = ROOT / "6verity" / "scripts" / "check_cumcm_2026.py"


VALID_PAPER = """
#set page(numbering: "1")
#let ai-use-declaration(body) = [#heading(numbering: none)[AI工具使用声明] #body]
#let references-cn() = [#heading(numbering: none)[参考文献]]
= 真实论文标题
摘要
关键词：测试
= 问题重述
真实正文。
#ai-use-declaration[
本参赛队在竞赛过程中使用了AI工具，主要用于资料搜集辅助、语言润色、代码调试和格式与规范核验，详细使用情况见支撑材料。
]
#references-cn()
= 附录
== 支撑材料文件列表
程序.py：完整求解程序。
== 完整源程序代码
程序内容见本附录和支撑材料。
"""


VALID_LOG = """
# AI 工具使用日志

| 编号 | 工具及版本/型号 | 使用环节 | 用途类别 | 主要提示方式与过程摘要 | 是否采纳 | 人工修改 | 人工核验及证据 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| AI-001 | 示例工具 v1 | 资料阶段 | 资料搜集辅助 | 给定关键词后返回候选公开信源，由人工逐项访问原始页面 | 部分 | 删除无权威来源条目 | 已核对原始页面、发布日期和链接 |

## 最终人工确认

全部记录已经人工审查，未包含身份、学校或赛区信息。
"""


def write_minimal_docx(path: Path, paragraphs: list[str]) -> None:
    body = "".join(
        f"<w:p><w:r><w:t>{escape(paragraph)}</w:t></w:r></w:p>"
        for paragraph in paragraphs
    )
    document_xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>{body}</w:body>
</w:document>
"""
    content_types = """<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="xml" ContentType="application/xml"/>
</Types>
"""
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("word/document.xml", document_xml)


class CumcmCheckerTests(unittest.TestCase):
    def run_checker(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(CHECKER), "--competition-year", "2026", *args],
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            check=False,
        )

    def test_valid_ai_used_package_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paper = root / "main.typ"
            log = root / "AI_USAGE_LOG.md"
            details = root / "AI工具使用详情.pdf"
            pdf = root / "论文.pdf"
            support = root / "支撑材料.zip"
            paper.write_text(VALID_PAPER, encoding="utf-8")
            log.write_text(VALID_LOG, encoding="utf-8")
            details.write_bytes(b"%PDF-1.4\n% test\n")
            pdf.write_bytes(b"%PDF-1.4\n% test\n")
            with zipfile.ZipFile(support, "w") as archive:
                archive.write(details, details.name)
            result = self.run_checker(
                "--paper-source", str(paper),
                "--ai-used", "yes",
                "--ai-log", str(log),
                "--ai-details-pdf", str(details),
                "--paper-pdf", str(pdf),
                "--support-archive", str(support),
                "--body-pages", "12",
                "--final",
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_unfilled_source_template_fails(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            template = Path(folder) / "paper.typ"
            template.write_text("{{PAPER_TITLE}}", encoding="utf-8")
            result = self.run_checker("--paper-source", str(template), "--ai-used", "yes")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("template placeholders", result.stdout)

    def test_unfilled_word_template_fails(self) -> None:
        template = ROOT / "5writing" / "assets" / "CUMCM_2026_论文模板.docx"
        result = self.run_checker("--paper-source", str(template), "--ai-used", "yes")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("template placeholders", result.stdout)

    def test_final_gate_requires_body_page_count(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paper = root / "main.typ"
            pdf = root / "论文.pdf"
            support = root / "支撑材料.zip"
            paper.write_text(
                VALID_PAPER.replace(
                    "本参赛队在竞赛过程中使用了AI工具，主要用于资料搜集辅助、语言润色、代码调试和格式与规范核验，详细使用情况见支撑材料。",
                    "本参赛队在竞赛过程中未使用任何AI工具。",
                ),
                encoding="utf-8",
            )
            pdf.write_bytes(b"%PDF-1.4\n% test\n")
            with zipfile.ZipFile(support, "w"):
                pass
            result = self.run_checker(
                "--paper-source", str(paper),
                "--ai-used", "no",
                "--paper-pdf", str(pdf),
                "--support-archive", str(support),
                "--final",
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("requires --body-pages", result.stdout)

    def test_core_ai_use_cannot_be_omitted_from_declaration(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paper = root / "main.typ"
            log = root / "AI_USAGE_LOG.md"
            details = root / "AI工具使用详情.pdf"
            paper.write_text(VALID_PAPER, encoding="utf-8")
            log.write_text(
                VALID_LOG.replace(
                    "资料阶段 | 资料搜集辅助 | 给定关键词后返回候选公开信源，由人工逐项访问原始页面",
                    "建模阶段 | 建模方案辅助分析 | 比较候选模型并形成被论文采用的算法路线",
                ),
                encoding="utf-8",
            )
            details.write_bytes(b"%PDF-1.4\n% test\n")
            result = self.run_checker(
                "--paper-source", str(paper),
                "--ai-used", "yes",
                "--ai-log", str(log),
                "--ai-details-pdf", str(details),
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("omits it", result.stdout)

    def test_no_ai_official_wording_passes_nonfinal_gate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paper = root / "main.typ"
            paper.write_text(
                VALID_PAPER.replace(
                    "本参赛队在竞赛过程中使用了AI工具，主要用于资料搜集辅助、语言润色、代码调试和格式与规范核验，详细使用情况见支撑材料。",
                    "本参赛队在竞赛过程中未使用任何AI工具。",
                ),
                encoding="utf-8",
            )
            result = self.run_checker("--paper-source", str(paper), "--ai-used", "no")
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_word_source_passes_and_is_checked_as_primary_document(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paper = Path(tmp) / "论文.docx"
            write_minimal_docx(
                paper,
                [
                    "真实论文标题",
                    "摘要",
                    "关键词：测试",
                    "问题重述",
                    "真实正文内容。",
                    "AI工具使用声明",
                    "本参赛队在竞赛过程中未使用任何AI工具。",
                    "参考文献",
                    "附录",
                    "支撑材料文件列表",
                    "程序.py：完整求解程序。",
                    "完整源程序代码",
                    "完整代码内容。",
                ],
            )
            result = self.run_checker("--paper-source", str(paper), "--ai-used", "no")
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("paper DOCX size is within 20MB", result.stdout)

    def test_word_source_with_directory_heading_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paper = Path(tmp) / "论文.docx"
            write_minimal_docx(
                paper,
                [
                    "真实论文标题",
                    "目录",
                    "AI工具使用声明",
                    "本参赛队在竞赛过程中未使用任何AI工具。",
                    "参考文献",
                    "支撑材料文件列表",
                    "完整源程序代码",
                ],
            )
            result = self.run_checker("--paper-source", str(paper), "--ai-used", "no")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Word directory heading", result.stdout)

    def test_other_year_is_rejected_before_content_checks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paper = Path(tmp) / "main.typ"
            paper.write_text(VALID_PAPER, encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(CHECKER), "--competition-year", "2023",
                 "--paper-source", str(paper), "--ai-used", "yes"],
                text=True, encoding="utf-8", errors="replace", capture_output=True, check=False,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("only applies to competition year 2026", result.stdout)


if __name__ == "__main__":
    unittest.main()
