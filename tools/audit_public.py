"""Fail closed against the explicitly reviewed public file manifest."""
from pathlib import Path
import hashlib
import json
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = "PUBLIC_MANIFEST.json"
ALLOWED = {".py", ".md", ".yaml", ".yml", ".json", ".ps1", ".sh", ".txt", ".ini"}
SPECIAL = {".gitignore", ".gitattributes", "LICENSE"}
FORBIDDEN_PARTS = {".git", "training", "evaluation", "runs", "cases", "source-notes", "reference-materials", "archive", "releases", "private-fulltext", "node_modules"}
# The protocol-only evaluation/EVAL_SPEC.md is a single explicit exception.
PROTOCOL = "_references/knowledge/evaluation/EVAL_SPEC.md"
PATTERNS = {
    "credential": re.compile(r"(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{30,}|sk-[A-Za-z0-9_-]{20,}|AKIA[A-Z0-9]{16}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----)"),
    "machine_path": re.compile(r"(?i)(?:[a-z]:[\\/](?:Users|home|workspace)[\\/]|/(?:Users|home)/[A-Za-z0-9_.-]+/)"),
    "email": re.compile(r"[A-Za-z0-9_.+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
}

def validate_file(root, name, expected):
    rel = Path(name)
    if rel.is_absolute() or ".." in rel.parts or "\\" in name:
        raise ValueError(f"unsafe manifest path: {name}")
    if name != PROTOCOL and FORBIDDEN_PARTS.intersection(rel.parts):
        raise ValueError(f"private directory: {name}")
    if rel.suffix not in ALLOWED and name not in SPECIAL:
        raise ValueError(f"non-source file: {name}")
    path = root / rel
    if any(p.is_symlink() for p in [path, *path.parents] if p != root.parent):
        raise ValueError(f"symlink: {name}")
    path.resolve().relative_to(root.resolve())
    data = path.read_bytes()
    if b"\x00" in data or len(data) > 2_000_000:
        raise ValueError(f"binary or oversized file: {name}")
    content = data.decode("utf-8")
    for category, pattern in PATTERNS.items():
        if pattern.search(content):
            raise ValueError(f"{category} detected in {name}")
    if hashlib.sha256(data).hexdigest() != expected:
        raise ValueError(f"unreviewed content change: {name}")

def audit(root=ROOT):
    manifest = json.loads((root / MANIFEST).read_text(encoding="utf-8"))
    files = manifest["files"]
    for name, expected in files.items():
        validate_file(root, name, expected)
    tracked = subprocess.check_output(["git", "ls-files", "-z"], cwd=root).decode("utf-8").split("\0")
    unexpected = set(filter(None, tracked)) - set(files) - {MANIFEST}
    if unexpected:
        raise ValueError("unreviewed tracked paths: " + ", ".join(sorted(unexpected)))
    # Compare staged bytes too: a sanitized working copy must not hide a secret in the index.
    for name in filter(None, tracked):
        staged = subprocess.check_output(["git", "show", ":" + name], cwd=root)
        if staged != (root / name).read_bytes():
            raise ValueError(f"index differs from reviewed working file: {name}")
    return {"status": "passed", "reviewed_files": len(files) + 1}

if __name__ == "__main__":
    try:
        print(json.dumps(audit()))
    except (ValueError, OSError, UnicodeError, subprocess.CalledProcessError) as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
