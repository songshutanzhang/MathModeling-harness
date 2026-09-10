#!/usr/bin/env python3
"""Validate MathModelAgent results.json structure, references, and artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker


KNOWLEDGE_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_FILE = KNOWLEDGE_ROOT / "schemas" / "results.schema.json"


def load_json_strict(path: Path) -> object:
    def reject_constant(value: str) -> None:
        raise ValueError(f"non-finite JSON number is forbidden: {value}")

    return json.loads(path.read_text(encoding="utf-8"), parse_constant=reject_constant)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def active_card_ids() -> set[str]:
    ids: set[str] = set()
    for path in (KNOWLEDGE_ROOT / "cards").rglob("*.md"):
        text = path.read_text(encoding="utf-8")
        if not text.startswith("---\n"):
            continue
        frontmatter = text.split("---\n", 2)[1]
        card_match = re.search(r"^id:\s*(\S+)\s*$", frontmatter, re.MULTILINE)
        status_match = re.search(r"^status:\s*(\S+)\s*$", frontmatter, re.MULTILINE)
        if card_match and status_match and status_match.group(1) == "active":
            ids.add(card_match.group(1))
    return ids


def safe_project_path(project_root: Path, relative: str, label: str, errors: list[str]) -> Path | None:
    candidate = (project_root / relative).resolve()
    try:
        candidate.relative_to(project_root)
    except ValueError:
        errors.append(f"{label}: path escapes project root: {relative}")
        return None
    return candidate


def validate_document(data: dict[str, object], project_root: Path, check_artifacts: bool, final: bool) -> list[str]:
    errors: list[str] = []
    known_cards = active_card_ids()
    for card_id in data["knowledge_cards"]:
        if card_id not in known_cards:
            errors.append(f"knowledge_cards: unknown or inactive card {card_id}")

    result_ids: set[str] = set()
    artifact_ids: set[str] = set()
    baseline_ids: set[str] = set()
    validation_ids: set[str] = set()
    constraint_ids: set[str] = set()
    subproblem_ids: set[str] = set()

    def add_unique(identifier: str, bucket: set[str], label: str) -> None:
        if identifier in bucket:
            errors.append(f"duplicate {label}: {identifier}")
        bucket.add(identifier)

    for subproblem in data["subproblems"]:
        add_unique(subproblem["subproblem_id"], subproblem_ids, "subproblem_id")
        for metric in subproblem["metrics"]:
            add_unique(metric["result_id"], result_ids, "result_id")
            uncertainty = metric.get("uncertainty")
            if uncertainty and uncertainty["lower"] > uncertainty["upper"]:
                errors.append(f"{metric['result_id']}: uncertainty lower exceeds upper")
        for baseline in subproblem["baselines"]:
            add_unique(baseline["baseline_id"], baseline_ids, "baseline_id")
        for constraint in subproblem["constraints"]:
            add_unique(constraint["constraint_id"], constraint_ids, "constraint_id")
        for validation in subproblem["validations"]:
            add_unique(validation["validation_id"], validation_ids, "validation_id")

    for artifact in data["artifacts"]:
        add_unique(artifact["artifact_id"], artifact_ids, "artifact_id")

    evidence_ids = result_ids | artifact_ids
    for subproblem in data["subproblems"]:
        for metric in subproblem["metrics"]:
            missing = set(metric["evidence_refs"]) - artifact_ids
            if missing:
                errors.append(f"{metric['result_id']}: unknown artifact evidence {sorted(missing)}")
        for baseline in subproblem["baselines"]:
            missing = set(baseline["metric_result_ids"]) - result_ids
            if missing:
                errors.append(f"{baseline['baseline_id']}: unknown metric result {sorted(missing)}")
        missing_artifacts = set(subproblem["artifact_ids"]) - artifact_ids
        if missing_artifacts:
            errors.append(f"{subproblem['subproblem_id']}: unknown artifact {sorted(missing_artifacts)}")
        for validation in subproblem["validations"]:
            missing = set(validation["evidence_refs"]) - evidence_ids
            if missing:
                errors.append(f"{validation['validation_id']}: unknown evidence {sorted(missing)}")
    for artifact in data["artifacts"]:
        missing = set(artifact["evidence_result_ids"]) - result_ids
        if missing:
            errors.append(f"{artifact['artifact_id']}: unknown result evidence {sorted(missing)}")
    for row in data["rule_coverage"]:
        missing = set(row["evidence_refs"]) - evidence_ids
        if missing:
            errors.append(f"{row['rule_id']}: unknown evidence {sorted(missing)}")
    for claim in data["claims"]:
        missing = set(claim["evidence_result_ids"]) - result_ids
        if missing:
            errors.append(f"{claim['claim_id']}: unknown result evidence {sorted(missing)}")
    for warning in data["warnings"]:
        missing = set(warning["evidence_refs"]) - evidence_ids
        if missing:
            errors.append(f"{warning['warning_id']}: unknown evidence {sorted(missing)}")

    local_files: list[tuple[str, str, str]] = []
    for input_row in data["inputs"]:
        if input_row["source_type"] == "local":
            local_files.append((f"input {input_row['dataset_id']}", input_row["locator"], input_row["sha256"]))
    for artifact in data["artifacts"]:
        local_files.append((f"artifact {artifact['artifact_id']}", artifact["path"], artifact["sha256"]))
    for label, relative, expected_hash in local_files:
        candidate = safe_project_path(project_root, relative, label, errors)
        if candidate is None or not check_artifacts:
            continue
        if not candidate.is_file():
            errors.append(f"{label}: missing file {relative}")
        elif sha256_file(candidate) != expected_hash.upper():
            errors.append(f"{label}: SHA-256 mismatch for {relative}")

    if final:
        if data["run"]["status"] != "approved":
            errors.append("final: run.status must be approved")
        for subproblem in data["subproblems"]:
            if subproblem["status"] != "completed":
                errors.append(f"final: {subproblem['subproblem_id']} must be completed")
            for constraint in subproblem["constraints"]:
                if not constraint["passed"]:
                    errors.append(f"final: constraint failed: {constraint['constraint_id']}")
            for validation in subproblem["validations"]:
                if not validation["passed"]:
                    errors.append(f"final: validation failed: {validation['validation_id']}")
        for row in data["rule_coverage"]:
            if row["status"] == "failed":
                errors.append(f"final: rule failed: {row['rule_id']}")
            if row["status"] == "satisfied" and not row["evidence_refs"]:
                errors.append(f"final: satisfied rule lacks evidence: {row['rule_id']}")
        for claim in data["claims"]:
            if claim["status"] != "approved":
                errors.append(f"final: claim is not approved: {claim['claim_id']}")
        for warning in data["warnings"]:
            if warning["severity"] == "error":
                errors.append(f"final: unresolved error warning: {warning['warning_id']}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("results", type=Path)
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--check-artifacts", action="store_true")
    parser.add_argument("--final", action="store_true")
    args = parser.parse_args()
    results_path = args.results.resolve()
    project_root = args.project_root.resolve()
    try:
        data = load_json_strict(results_path)
        schema = load_json_strict(SCHEMA_FILE)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print("RESULTS CONTRACT: FAIL")
        print(f"- {exc}")
        return 1
    if not isinstance(data, dict):
        print("RESULTS CONTRACT: FAIL")
        print("- root must be an object")
        return 1
    schema_errors = sorted(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(data),
        key=lambda item: list(item.absolute_path),
    )
    errors = [f"schema {list(error.absolute_path)}: {error.message}" for error in schema_errors]
    if not schema_errors:
        errors.extend(validate_document(data, project_root, args.check_artifacts, args.final))
    if errors:
        print("RESULTS CONTRACT: FAIL")
        for error in errors:
            print(f"- {error}")
        return 1
    print("RESULTS CONTRACT: PASS")
    print(f"file={results_path}")
    print(f"subproblems={len(data['subproblems'])} artifacts={len(data['artifacts'])} claims={len(data['claims'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
