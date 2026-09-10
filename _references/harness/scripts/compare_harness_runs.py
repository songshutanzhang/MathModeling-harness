#!/usr/bin/env python3
"""Compare two same-protocol harness runs without letting upside hide failures."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "schemas" / "harness_run_metrics.schema.json"


def load_metrics(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    errors = sorted(Draft202012Validator(schema).iter_errors(data), key=lambda e: list(e.path))
    if errors:
        details = "; ".join(f"{list(e.path)}: {e.message}" for e in errors)
        raise ValueError(f"invalid metrics {path}: {details}")
    expected_rate = data["hard_failures"] / data["cases_evaluated"]
    if abs(expected_rate - data["hard_failure_rate"]) > 1e-9:
        raise ValueError(f"hard_failure_rate does not match counts: {path}")
    if data.get("contamination_status", "clean") != "clean":
        raise ValueError(f"contaminated run cannot be compared: {path}")
    return data


def compare(baseline: dict, candidate: dict, tolerance: float) -> dict:
    if baseline["benchmark_id"] != candidate["benchmark_id"]:
        raise ValueError("benchmark_id mismatch")
    if baseline["cases_evaluated"] != candidate["cases_evaluated"]:
        raise ValueError("cases_evaluated mismatch")
    if baseline.get("artifact_tier") != candidate.get("artifact_tier"):
        raise ValueError("artifact_tier mismatch")

    metrics = [
        "hard_failure_rate", "reliability_score", "competition_upside_score",
        "token_usage", "wall_clock_seconds", "tool_calls", "route_diversity",
        "model_family_diversity", "blind_paper_score",
    ]
    deltas = {name: candidate[name] - baseline[name] for name in metrics}
    reliability_pass = (
        candidate["hard_failure_rate"] <= baseline["hard_failure_rate"] + tolerance
        and candidate["reliability_score"] >= baseline["reliability_score"]
    )
    if not reliability_pass:
        decision = "reject_reliability_regression"
    elif candidate["competition_upside_score"] > baseline["competition_upside_score"]:
        decision = "candidate_improves_ceiling"
    elif candidate["competition_upside_score"] == baseline["competition_upside_score"] and (
        candidate["token_usage"] < baseline["token_usage"]
        or candidate["wall_clock_seconds"] < baseline["wall_clock_seconds"]
    ):
        decision = "candidate_improves_efficiency"
    else:
        decision = "no_proven_improvement"
    return {
        "schema_version": "1.0",
        "baseline_run_id": baseline["run_id"],
        "candidate_run_id": candidate["run_id"],
        "benchmark_id": baseline["benchmark_id"],
        "hard_failure_tolerance": tolerance,
        "reliability_gate": "PASS" if reliability_pass else "FAIL",
        "deltas_candidate_minus_baseline": deltas,
        "decision": decision,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", required=True, type=Path)
    parser.add_argument("--candidate", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--hard-failure-tolerance", type=float, default=0.0)
    args = parser.parse_args()
    if args.hard_failure_tolerance < 0:
        parser.error("--hard-failure-tolerance must be non-negative")
    result = compare(
        load_metrics(args.baseline.resolve()),
        load_metrics(args.candidate.resolve()),
        args.hard_failure_tolerance,
    )
    payload = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    print(payload, end="")
    return 0 if result["reliability_gate"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
