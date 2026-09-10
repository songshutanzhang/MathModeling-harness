"""Adapter for the packaged DOCX renderer using installed Microsoft Word on Windows.

Set DOCX_RENDERER to the absolute packaged render_docx.py path from the runtime.
Managed dependencies are never patched; the conversion hook is process-local.
"""
import importlib.util
import os
from pathlib import Path
import subprocess


def main():
    package = Path(os.environ['DOCX_RENDERER']).resolve()
    spec = importlib.util.spec_from_file_location('packaged_docx_renderer', package)
    renderer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(renderer)

    def convert(doc_path, user_profile, convert_tmp_dir, stem, verbose=False):
        target = Path(convert_tmp_dir) / (stem + '.pdf')
        result = subprocess.run(['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass',
            '-File', str(Path(__file__).with_name('export_word_pdf.ps1')),
            '-InputDoc', str(Path(doc_path).resolve()), '-OutputPdf', str(target.resolve())],
            capture_output=True, text=True, errors='replace', timeout=180)
        log = f'PDF engine: Microsoft Word; return code {result.returncode}\n{result.stdout}\n{result.stderr}'
        return (str(target) if result.returncode == 0 and target.exists() else ''), log

    renderer.convert_to_pdf = convert
    renderer.main()


if __name__ == '__main__':
    main()
