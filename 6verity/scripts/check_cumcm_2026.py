#!/usr/bin/env python3
"""Cross-platform hard gate for CUMCM 2026 paper and AI-use compliance."""

from __future__ import annotations

import argparse
import re
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET


MAX_SUBMISSION_BYTES = 20_000_000
USED_DECLARATION_PREFIX = "本参赛队在竞赛过程中使用了AI工具，主要用于"
USED_DECLARATION_SUFFIX = "，详细使用情况见支撑材料。"
NO_AI_DECLARATION = "本参赛队在竞赛过程中未使用任何AI工具。"
CORE_AI_TERMS = ("题意", "假设", "建模", "模型", "算法", "策略", "结果解释", "关键结论")


class Gate:
    def __init__(self) -> None:
        self.failures: list[str] = []
        self.warnings: list[str] = []

    def fail(self, message: str) -> None:
        self.failures.append(message)
        print(f"FAIL: {message}")

    def warn(self, message: str) -> None:
        self.warnings.append(message)
        print(f"WARN: {message}")

    def info(self, message: str) -> None:
        print(f"INFO: {message}")


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def xml_visible_text(data: bytes) -> str:
    root = ET.fromstring(data)
    paragraphs: list[str] = []
    paragraph_tag = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}p"
    for paragraph in root.iter(paragraph_tag):
        parts: list[str] = []
        for element in paragraph.iter():
            local = element.tag.rsplit("}", 1)[-1]
            if local in {"t", "instrText"} and element.text:
                parts.append(element.text)
            elif local == "tab":
                parts.append("\t")
            elif local in {"br", "cr"}:
                parts.append("\n")
        paragraphs.append("".join(parts))
    return "\n".join(paragraphs)


def strip_comments(text: str, suffix: str) -> str:
    if suffix == ".tex":
        return re.sub(r"(?m)(?<!\\)%.*$", "", text)
    if suffix == ".typ":
        return re.sub(r"(?m)//.*$", "", text)
    return text


def resolve_include(base: Path, raw: str, suffix: str) -> Path:
    target = (base / raw).resolve()
    if not target.suffix:
        target = target.with_suffix(suffix)
    return target


def collect_sources(main: Path, gate: Gate) -> dict[Path, str]:
    suffix = main.suffix.lower()
    if suffix not in {".typ", ".tex", ".docx"}:
        gate.fail(f"paper source must be .docx, .typ, or .tex: {main}")
        return {}

    if suffix == ".docx":
        sources: dict[Path, str] = {}
        try:
            with zipfile.ZipFile(main) as archive:
                names = set(archive.namelist())
                if "word/document.xml" not in names:
                    gate.fail(f"DOCX is missing word/document.xml: {main}")
                    return {}
                sources[main.resolve()] = xml_visible_text(archive.read("word/document.xml"))
                story_names = sorted(
                    name
                    for name in names
                    if re.fullmatch(
                        r"word/(?:header\d+|footer\d+|footnotes|endnotes|comments)\.xml",
                        name,
                    )
                )
                for index, name in enumerate(story_names, start=1):
                    pseudo_path = Path(f"{main.resolve()}::story-{index}")
                    sources[pseudo_path] = xml_visible_text(archive.read(name))
        except (zipfile.BadZipFile, ET.ParseError, OSError) as exc:
            gate.fail(f"paper DOCX is invalid: {exc}")
        return sources

    include_re = (
        re.compile(r'#include\(\s*["\']([^"\']+)["\']\s*\)')
        if suffix == ".typ"
        else re.compile(r"\\(?:input|include)\{([^}]+)\}")
    )
    sources: dict[Path, str] = {}

    def visit(path: Path) -> None:
        path = path.resolve()
        if path in sources:
            return
        if not path.exists():
            gate.fail(f"included source does not exist: {path}")
            return
        text = read_text(path)
        sources[path] = text
        clean = strip_comments(text, suffix)
        for match in include_re.finditer(clean):
            child = resolve_include(path.parent, match.group(1).strip(), suffix)
            visit(child)

    visit(main)
    return sources


def normalize(text: str) -> str:
    return re.sub(r"\s+", "", text)


