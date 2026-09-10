#!/usr/bin/env python3
"""Exercise the active dependency, candidate, review-disposition, telemetry, and P2 loop."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
from runtime_support import atomic_json, file_hash, record
import dependency_preflight
import g5_disposition
import run_orchestrator
import run_telemetry
import run_p2_development_demo
import validate_g5_bundle


def write(path: Path, value: dict) -> Path:
    atomic_json(path, value)
    return path


def run(repo_root: Path, active_root: Path) -> dict:
    preflight = dependency_preflight.inspect(
        repo_root, active_root, packages=["jsonschema", "PyYAML"], executables=["python"])
    if preflight["status"] != "executable":
        raise ValueError("active dependency preflight failed")
    with tempfile.TemporaryDirectory(prefix="mathmodel-p0-canary-") as temporary:
        project = Path(temporary)
        (project / "src").mkdir(); (project / "src/solver.py").write_text("canary-source", encoding="utf-8")
        (project / "input").mkdir(); (project / "input/problem.txt").write_text("synthetic", encoding="utf-8")
        preflight_path = write(project / "run/PREFLIGHT.json", preflight)
        command = (
            "import json,os,pathlib; p=pathlib.Path(os.environ['HARNESS_OUTPUT_DIR'])/'results/candidate.json'; "
            "p.parent.mkdir(parents=True,exist_ok=True); p.write_text(json.dumps({'objective':1.25,'feasible':True}),encoding='utf-8')"
        )
        plan_path = write(project / "run/RUN_PLAN.json", {
            "schema_version": "1.0", "run_id": "p0-canary", "experiment_id": "synthetic-canary",
            "problem_identity": "synthetic-problem-v1", "objective_identity": "synthetic-objective-v1",
            "case_id": "p0-canary", "dataset_role": "structural",
            "budget_seconds": 30, "final_review_reserve_seconds": 5,
            "tasks": [{"task_id": "candidate", "stage": "coding", "kind": "compute",
                       "command": [sys.executable, "-c", command], "dependencies": [],
                       "inputs": ["input/problem.txt"], "sources": ["src"],
                       "outputs": ["results/candidate.json"], "packages": [],
                       "configuration": {"precision": "canary"}, "max_attempts": 2}],
        })
        state = project / ".runtime"
        run_orchestrator.initialize(project, state, plan_path, preflight_path)
        candidate = run_orchestrator.run_task(project, state, "candidate")
        bundle = project / "review/g5/v1"; bundle.mkdir(parents=True)
        result_record = record(project, "results/candidate.json")
        write(bundle / "EVIDENCE_PACKAGE.json", {
            "schema_version": "1.0", "artifact_root": "../../..",
            "problem_rule_hashes": ["A" * 64], "assumptions": ["synthetic canary only"],
            "mathematical_model": "bounded synthetic computation", "results": result_record,
            "figures": [], "baseline": "fixed smoke baseline", "validation": [],
        })
        evidence_hash = file_hash(bundle / "EVIDENCE_PACKAGE.json")
        write(bundle / "FAILURE_HUNTER.yaml", {
            "review_id": "FH-CANARY", "role": "failure_hunter",
            "visibility": "evidence_package_only", "other_review_seen": False,
            "evidence_package_sha256": evidence_hash, "reliability_score": 95,
            "hard_failures": [{"failure_id": "HF-CANARY", "status": "open"}],
        })
        initial_review_hash = file_hash(bundle / "FAILURE_HUNTER.yaml")
        write(bundle / "SOLVER_RESPONSE.yaml", {
            "review_ids_addressed": ["FH-CANARY"], "repair": "added explicit feasibility proof",
        })
        write(project / "results/repair-proof.json", {"feasible": True, "check": "independent recomputation"})
        write(bundle / "INDEPENDENT_VALIDATION.yaml", {
            "solver_response_sha256": file_hash(bundle / "SOLVER_RESPONSE.yaml"), "status": "pass",
            "reviewer_role": "independent_validator", "reviewer_id": "IV-CANARY",
            "verified_failure_ids": ["HF-CANARY"],
        })
        disposition = g5_disposition.append(
            bundle, project, event_id="DISP-CANARY", finding_id="HF-CANARY", action="closed",
            reviewer_id="IV-CANARY", verification_scope="recomputed synthetic feasibility artifact",
            evidence_paths=["results/repair-proof.json"],
        )
        write(bundle / "G5_DECISION.yaml", {
            "schema_version": "1.0", "execution_mode": "training_run",
            "review_bundle_id": "G5-CANARY", "hard_failures": [], "soft_failures": [],
            "validation_quality": 95, "reliability_score": 95, "recommended_action": "accept",
            "review_protocol": "reliability_only", "disposition_chain_head": disposition["event_hash"],
        })
        review = validate_g5_bundle.validate(bundle, reliability_only=True)
        runtime = run_orchestrator.status(project, state)
        telemetry = run_telemetry.summarize(state / "telemetry")
        p2 = run_p2_development_demo.run()
        return {
            "schema_version": "1.0", "dataset_role": "synthetic_structural_canary",
            "qualification": {"state": "pass", "dependency_manifest_sha256": preflight["dependency_manifest_sha256"]},
            "candidate": {"state": candidate["status"], "task_identity": candidate["task_identity"],
                          "outputs": candidate["outputs"]},
            "review": {"state": "pass" if review["action"] == "accept" else "fail",
                       "action": review["action"], "open_hard_failures": review["open_hard_failures"],
                       "disposition_chain_head": review["dispositions"]["chain_head"],
                       "original_review_unchanged": file_hash(bundle / "FAILURE_HUNTER.yaml") == initial_review_hash},
            "merged_status": "pass" if candidate["status"] == "completed" and review["action"] == "accept" else "fail",
            "runtime": runtime, "telemetry": telemetry,
            "unknown_tokens_preserved": telemetry["by_stage"]["coding"]["input_tokens"]["value"] is None,
            "p2_development_acceptance": p2["acceptance"],
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", required=True, type=Path)
    parser.add_argument("--active-root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = run(args.repo_root, args.active_root)
    atomic_json(args.output, result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["merged_status"] == "pass" and all(result["p2_development_acceptance"].values()) else 2


if __name__ == "__main__":
    raise SystemExit(main())
