"""Portable entry point. Use Python 3.11+; no model service is bundled."""
from pathlib import Path
import argparse
import importlib.util
import json
import os
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
SCRIPTS = ROOT / "_references/harness/scripts"

def call(script, *args):
    return subprocess.call([sys.executable, str(script), *map(str, args)], cwd=ROOT)

def main():
    # Propagate UTF-8 to all Python subprocesses on non-Chinese Windows hosts.
    os.environ["PYTHONUTF8"] = "1"
    os.environ["PYTHONIOENCODING"] = "utf-8"
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["setup", "check", "test", "smoke", "run"])
    args, rest = parser.parse_known_args()
    if args.action == "test":
        return subprocess.call([sys.executable, "-m", "pytest", "-q", *rest], cwd=ROOT)
    if args.action == "run":
        return call(SCRIPTS / "run_orchestrator.py", *rest)
    if args.action == "smoke":
        return call(SCRIPTS / "run_workflow_canary.py", *rest)
    if rest:
        parser.error("unexpected arguments: " + " ".join(rest))
    if args.action == "setup":
        template = ROOT / "5writing/assets/CUMCM_2026_论文模板.docx"
        if not template.exists():
            code = call(ROOT / "5writing/scripts/build_cumcm_word_template.py", "--output", template)
            if code:
                return code
        code = call(SCRIPTS / "generate_vnext_views.py")
        if code:
            return code
    sys.path.insert(0, str(SCRIPTS))
    from dependency_preflight import inspect
    report = inspect(ROOT, ROOT, packages=["PyYAML", "jsonschema", "python-docx", "numpy", "scipy", "psutil"])
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "executable" else 1

if __name__ == "__main__":
    raise SystemExit(main())
