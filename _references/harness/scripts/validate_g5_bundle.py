#!/usr/bin/env python3
"""Validate independent Failure Hunter and Ceiling Reviewer evidence."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[1]
DECISION_SCHEMA = json.loads((ROOT / "schemas" / "g5_review.schema.json").read_text(encoding="utf-8"))
DISPOSITION_SCHEMA = json.loads((ROOT / "schemas" / "g5_disposition.schema.json").read_text(encoding="utf-8"))
BINDING_FILE = "ROUTING_BINDING.json"
DISPOSITION_FILE = "FINDING_DISPOSITIONS.jsonl"
ZERO = "0" * 64


def routing_module():
    path = Path(__file__).resolve().with_name("reasoning_route.py")
    spec = importlib.util.spec_from_file_location("reasoning_route_for_g5", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    return module


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def mapping(path: Path) -> dict:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"mapping required: {path}")
    return data


def canonical(value: dict) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")


def event_hash(value: dict) -> str:
    return hashlib.sha256(canonical(value)).hexdigest().upper()


def validate_dispositions(bundle: Path, case_root: Path, hunter: dict, response_path: Path,
                          independent_path: Path, independent: dict) -> dict:
    ledger = bundle / DISPOSITION_FILE
    findings = {str(item.get("failure_id")): item.get("status", "open")
                for item in hunter.get("hard_failures", [])}
    if len(findings) != len(hunter.get("hard_failures", [])):
        raise ValueError("Failure Hunter finding IDs must be unique")
    if not ledger.exists():
        return {"events": 0, "chain_head": None, "statuses": findings,
                "open_ids": {key for key, status in findings.items() if status != "closed"}}
    previous = ZERO
    ids = set()
    lines = ledger.read_text(encoding="utf-8").splitlines()
    if not lines:
        raise ValueError("empty disposition ledger must be absent")
    for sequence, line in enumerate(lines, 1):
        if not line.strip():
            raise ValueError(f"blank/partial disposition line: {sequence}")
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"partial disposition line {sequence}: {exc}") from exc
        errors = list(Draft202012Validator(DISPOSITION_SCHEMA).iter_errors(event))
        if errors:
            raise ValueError(f"invalid disposition event {sequence}: {errors[0].message}")
        stored = event["event_hash"]
        body = {key: value for key, value in event.items() if key != "event_hash"}
        if event["sequence"] != sequence or event["previous_event_hash"] != previous or stored != event_hash(body):
            raise ValueError(f"disposition hash chain mismatch at event {sequence}")
        if event["event_id"] in ids:
            raise ValueError("duplicate disposition event_id")
        ids.add(event["event_id"])
        if event["finding_id"] not in findings:
            raise ValueError("disposition references an unknown Failure Hunter finding")
        if event["failure_review_sha256"] != sha(bundle / "FAILURE_HUNTER.yaml"):
            raise ValueError("disposition does not bind the frozen Failure Hunter review")
        if event["solver_response_sha256"] != sha(response_path):
            raise ValueError("disposition binds an old solver response")
        if event["independent_validation_sha256"] != sha(independent_path):
            raise ValueError("disposition binds an old independent validation")
        if independent.get("status") != "pass" or independent.get("reviewer_role") != "independent_validator":
            raise ValueError("disposition lacks an authorized passing independent validator")
        if event["reviewer_id"] != independent.get("reviewer_id"):
            raise ValueError("disposition reviewer identity mismatch")
        if event["finding_id"] not in set(independent.get("verified_failure_ids", [])):
            raise ValueError("independent validation scope does not include disposition finding")
        for artifact in event["evidence"]:
            path = _resolve_under(case_root, artifact["path"])
            if not path.is_file() or sha(path) != artifact["sha256"]:
                raise ValueError(f"disposition evidence missing or drifted: {artifact['path']}")
        findings[event["finding_id"]] = "closed" if event["action"] == "closed" else "open"
        previous = stored
    return {"events": len(lines), "chain_head": previous, "statuses": findings,
            "open_ids": {key for key, status in findings.items() if status != "closed"}}


def _resolve_under(root: Path, relative: str) -> Path:
    """Resolve one declared artifact without allowing it to escape the case root."""

    root = root.resolve()
    path = (root / relative).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"evidence artifact escapes case root: {relative}") from exc
    return path


def _bound_artifacts(evidence: dict) -> list[tuple[str, str]]:
    """Collect structured path/hash bindings from an Evidence Package."""

    records: list[tuple[str, str]] = []
    model = evidence.get("mathematical_model")
    if isinstance(model, dict) and model.get("contract_path") and model.get("contract_sha256"):
        records.append((str(model["contract_path"]), str(model["contract_sha256"])))
    results = evidence.get("results")
    if isinstance(results, dict) and results.get("path") and results.get("sha256"):
        records.append((str(results["path"]), str(results["sha256"])))
    for section in ("figures", "validation"):
        values = evidence.get(section, [])
        if not isinstance(values, list):
            continue
        for item in values:
            if isinstance(item, dict) and item.get("path") and item.get("sha256"):
                records.append((str(item["path"]), str(item["sha256"])))
    return records


def _infer_case_root(bundle: Path, evidence: dict, records: list[tuple[str, str]]) -> Path:
    declared = evidence.get("artifact_root")
    if declared is not None:
        root = (bundle / str(declared)).resolve()
        if not root.is_dir():
            raise ValueError(f"evidence artifact_root is not a directory: {declared}")
        return root
    candidates = [bundle.resolve(), *bundle.resolve().parents]
    matches = [
        candidate
        for candidate in candidates
        if all(_resolve_under(candidate, relative).is_file() for relative, _ in records)
    ]
    if not matches:
        raise ValueError("cannot locate the case root for evidence artifact bindings")
    # The nearest matching ancestor is the narrowest valid authority boundary.
    return matches[0]


def validate_artifact_bindings(bundle: Path, evidence: dict) -> dict:
    records = _bound_artifacts(evidence)
    if not records:
        return {"artifact_bindings_checked": 0, "artifact_root": None}
    case_root = _infer_case_root(bundle, evidence, records)
    seen: set[str] = set()
    for relative, expected in records:
        normalized = relative.replace("\\", "/")
        if normalized in seen:
            raise ValueError(f"duplicate evidence artifact binding: {relative}")
        seen.add(normalized)
        path = _resolve_under(case_root, relative)
        if not path.is_file():
            raise ValueError(f"evidence artifact is missing: {relative}")
        supplied = expected.upper()
        if len(supplied) != 64 or any(char not in "0123456789ABCDEF" for char in supplied):
            raise ValueError(f"invalid evidence artifact sha256: {relative}")
        if sha(path) != supplied:
            raise ValueError(f"evidence artifact hash mismatch: {relative}")
    return {
        "artifact_bindings_checked": len(records),
        "artifact_root": str(case_root),
    }


def validate_evidence(bundle: Path) -> tuple[dict, str, dict]:
    evidence_path = bundle / "EVIDENCE_PACKAGE.json"
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    required = {"schema_version", "problem_rule_hashes", "assumptions", "mathematical_model", "results", "figures", "baseline", "validation"}
    if not required <= set(evidence):
        raise ValueError("evidence package is incomplete")
    forbidden = {"solver_advocacy", "expected_award", "g2_critic_opinion", "reviewer_opinion"}
    if forbidden & set(evidence):
        raise ValueError("evidence package contains framing context")
    artifact_validation = validate_artifact_bindings(bundle, evidence)
    evidence_hash = sha(evidence_path)
    return evidence, evidence_hash, artifact_validation


def validate(
    bundle: Path, *, route_ledger: Path | None = None,
    capability_snapshot: Path | None = None, project_root: Path | None = None,
    reliability_only: bool = False,
) -> dict:
    evidence, evidence_hash, artifact_validation = validate_evidence(bundle)
    reviews = []
    review_files = [("FAILURE_HUNTER.yaml", "failure_hunter")]
    if not reliability_only:
        review_files.append(("CEILING_REVIEWER.yaml", "ceiling_reviewer"))
    for filename, role in review_files:
        review = mapping(bundle / filename)
        if review.get("role") != role:
            raise ValueError(f"review role mismatch: {filename}")
        if review.get("visibility") != "evidence_package_only" or review.get("other_review_seen") is not False:
            raise ValueError(f"review isolation failed: {filename}")
        if str(review.get("evidence_package_sha256", "")).upper() != evidence_hash:
            raise ValueError(f"review evidence hash mismatch: {filename}")
        score_name = "reliability_score" if role == "failure_hunter" else "competition_upside_score"
        score = review.get(score_name)
        if type(score) not in (int, float) or not 0 <= score <= 100:
            raise ValueError(f"invalid {score_name}: {filename}")
        reviews.append(review)
    response = mapping(bundle / "SOLVER_RESPONSE.yaml")
    if set(response.get("review_ids_addressed", [])) != {item.get("review_id") for item in reviews}:
        raise ValueError("solver response must address both frozen reviews")
    independent_path = bundle / "INDEPENDENT_VALIDATION.yaml"
    independent = mapping(independent_path)
    if independent.get("solver_response_sha256", "").upper() != sha(bundle / "SOLVER_RESPONSE.yaml"):
        raise ValueError("independent validator did not bind the solver response")
    decision = mapping(bundle / "G5_DECISION.yaml")
    decision_schema = DECISION_SCHEMA
    if reliability_only:
        decision_schema = json.loads((ROOT / 'schemas/g5_reliability.schema.json').read_text(encoding='utf-8'))
    decision_errors = list(Draft202012Validator(decision_schema).iter_errors(decision))
    if decision_errors:
        raise ValueError(f"invalid G5 decision: {decision_errors[0].message}")
    action = decision.get("recommended_action")
    case_root = Path(artifact_validation["artifact_root"]) if artifact_validation["artifact_root"] else bundle
    dispositions = validate_dispositions(bundle, case_root, reviews[0], bundle / "SOLVER_RESPONSE.yaml",
                                         independent_path, independent)
    open_hard_ids = dispositions["open_ids"]
    if dispositions["events"]:
        if decision.get("disposition_chain_head") != dispositions["chain_head"]:
            raise ValueError("G5 decision does not bind the current disposition chain head")
    elif decision.get("disposition_chain_head") is not None:
        raise ValueError("G5 decision declares a disposition chain that does not exist")
    if action == "accept" and open_hard_ids:
        raise ValueError("G5 cannot accept with open hard failures")
    if action == "accept" and independent.get("status") != "pass":
        raise ValueError("G5 cannot accept before independent validation passes")
    if decision.get("reliability_score") != reviews[0].get("reliability_score"):
        raise ValueError("decision reliability score must come from Failure Hunter")
    if not reliability_only and decision.get("competition_upside_score") != reviews[1].get("competition_upside_score"):
        raise ValueError("decision upside score must come from Ceiling Reviewer")
    if set(decision.get("hard_failures", [])) != open_hard_ids:
        raise ValueError("decision hard failures must equal the current open findings after dispositions")
    if dispositions["events"] and decision.get("disposition_chain_head") != dispositions["chain_head"]:
        raise ValueError("G5 decision does not bind the latest disposition chain")
    if not dispositions["events"] and decision.get("disposition_chain_head") is not None:
        raise ValueError("G5 decision declares a disposition chain that does not exist")
    if action == "return_to_g2":
        if not decision.get("cost_notice"):
            raise ValueError("G5→G2 requires an explicit cost notice")
        mode = decision.get("execution_mode")
        if mode in {"evaluation_run", "live_competition", "release_candidate"} and not decision.get("human_approval_required"):
            raise ValueError("formal G5→G2 requires human approval")
    result = {
        "evidence_sha256": evidence_hash,
        "open_hard_failures": len(open_hard_ids),
        "open_hard_failure_ids": sorted(open_hard_ids),
        "dispositions": {key: value for key, value in dispositions.items() if key != "open_ids"},
        "action": action,
        "review_protocol": 'reliability_only' if reliability_only else 'legacy_dual_review',
        "isolation_claim": 'artifact-isolated; runtime independence requires a receipt',
        "dispositions": {key: value for key, value in dispositions.items() if key != "open_ids"},
        **artifact_validation,
    }
    route_args = (route_ledger, capability_snapshot, project_root)
    if any(value is not None for value in route_args):
        if not all(value is not None for value in route_args):
            raise ValueError("G5 route verification requires ledger, snapshot, and project root")
        route = routing_module()
        route_result = route.validate_bundle_binding(
            bundle / BINDING_FILE, route_ledger, capability_snapshot, project_root,
            bundle_kind="g5", frozen_input_sha256=evidence_hash,
            expected_outputs=[bundle / filename for filename, _ in review_files],
            expected_roles={role for _, role in review_files},
        )
        if route_result["topology"] not in {"single", "dual_review"}:
            raise ValueError("G5 route topology must be dual_review or an explicit single fallback")
        result["route"] = route_result
    elif (bundle / BINDING_FILE).exists():
        raise ValueError("G5 route binding exists but no route ledger/snapshot was supplied")
    else:
        result["route"] = {"evidence_confidence": "legacy_missing"}
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle", required=True, type=Path)
    parser.add_argument("--route-ledger", type=Path)
    parser.add_argument("--capability-snapshot", type=Path)
    parser.add_argument("--project-root", type=Path)
    parser.add_argument("--reliability-only", action='store_true', help='Validate the hard gate without loading an upside reviewer')
    args = parser.parse_args()
    result = validate(
        args.bundle.resolve(), route_ledger=args.route_ledger,
        capability_snapshot=args.capability_snapshot, project_root=args.project_root,
        reliability_only=args.reliability_only,
    )
    print("PASS: " + json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
