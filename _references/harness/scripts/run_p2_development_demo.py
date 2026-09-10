#!/usr/bin/env python3
"""Run a deterministic synthetic development experiment for the P2 search tools."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from runtime_support import atomic_json
from math_search_tools import marginal_deletion, partition_joint_search, uniform_baseline


ZONE = [
    {"low": (18.0, 28.0), "medium": (22.0, 38.0), "high": (28.0, 42.0)},
    {"low": (16.0, 22.0), "medium": (22.0, 38.0), "high": (24.0, 52.0)},
    {"low": (15.0, 22.0), "medium": (22.0, 38.0), "high": (25.0, 52.0)},
]


def evaluate(configuration, interaction_gain=1.0):
    power = sum(ZONE[index][choice][0] for index, choice in enumerate(configuration))
    area = sum(ZONE[index][choice][1] for index, choice in enumerate(configuration))
    # A reproducible adjacent-zone interaction; it makes the externality explicit.
    if configuration[0] == "high" and configuration[1] == "low":
        power += interaction_gain
    return {"power": power, "area": area, "feasible": True}


def run() -> dict:
    options = ["low", "medium", "high"]
    baseline = uniform_baseline(options, 3, evaluate, minimum_power=63.0)
    search = partition_joint_search([options] * 3, evaluate, minimum_power=63.0,
                                    incumbent=tuple(baseline["best"]["configuration"]))
    ablation = partition_joint_search(
        [options] * 3, lambda configuration: evaluate(configuration, interaction_gain=0.0),
        minimum_power=63.0, incumbent=tuple(baseline["best"]["configuration"]),
    )
    repeated = []
    for interaction in (0.8, 1.0, 1.2):
        trial = partition_joint_search(
            [options] * 3, lambda configuration, gain=interaction: evaluate(configuration, gain),
            minimum_power=63.0, incumbent=tuple(baseline["best"]["configuration"]),
        )
        repeated.append({"interaction_gain": interaction,
                         "objective_gain": trial["best"]["objective"] - baseline["best"]["objective"]})
    marginal = marginal_deletion(70.0, 120.0, 5.0, 12.0, 1.5, 60.0)
    gain = search["best"]["objective"] - baseline["best"]["objective"]
    return {
        "schema_version": "1.0", "dataset_role": "synthetic_development_not_2023_evaluation",
        "uniform_strong_baseline": baseline, "three_zone_joint_search": search,
        "structural_ablation_no_externality": ablation,
        "repeat_scenarios": repeated,
        "marginal_externality_example": marginal,
        "objective_gain": gain,
        "evaluation_cost_increment": search["evaluations"] - baseline["evaluations"],
        "complexity_decision": "retain" if min(item["objective_gain"] for item in repeated) > 1e-6 else "delete",
        "acceptance": {
            "tight_bound": search["optimality_gap"] == 0,
            "externality_changes_deletion_test": marginal["accept_deletion"],
            "nested_nonregression": search["nested_nonregression_pass"],
            "joint_search_repeated_gain": all(item["objective_gain"] > 1e-6 for item in repeated),
            "structural_ablation_present": ablation["evaluations"] == search["evaluations"],
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = run()
    atomic_json(args.output, result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if all(result["acceptance"].values()) else 2


if __name__ == "__main__":
    raise SystemExit(main())
