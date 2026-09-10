from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = ROOT / "scripts" / "validate_results.py"
EXAMPLE = ROOT / "examples" / "results.example.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


class ResultsContractTests(unittest.TestCase):
    def run_validator(self, result_file: Path, project_root: Path, *extra: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(VALIDATOR), str(result_file), "--project-root", str(project_root), *extra],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )

    def write_project(self, data: dict) -> tuple[tempfile.TemporaryDirectory[str], Path, Path]:
        temp = tempfile.TemporaryDirectory()
        root = Path(temp.name)
        (root / "data").mkdir()
        (root / "results").mkdir()
        input_path = root / "data" / "input.csv"
        artifact_path = root / "results" / "metric.csv"
        input_path.write_text("x,y\n1,2\n", encoding="utf-8")
        artifact_path.write_text("metric,value\nmae,1.25\n", encoding="utf-8")
        data["inputs"] = [{
            "dataset_id": "input-local",
            "role": "official",
            "source_type": "local",
            "locator": "data/input.csv",
            "sha256": sha256(input_path),
            "schema_summary": "x 与 y 两列",
            "parent_dataset_ids": [],
        }]
        data["artifacts"] = [{
            "artifact_id": "artifact-metric",
            "kind": "table",
            "path": "results/metric.csv",
            "sha256": sha256(artifact_path),
            "produced_by": "python code/main.py",
            "evidence_result_ids": ["metric-main"],
        }]
        data["subproblems"][0]["metrics"][0]["evidence_refs"] = ["artifact-metric"]
        data["subproblems"][0]["artifact_ids"] = ["artifact-metric"]
        result_file = root / "results" / "results.json"
        result_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return temp, root, result_file

    def test_example_is_structurally_valid(self) -> None:
        result = self.run_validator(EXAMPLE, ROOT)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_artifact_hash_and_final_contract_pass(self) -> None:
        data = json.loads(EXAMPLE.read_text(encoding="utf-8"))
        data["run"]["status"] = "approved"
        data["subproblems"][0]["status"] = "completed"
        data["claims"][0]["status"] = "approved"
        temp, root, result_file = self.write_project(data)
        self.addCleanup(temp.cleanup)
        result = self.run_validator(result_file, root, "--check-artifacts", "--final")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_hash_mismatch_is_rejected(self) -> None:
        data = json.loads(EXAMPLE.read_text(encoding="utf-8"))
        temp, root, result_file = self.write_project(data)
        self.addCleanup(temp.cleanup)
        (root / "results" / "metric.csv").write_text("changed", encoding="utf-8")
        result = self.run_validator(result_file, root, "--check-artifacts")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("SHA-256 mismatch", result.stdout)

    def test_duplicate_result_id_is_rejected(self) -> None:
        data = json.loads(EXAMPLE.read_text(encoding="utf-8"))
        data["subproblems"][0]["metrics"].append(deepcopy(data["subproblems"][0]["metrics"][0]))
        temp, root, result_file = self.write_project(data)
        self.addCleanup(temp.cleanup)
        result = self.run_validator(result_file, root)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("duplicate result_id", result.stdout)

    def test_unknown_evidence_is_rejected(self) -> None:
        data = json.loads(EXAMPLE.read_text(encoding="utf-8"))
        data["claims"][0]["evidence_result_ids"] = ["missing-result"]
        temp, root, result_file = self.write_project(data)
        self.addCleanup(temp.cleanup)
        result = self.run_validator(result_file, root)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unknown result evidence", result.stdout)

    def test_path_escape_is_rejected(self) -> None:
        data = json.loads(EXAMPLE.read_text(encoding="utf-8"))
        temp, root, result_file = self.write_project(data)
        self.addCleanup(temp.cleanup)
        loaded = json.loads(result_file.read_text(encoding="utf-8"))
        loaded["artifacts"][0]["path"] = "../outside.csv"
        result_file.write_text(json.dumps(loaded, ensure_ascii=False), encoding="utf-8")
        result = self.run_validator(result_file, root)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("path escapes project root", result.stdout)

    def test_non_finite_number_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            result_file = root / "results.json"
            text = EXAMPLE.read_text(encoding="utf-8").replace('"value": 1.25', '"value": NaN')
            result_file.write_text(text, encoding="utf-8")
            result = self.run_validator(result_file, root)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("non-finite JSON number", result.stdout)

    def test_final_rejects_candidate_claim(self) -> None:
        data = json.loads(EXAMPLE.read_text(encoding="utf-8"))
        data["run"]["status"] = "approved"
        data["subproblems"][0]["status"] = "completed"
        temp, root, result_file = self.write_project(data)
        self.addCleanup(temp.cleanup)
        result = self.run_validator(result_file, root, "--final")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("claim is not approved", result.stdout)


if __name__ == "__main__":
    unittest.main()
