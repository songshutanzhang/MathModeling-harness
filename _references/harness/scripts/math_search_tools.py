#!/usr/bin/env python3
"""Reusable fractional-objective, marginal-externality, and partition-search tools."""
from __future__ import annotations

from itertools import product
import math


def marginal_deletion(power: float, area: float, removed_power: float, removed_area: float,
                      externality_gain: float, minimum_power: float) -> dict:
    if area <= 0 or removed_area <= 0 or removed_area >= area:
        raise ValueError("areas must satisfy 0 < removed_area < area")
    if min(power, removed_power, externality_gain, minimum_power) < 0:
        raise ValueError("power terms must be nonnegative")
    before = power / area
    after_power = power - removed_power + externality_gain
    after_area = area - removed_area
    criterion = externality_gain - removed_power + before * removed_area
    after = after_power / after_area
    return {
        "before_objective": before, "after_objective": after,
        "after_power": after_power, "criterion": criterion,
        "objective_improves": criterion > 0,
        "power_feasible": after_power >= minimum_power,
        "accept_deletion": criterion > 0 and after_power >= minimum_power,
    }


def partition_joint_search(zone_options: list[list[object]], evaluator, *, minimum_power: float,
                           incumbent: tuple[object, ...] | None = None,
                           maximum_evaluations: int | None = None) -> dict:
    if not 3 <= len(zone_options) <= 5:
        raise ValueError("partition search requires 3-5 zones")
    if any(not options for options in zone_options):
        raise ValueError("each zone needs at least one option")
    total = math.prod(len(options) for options in zone_options)
    limit = total if maximum_evaluations is None else min(maximum_evaluations, total)
    configurations = list(product(*zone_options))
    if incumbent is not None:
        if len(incumbent) != len(zone_options) or any(value not in zone_options[i] for i, value in enumerate(incumbent)):
            raise ValueError("incumbent is outside the partition feasible domain")
        configurations.remove(tuple(incumbent))
        configurations.insert(0, tuple(incumbent))
    evaluated = []
    for configuration in configurations[:limit]:
        result = evaluator(configuration)
        power, area = float(result["power"]), float(result["area"])
        feasible = bool(result.get("feasible", True)) and power >= minimum_power and area > 0
        evaluated.append({"configuration": list(configuration), "power": power, "area": area,
                          "objective": power / area if area > 0 else None, "feasible": feasible})
    feasible = [item for item in evaluated if item["feasible"]]
    if not feasible:
        raise ValueError("partition search found no feasible candidate")
    best = max(feasible, key=lambda item: item["objective"])
    incumbent_result = next((item for item in evaluated if incumbent is not None and item["configuration"] == list(incumbent)), None)
    if incumbent_result is not None and incumbent_result["feasible"] and best["objective"] < incumbent_result["objective"]:
        best = incumbent_result
    exhaustive = len(evaluated) == total
    upper_bound = best["objective"] if exhaustive else None
    return {
        "zones": len(zone_options), "domain_size": total, "evaluations": len(evaluated),
        "exhaustive": exhaustive, "best": best, "incumbent_injected": incumbent is not None,
        "nested_nonregression_pass": incumbent_result is None or best["objective"] >= incumbent_result["objective"],
        "objective_upper_bound": upper_bound,
        "optimality_gap": 0.0 if exhaustive else None,
        "claim_scope": "global_on_declared_discrete_partition_domain" if exhaustive else "best_found_no_global_claim",
    }


def uniform_baseline(options: list[object], zones: int, evaluator, *, minimum_power: float) -> dict:
    evaluated = []
    for option in options:
        configuration = tuple([option] * zones)
        result = evaluator(configuration)
        power, area = float(result["power"]), float(result["area"])
        feasible = bool(result.get("feasible", True)) and power >= minimum_power and area > 0
        evaluated.append({"configuration": list(configuration), "power": power, "area": area,
                          "objective": power / area if area > 0 else None, "feasible": feasible})
    feasible = [item for item in evaluated if item["feasible"]]
    if not feasible:
        raise ValueError("uniform baseline has no feasible candidate")
    return {"evaluations": len(evaluated), "best": max(feasible, key=lambda item: item["objective"]),
            "budget_entitlement": len(options) ** zones}