def statement_body(main_text: str, suffix: str) -> tuple[str, int, int]:
    clean = strip_comments(main_text, suffix)
    if suffix == ".typ":
        statement_pos = clean.rfind("#ai-use-declaration[")
        references_pos = clean.rfind("#references-cn()")
    elif suffix == ".tex":
        statement_pos = clean.rfind("\\aiusedeclaration{")
        references_pos = clean.rfind("\\referencescn")
    else:
        statement_pos = clean.rfind("AI工具使用声明")
        references_pos = clean.rfind("参考文献")
    body = clean[statement_pos:references_pos] if statement_pos >= 0 and references_pos >= 0 else ""
    return body, statement_pos, references_pos


def adopted_core_ai_use(log_text: str) -> bool:
    for line in log_text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("| AI-"):
            continue
        fields = [field.strip() for field in stripped.strip("|").split("|")]
        if len(fields) < 8:
            continue
        stage, purpose, summary, adopted = fields[2], fields[3], fields[4], fields[5]
        if adopted not in {"是", "部分", "已采纳", "部分采纳"}:
            continue
        if any(term in f"{stage} {purpose} {summary}" for term in CORE_AI_TERMS):
            return True
    return False


def check_file_size(path: Path, label: str, gate: Gate) -> None:
    if path.stat().st_size > MAX_SUBMISSION_BYTES:
        gate.fail(f"{label} exceeds 20MB: {path.stat().st_size} bytes")
    else:
        gate.info(f"{label} size is within 20MB")


def check_pdf(path: Path, label: str, gate: Gate) -> None:
    check_file_size(path, label, gate)
    with path.open("rb") as stream:
        if stream.read(5) != b"%PDF-":
            gate.fail(f"{label} is not a valid PDF file: {path}")


def check_archive(path: Path, ai_used: bool, gate: Gate) -> None:
    if path.suffix.lower() not in {".zip", ".rar"}:
        gate.fail(f"support archive must be ZIP or RAR: {path}")
        return
    check_file_size(path, "support archive", gate)
    if ai_used and path.suffix.lower() == ".zip":
        try:
            with zipfile.ZipFile(path) as archive:
                names = [Path(name).name for name in archive.namelist()]
            if "AI工具使用详情.pdf" not in names:
                gate.fail("support ZIP does not contain AI工具使用详情.pdf")
        except zipfile.BadZipFile:
            gate.fail(f"support ZIP is invalid: {path}")
    elif ai_used and path.suffix.lower() == ".rar":
        gate.warn("RAR contents were not inspected; manually confirm AI工具使用详情.pdf is included")


