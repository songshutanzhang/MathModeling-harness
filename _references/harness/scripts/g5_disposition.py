#!/usr/bin/env python3
"""Append an authorized, hash-bound G5 finding disposition without editing the review."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from runtime_support import canonical, digest, file_hash, record, scoped

LEDGER = "FINDING_DISPOSITIONS.jsonl"
ZERO = "0" * 64


def _load_validator():
    path = Path(__file__).with_name("validate_g5_bundle.py")
    spec = importlib.util.spec_from_file_location("g5_for_disposition", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    return module


def read_events(path: Path) -> list[dict]:
    if not path.exists():
        return []
    events = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            raise ValueError(f"blank/partial disposition line: {number}")
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise ValueError(f"partial disposition line {number}: {exc}") from exc
    return events


def append(bundle: Path, project_root: Path, *, event_id: str, finding_id: str,
           action: str, reviewer_id: str, verification_scope: str,
           evidence_paths: list[str]) -> dict:
    bundle, project_root = bundle.resolve(), project_root.resolve()
    bundle.relative_to(project_root)
    validator = _load_validator()
    hunter = validator.mapping(bundle / "FAILURE_HUNTER.yaml")
    response = bundle / "SOLVER_RESPONSE.yaml"
    independent_path = bundle / "INDEPENDENT_VALIDATION.yaml"
    independent = validator.mapping(independent_path)
    if independent.get("status") != "pass" or independent.get("reviewer_role") != "independent_validator":
        raise ValueError("only a passing independent validator may close/reopen a finding")
    if independent.get("reviewer_id") != reviewer_id:
        raise ValueError("disposition reviewer_id does not match independent validation")
    if independent.get("solver_response_sha256", "").upper() != file_hash(response):
        raise ValueError("independent validation binds an old solver response")
    if finding_id not in set(independent.get("verified_failure_ids", [])):
        raise ValueError("independent validation did not verify this finding")
    findings = {str(item.get("failure_id")) for item in hunter.get("hard_failures", [])}
    if finding_id not in findings:
        raise ValueError("disposition references an unknown Failure Hunter finding")
    evidence = [record(project_root, raw) for raw in evidence_paths]
    ledger = bundle / LEDGER
    lock = bundle / (LEDGER + ".lock")
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.close(descriptor)
    except FileExistsError as exc:
        raise ValueError("disposition ledger is locked by another writer") from exc
    try:
        prior = read_events(ledger)
        if any(item.get("event_id") == event_id for item in prior):
            raise ValueError("disposition event_id already exists")
        event = {
            "schema_version": "1.0", "sequence": len(prior) + 1,
            "event_id": event_id, "finding_id": finding_id, "action": action,
            "reviewer_role": "independent_validator", "reviewer_id": reviewer_id,
            "failure_review_sha256": file_hash(bundle / "FAILURE_HUNTER.yaml"),
            "solver_response_sha256": file_hash(response),
            "independent_validation_sha256": file_hash(independent_path),
            "evidence": evidence, "verification_scope": verification_scope,
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            "previous_event_hash": prior[-1]["event_hash"] if prior else ZERO,
        }
        event["event_hash"] = digest(event)
        # One append is durable enough to detect interruption; a partial line is never accepted.
        with ledger.open("ab") as handle:
            handle.write(canonical(event) + b"\n")
            handle.flush()
            os.fsync(handle.fileno())
        return event
    finally:
        lock.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("append", nargs="?")
    parser.add_argument("--bundle", required=True, type=Path)
    parser.add_argument("--project-root", required=True, type=Path)
    parser.add_argument("--event-id", required=True)
    parser.add_argument("--finding-id", required=True)
    parser.add_argument("--action", choices=["closed", "reopened"], required=True)
    parser.add_argument("--reviewer-id", required=True)
    parser.add_argument("--verification-scope", required=True)
    parser.add_argument("--evidence", action="append", required=True)
    args = parser.parse_args()
    result = append(args.bundle, args.project_root, event_id=args.event_id,
                    finding_id=args.finding_id, action=args.action,
                    reviewer_id=args.reviewer_id, verification_scope=args.verification_scope,
                    evidence_paths=args.evidence)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
