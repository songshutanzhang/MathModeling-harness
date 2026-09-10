#!/usr/bin/env python3
"""Counterfactual contract replay for the vNext reasoning router.

This ablation measures routing auditability on historical run metadata. It does
not claim model-quality or cost improvements because those runs lack effective
setting, token, and topology receipts.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


TASKS = (
    ("g2_candidate_generation", "independent_candidates"),
    ("g5_failure_review", "dual_review"),
)


def load_records(path: Path) -> list[dict[str, Any]]:
    records = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError(f"run record line {line_number} is not an object")
        records.append(value)
    return records


def ablate(records: list[dict[str, Any]]) -> dict[str, Any]:
    eligible = [record for record in records if record.get("status", "").startswith("artifact_complete")]
    opportunities = len(eligible) * len(TASKS)
    scenarios = [
        {
            "scenario": "legacy_gate_embedded_router",
            "training_route_executable_without_human_gate": False,
            "effective_setting_verified_tasks": 0,
            "topology_verified_tasks": 0,
            "explicit_degraded_tasks": None,
            "unverifiable_tasks": opportunities,
            "interpretation": "Historical artifacts predate independent route receipts; no claim of effective effort or independent topology is accepted.",
        },
        {
            "scenario": "vnext_fixed_high_single_runtime",
            "training_route_executable_without_human_gate": True,
            "effective_setting_verified_tasks": opportunities,
            "topology_verified_tasks": 0,
            "explicit_degraded_tasks": opportunities,
            "unverifiable_tasks": 0,
            "interpretation": "A fixed high/single runtime remains usable, but every G2/G5 independence request is disclosed as degraded.",
        },
        {
            "scenario": "vnext_ultra_isolated_runtime",
            "training_route_executable_without_human_gate": True,
            "effective_setting_verified_tasks": opportunities,
            "topology_verified_tasks": opportunities,
            "explicit_degraded_tasks": 0,
            "unverifiable_tasks": 0,
            "interpretation": "Full credit requires effective-setting receipts plus distinct-context topology receipts bound to the frozen G2/G5 inputs and outputs.",
        },
    ]
    return {
        "schema_version": "1.0",
        "ablation_type": "counterfactual_contract_replay",
        "historical_runs_observed": len(records),
        "artifact_complete_runs_eligible": len(eligible),
        "bounded_task_opportunities": opportunities,
        "task_classes": [task for task, _ in TASKS],
        "requested_topologies": [topology for _, topology in TASKS],
        "scenarios": scenarios,
        "quality_effect": {"value": None, "evidence": "missing"},
        "cost_effect": {"value": None, "evidence": "missing"},
        "limitations": [
            "Historical runs contain no MODEL_CAPABILITY_SNAPSHOT or REASONING_ROUTE_LEDGER.",
            "The replay evaluates audit semantics, not mathematical answer quality.",
            "No token, latency, context-peak, or quota telemetry is inferred.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--records", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = ablate(load_records(args.records.resolve()))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