def run(args: argparse.Namespace) -> int:
    gate = Gate()
    if args.competition_year != 2026:
        gate.fail("check_cumcm_2026.py only applies to competition year 2026")
        return 1
    main = args.paper_source.resolve()
    if not main.exists():
        gate.fail(f"paper source does not exist: {main}")
        return 1

    sources = collect_sources(main, gate)
    main_text = sources[main] if main in sources else read_text(main)
    suffix = main.suffix.lower()
    clean_sources = "\n".join(strip_comments(text, suffix) for text in sources.values())
    compact_sources = normalize(clean_sources)

    toc_patterns = (
        (r"#outline\s*\(", "Typst outline"),
        (r"#toc-page\s*\(", "Typst toc-page"),
        (r"\\tableofcontents\b", "LaTeX tableofcontents"),
        (r"\\tocpage\b", "LaTeX tocpage"),
        (r"\\@starttoc\{toc\}", "LaTeX low-level TOC"),
        (r"(?m)^\s*目录\s*$", "Word directory heading"),
        (r"(?i)\bTOC\s+\\[a-z]", "Word TOC field"),
    )
    for pattern, label in toc_patterns:
        if re.search(pattern, clean_sources):
            gate.fail(f"CUMCM paper must not contain a directory/TOC ({label})")

    placeholder_re = re.compile(
        r"\{\{[A-Z0-9_:-]+\}\}|PLACEHOLDER|TODO|TBD|待补充|待续写|中文摘要内容|关键词1|作者\s*[.。]\s*题名",
        re.I,
    )
    if placeholder_re.search(clean_sources):
        gate.fail("paper still contains template placeholders or sample references")

    for required in ("支撑材料文件列表", "完整源程序代码"):
        if required not in clean_sources:
            gate.fail(f"appendix is missing required section: {required}")

    identity_re = re.compile(r"参赛学校|学校名称|参赛队员|姓名\s*[:：]|学号\s*[:：]|指导教师\s*[:：]|赛区\s*[:：]")
    if identity_re.search(clean_sources):
        gate.fail("paper source contains possible identity, school, adviser, or region information")

    body, statement_pos, references_pos = statement_body(main_text, suffix)
    if statement_pos < 0:
        gate.fail("paper is missing AI工具使用声明")
    elif references_pos < 0 or statement_pos >= references_pos:
        gate.fail("AI工具使用声明 must appear before references")

    body_compact = normalize(body)
    ai_used = args.ai_used == "yes"
    if ai_used:
        declaration_re = re.compile(
            re.escape(USED_DECLARATION_PREFIX) + r".+?" + re.escape(USED_DECLARATION_SUFFIX)
        )
        if not declaration_re.search(body_compact):
            gate.fail("AI-used declaration does not use the required official wording")
        if args.ai_log is None or not args.ai_log.exists():
            gate.fail("AI was used but AI_USAGE_LOG.md is missing")
        else:
            log_text = read_text(args.ai_log)
            if "TODO" in log_text or len(log_text.strip()) < 200:
                gate.fail("AI usage log is incomplete")
            if adopted_core_ai_use(log_text) and not any(term in body for term in CORE_AI_TERMS):
                gate.fail("AI log records adopted core modeling/algorithm use, but the paper declaration omits it")
        if args.ai_details_pdf is None or not args.ai_details_pdf.exists():
            gate.fail("AI was used but AI工具使用详情.pdf is missing")
        else:
            if args.ai_details_pdf.name != "AI工具使用详情.pdf":
                gate.fail("AI details PDF filename must be exactly AI工具使用详情.pdf")
            check_pdf(args.ai_details_pdf, "AI details PDF", gate)
    else:
        if NO_AI_DECLARATION not in body_compact:
            gate.fail("no-AI declaration does not use the required official wording")

    if args.body_pages is not None and args.body_pages > 30:
        gate.fail(f"paper body exceeds 30 pages: {args.body_pages}")
    elif args.final and args.body_pages is None:
        gate.fail("final check requires --body-pages")

    if suffix == ".docx":
        check_file_size(main, "paper DOCX", gate)

    if args.paper_pdf is not None:
        if not args.paper_pdf.exists():
            gate.fail(f"paper PDF does not exist: {args.paper_pdf}")
        else:
            check_pdf(args.paper_pdf, "paper PDF", gate)
    elif args.final:
        gate.fail("final check requires --paper-pdf")

    if args.support_archive is not None:
        if not args.support_archive.exists():
            gate.fail(f"support archive does not exist: {args.support_archive}")
        else:
            check_archive(args.support_archive, ai_used, gate)
    elif args.final and "本论文没有支撑材料" not in clean_sources:
        gate.fail("final check requires --support-archive unless the official no-support statement is present")

    if gate.failures:
        print(f"RESULT: FAIL ({len(gate.failures)} failures, {len(gate.warnings)} warnings)")
        return 1
    print(f"RESULT: PASS (0 failures, {len(gate.warnings)} warnings)")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--paper-source", type=Path, required=True, help="paper.docx, main.typ, or main.tex")
    parser.add_argument("--competition-year", type=int, required=True,
                        help="must be 2026; use contest_rules.py to select a checker")
    parser.add_argument("--ai-used", choices=("yes", "no"), required=True)
    parser.add_argument("--ai-log", type=Path)
    parser.add_argument("--ai-details-pdf", type=Path)
    parser.add_argument("--paper-pdf", type=Path)
    parser.add_argument("--support-archive", type=Path)
    parser.add_argument("--body-pages", type=int, help="body page count, excluding abstract and appendices")
    parser.add_argument("--final", action="store_true", help="require final PDF and support archive")
    return parser.parse_args()


if __name__ == "__main__":
    sys.exit(run(parse_args()))
