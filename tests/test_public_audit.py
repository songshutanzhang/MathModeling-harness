import hashlib
import importlib.util
from pathlib import Path
import pytest

spec = importlib.util.spec_from_file_location("audit_public", Path(__file__).resolve().parents[1] / "tools/audit_public.py")
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)

def test_secret_is_blocked_even_with_matching_hash(tmp_path):
    data = ("ghp_" + "A" * 36).encode()
    (tmp_path / "example.py").write_bytes(data)
    with pytest.raises(ValueError, match="credential"):
        audit.validate_file(tmp_path, "example.py", hashlib.sha256(data).hexdigest())

def test_case_and_binary_paths_are_blocked(tmp_path):
    for path in ("training/problem.md", "paper.docx", "../escape.py"):
        with pytest.raises(ValueError):
            audit.validate_file(tmp_path, path, "0" * 64)

def test_modified_code_requires_review(tmp_path):
    (tmp_path / "example.py").write_text("print(1)")
    with pytest.raises(ValueError, match="unreviewed content"):
        audit.validate_file(tmp_path, "example.py", "0" * 64)
