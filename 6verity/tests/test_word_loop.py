from __future__ import annotations

import json
import hashlib
import os
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "5writing" / "scripts" / "word_loop.py"


CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="xml" ContentType="application/xml"/>
</Types>
"""


def make_docx(path: Path, dirty: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tracked = "<w:ins><w:r><w:t>修订文字</w:t></w:r></w:ins>" if dirty else ""
    document = f"""<?xml version="1.0" encoding="UTF-8"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body><w:p><w:r><w:t>数学建模论文</w:t></w:r>{tracked}</w:p></w:body>
</w:document>
"""
    core = """<?xml version="1.0" encoding="UTF-8"?>
<cp:coreProperties
 xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties"
 xmlns:dc="http://purl.org/dc/elements/1.1/">
 <dc:creator>{}</dc:creator>
 <cp:lastModifiedBy>{}</cp:lastModifiedBy>
</cp:coreProperties>
""".format("某参赛者" if dirty else "", "某参赛者" if dirty else "")
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("[Content_Types].xml", CONTENT_TYPES)
        archive.writestr("word/document.xml", document)
        archive.writestr("docProps/core.xml", core)


class WordLoopTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.project = Path(self.temp.name)
        self.registry = self.project / "paper" / "revisions" / "WORD_LOOPS.json"
        self.working = self.project / "paper" / "论文_working.docx"
        self.strategy = self.project / "reports" / "STRATEGY_CONTEXT.md"
        self.changeset = self.project / "_tmp" / "CHANGESET.md"
        self.render_dir = self.project / "_tmp" / "render"
        make_docx(self.working)
        self.strategy.parent.mkdir(parents=True, exist_ok=True)
        self.strategy.write_text("# 策略上下文\n当前采用透明基线。\n", encoding="utf-8")
        self.changeset.parent.mkdir(parents=True, exist_ok=True)
        self.changeset.write_text("# 本轮变更\n完成正文初稿。\n", encoding="utf-8")
        self.prepare_render(2)
        result = self.run_loop(
            "init",
            "--registry",
            str(self.registry.relative_to(self.project)),
            "--project-root",
            str(self.project),
            "--working-docx",
            str(self.working.relative_to(self.project)),
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def run_loop(self, *args: str) -> subprocess.CompletedProcess[str]:
        environment = os.environ.copy()
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        return subprocess.run(
            [sys.executable, str(SCRIPT), *args],
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            check=False,
            env=environment,
        )

    def prepare_render(self, pages: int) -> None:
        self.render_dir.mkdir(parents=True, exist_ok=True)
        for old in self.render_dir.glob("page-*.png"):
            old.unlink()
        (self.render_dir / "论文_working.pdf").write_bytes(b"%PDF-1.4\nqa snapshot\n")
        for index in range(1, pages + 1):
            (self.render_dir / f"page-{index}.png").write_bytes(
                b"\x89PNG\r\n" + bytes([index])
            )

        def digest(path: Path) -> str:
            return hashlib.sha256(path.read_bytes()).hexdigest()

        pdf = self.render_dir / "论文_working.pdf"
        images = [self.render_dir / f"page-{index}.png" for index in range(1, pages + 1)]
        receipt = {
            "schema_version": "1.0",
            "rendered_at": "2026-08-27T00:00:00+00:00",
            "renderer": "test renderer",
            "docx": {
                "path": self.working.relative_to(self.project).as_posix(),
                "sha256": digest(self.working),
            },
            "pdf": {
                "path": pdf.relative_to(self.project).as_posix(),
                "sha256": digest(pdf),
            },
            "page_count": pages,
            "page_images": [
                {
                    "path": image.relative_to(self.project).as_posix(),
                    "sha256": digest(image),
                }
                for image in images
            ],
        }
        (self.render_dir / "RENDER_RECEIPT.json").write_text(
            json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def snapshot(self, loop_id: str, pages: int = 2) -> subprocess.CompletedProcess[str]:
        return self.run_loop(
            "snapshot",
            "--registry",
            str(self.registry.relative_to(self.project)),
            "--project-root",
            str(self.project),
            "--loop-id",
            loop_id,
            "--docx",
            str(self.working.relative_to(self.project)),
            "--render-receipt",
            str((self.render_dir / "RENDER_RECEIPT.json").relative_to(self.project)),
            "--all-pages-reviewed",
            "--strategy-context",
            str(self.strategy.relative_to(self.project)),
            "--changeset",
            str(self.changeset.relative_to(self.project)),
        )

    def verify(self, loop_id: str = "latest", final_ready: bool = False) -> subprocess.CompletedProcess[str]:
        arguments = [
            "verify",
            "--registry",
            str(self.registry.relative_to(self.project)),
            "--project-root",
            str(self.project),
            "--loop-id",
            loop_id,
        ]
        if final_ready:
            arguments.append("--final-ready")
        return self.run_loop(*arguments)

    def test_snapshot_and_verify_pass(self) -> None:
        result = self.snapshot("loop-001")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        verify = self.verify()
        self.assertEqual(verify.returncode, 0, verify.stdout + verify.stderr)
        self.assertIn("RESULT: PASS", verify.stdout)

    def test_page_image_count_must_match(self) -> None:
        receipt_path = self.render_dir / "RENDER_RECEIPT.json"
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        receipt["page_count"] = 3
        receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
        result = self.snapshot("loop-001")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("page image count", result.stdout)

    def test_docx_change_after_render_receipt_blocks_snapshot(self) -> None:
        self.working.write_bytes(self.working.read_bytes() + b"changed after render")
        result = self.snapshot("loop-001")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("changed after the recorded render", result.stdout)

    def test_loop_sequence_and_frozen_version_are_immutable(self) -> None:
        self.assertEqual(self.snapshot("loop-001").returncode, 0)
        skipped = self.snapshot("loop-003")
        self.assertNotEqual(skipped.returncode, 0)
        frozen = self.project / "paper" / "revisions" / "loop-001" / "论文_loop-001.docx"
        frozen.write_bytes(frozen.read_bytes() + b"tamper")
        verify = self.verify("loop-001")
        self.assertNotEqual(verify.returncode, 0)
        self.assertIn("DOCX hash changed", verify.stdout)

    def test_finalize_delivers_word_and_pdf_from_same_loop(self) -> None:
        self.assertEqual(self.snapshot("loop-001").returncode, 0)
        result = self.run_loop(
            "finalize",
            "--registry",
            str(self.registry.relative_to(self.project)),
            "--project-root",
            str(self.project),
            "--loop-id",
            "loop-001",
            "--output-dir",
            "submission",
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue((self.project / "submission" / "论文.docx").is_file())
        self.assertTrue((self.project / "submission" / "论文.pdf").is_file())
        manifest = json.loads(
            (self.project / "submission" / "FINAL_DELIVERY.json").read_text(encoding="utf-8")
        )
        self.assertEqual(manifest["source_loop"], "loop-001")
        self.assertTrue(manifest["docx"]["editable"])
        self.assertTrue(manifest["pdf"]["derived_from_same_loop_docx"])
        final_verify = self.run_loop(
            "verify",
            "--registry",
            str(self.registry.relative_to(self.project)),
            "--project-root",
            str(self.project),
            "--loop-id",
            "loop-001",
            "--final-ready",
            "--final-manifest",
            "submission/FINAL_DELIVERY.json",
        )
        self.assertEqual(final_verify.returncode, 0, final_verify.stdout + final_verify.stderr)

        (self.project / "submission" / "论文.pdf").write_bytes(b"%PDF-1.4\nchanged\n")
        stale = self.run_loop(
            "verify",
            "--registry",
            str(self.registry.relative_to(self.project)),
            "--project-root",
            str(self.project),
            "--loop-id",
            "loop-001",
            "--final-ready",
            "--final-manifest",
            "submission/FINAL_DELIVERY.json",
        )
        self.assertNotEqual(stale.returncode, 0)
        self.assertIn("final PDF hash changed", stale.stdout)

    def test_finalize_rejects_metadata_and_tracked_changes(self) -> None:
        make_docx(self.working, dirty=True)
        self.prepare_render(2)
        self.assertEqual(self.snapshot("loop-001").returncode, 0)
        verify = self.verify("loop-001", final_ready=True)
        self.assertNotEqual(verify.returncode, 0)
        self.assertIn("tracked changes", verify.stdout)
        self.assertIn("creator metadata", verify.stdout)

    def test_render_command_creates_receipt_for_exact_docx(self) -> None:
        renderer = self.project / "_tmp" / "fake_renderer.py"
        renderer.write_text(
            """from pathlib import Path
import sys

source = Path(sys.argv[1])
out = Path(sys.argv[sys.argv.index('--output_dir') + 1])
out.mkdir(parents=True, exist_ok=True)
(out / f'{source.stem}.pdf').write_bytes(b'%PDF-1.4\\nrendered\\n')
(out / 'page-1.png').write_bytes(b'\\x89PNG\\r\\npage1')
""",
            encoding="utf-8",
        )
        output = self.project / "_tmp" / "auto-render"
        result = self.run_loop(
            "render",
            "--project-root",
            str(self.project),
            "--docx",
            str(self.working.relative_to(self.project)),
            "--output-dir",
            str(output.relative_to(self.project)),
            "--renderer",
            str(renderer),
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        receipt = json.loads((output / "RENDER_RECEIPT.json").read_text(encoding="utf-8"))
        self.assertEqual(receipt["page_count"], 1)
        self.assertEqual(
            receipt["docx"]["sha256"], hashlib.sha256(self.working.read_bytes()).hexdigest()
        )


if __name__ == "__main__":
    unittest.main()
