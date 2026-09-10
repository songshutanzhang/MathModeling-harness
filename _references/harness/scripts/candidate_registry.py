#!/usr/bin/env python3
"""Register immutable candidate evidence and produce auditable fair promotions."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from jsonschema import Draft202012Validator

sys.path.insert(0, str(Path(__file__).resolve().parent))
from runtime_support import atomic_json, canonical, digest, read_json, record, verify_record

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = json.loads((ROOT / "schemas/candidate_evidence.schema.json").read_text(encoding="utf-8"))


def validate_candidate(candidate: dict, project_root: Path) -> None:
    errors = list(Draft202012Validator(SCHEMA).iter_errors(candidate))
    if errors:
        raise ValueError(f"candidate schema invalid: {errors[0].message}")
    actual = record(project_root, candidate["artifact"]["path"])
    if actual != candidate["artifact"]:
        raise ValueError("candidate artifact is missing or drifted")
    if candidate['schema_version'] == '1.1':
        verify_record(project_root, candidate['evaluator'])
        cost = read_json(verify_record(project_root, candidate['actual_budget']['receipt']))
        if cost.get('evaluations') != candidate['actual_budget']['evaluations'] or cost.get('observed_seconds') != candidate['actual_budget']['observed_seconds']:
            raise ValueError('actual family budget differs from measurement receipt')
        raw = read_json(verify_record(project_root, candidate['artifact']))
        for key in ('raw_metrics', 'objective', 'feasible', 'definition', 'seeds'):
            if raw.get(key) != candidate[key]:
                raise ValueError(f'candidate differs from raw evaluation: {key}')


def register(directory: Path, project_root: Path, candidate_path: Path) -> dict:
    directory.resolve().relative_to(project_root.resolve())
    candidate = read_json(candidate_path)
    validate_candidate(candidate, project_root)
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / f"{candidate['candidate_id']}.json"
    atomic_json(target, candidate, immutable=True)
    return {"status": "registered", "candidate_id": candidate["candidate_id"],
            "record": record(project_root, target)}


def load_candidates(directory: Path, project_root: Path) -> list[dict]:
    directory.resolve().relative_to(project_root.resolve())
    candidates = [read_json(path) for path in sorted(directory.glob("*.json"))]
    if not candidates:
        raise ValueError("candidate registry is empty")
    seen = set()
    for candidate in candidates:
        validate_candidate(candidate, project_root)
        if candidate["candidate_id"] in seen:
            raise ValueError("duplicate candidate ID")
        seen.add(candidate["candidate_id"])
    return candidates


def _same_protocol(candidate: dict, baseline: dict) -> bool:
    if candidate['schema_version'] != baseline['schema_version']:
        return False
    keys = ['evaluator', 'budget', 'precision', 'sample_group']
    if candidate['schema_version'] == '1.1':
        keys += ['definition', 'seeds']
        if candidate['actual_budget']['evaluations'] != baseline['actual_budget']['evaluations']:
            return False
    return all(canonical(candidate[key]) == canonical(baseline[key]) for key in keys)


def promote(directory: Path, project_root: Path, *, problem_level: str,
            incumbent_id: str | None = None, minimum_gain: float = 0.0) -> dict:
    candidates = load_candidates(directory, project_root)
    baselines = [item for item in candidates if item["problem_level"] == problem_level
                 and item["role"] == "strong_baseline"]
    if len(baselines) != 1:
        raise ValueError("promotion requires exactly one same-level strong baseline")
    baseline = baselines[0]
    eligible, excluded = [], []
    for item in candidates:
        level_ok = item["problem_level"] == problem_level or problem_level in item.get("eligible_for", [])
        reasons = []
        if not level_ok:
            reasons.append("problem_level")
        if item["objective"]["name"] != baseline["objective"]["name"] or item["objective"]["direction"] != baseline["objective"]["direction"]:
            reasons.append("objective_semantics")
        if not _same_protocol(item, baseline):
            reasons.append("comparison_protocol")
        if not item["feasible"]:
            reasons.append("infeasible")
        if reasons:
            excluded.append({"candidate_id": item["candidate_id"], "reasons": reasons})
        else:
            eligible.append(item)
    if baseline not in eligible:
        raise ValueError("strong baseline is not eligible under its own comparison protocol")
    if not any(item["role"] == "ablation" or item.get("ablation_of") for item in eligible):
        raise ValueError("promotion requires at least one structural ablation under the same protocol")
    incumbent = None
    if incumbent_id:
        matches = [item for item in eligible if item["candidate_id"] == incumbent_id]
        if len(matches) != 1:
            raise ValueError("nested incumbent is absent, infeasible, or not fairly evaluated")
        incumbent = matches[0]
    direction = baseline["objective"]["direction"]
    reverse = direction == "maximize"
    ranked = sorted(eligible, key=lambda item: item["objective"]["value"], reverse=reverse)
    selected = ranked[0]
    if incumbent:
        no_worse = selected["objective"]["value"] >= incumbent["objective"]["value"] if reverse else selected["objective"]["value"] <= incumbent["objective"]["value"]
        if not no_worse:
            raise AssertionError("nested feasible promotion regressed despite incumbent injection")
    signed_gain = (selected["objective"]["value"] - baseline["objective"]["value"]) * (1 if reverse else -1)
    proposed_gain = signed_gain
    if signed_gain < minimum_gain:
        selected = sorted([baseline] + ([incumbent] if incumbent else []),
                          key=lambda item: item['objective']['value'], reverse=reverse)[0]
    signed_gain = (selected['objective']['value'] - baseline['objective']['value']) * (1 if reverse else -1)
    return {
        "schema_version": "1.0", "problem_level": problem_level,
        "selected_candidate_id": selected["candidate_id"],
        "selected_objective": selected["objective"],
        "baseline_candidate_id": baseline["candidate_id"],
        "incumbent_candidate_id": incumbent_id,
        "nested_nonregression_pass": incumbent is None or (
            selected["objective"]["value"] >= incumbent["objective"]["value"] if reverse
            else selected["objective"]["value"] <= incumbent["objective"]["value"]),
        "fair_protocol": {key: baseline[key] for key in ("evaluator", "budget", "precision", "sample_group")},
        "ranked_candidate_ids": [item["candidate_id"] for item in ranked],
        "excluded": excluded, "gain_over_strong_baseline": signed_gain,
        "complexity_retained": proposed_gain >= minimum_gain,
        "proposed_gain_over_strong_baseline": proposed_gain,
        "strict_ablation": baseline['schema_version'] == '1.1',
        "candidate_evidence": [{key: item.get(key) for key in (
            'candidate_id', 'artifact', 'definition', 'raw_metrics', 'seeds', 'actual_budget')} for item in eligible],
        "registry_sha256": digest({item["candidate_id"]: item for item in candidates}),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    add = sub.add_parser("register")
    add.add_argument("--registry", required=True, type=Path); add.add_argument("--project-root", required=True, type=Path)
    add.add_argument("--candidate", required=True, type=Path)
    select = sub.add_parser("promote")
    select.add_argument("--registry", required=True, type=Path); select.add_argument("--project-root", required=True, type=Path)
    select.add_argument("--problem-level", required=True); select.add_argument("--incumbent-id")
    select.add_argument("--minimum-gain", type=float, default=0.0); select.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.action == "register":
        result = register(args.registry, args.project_root, args.candidate)
    else:
        result = promote(args.registry, args.project_root, problem_level=args.problem_level,
                         incumbent_id=args.incumbent_id, minimum_gain=args.minimum_gain)
        if args.output:
            atomic_json(args.output, result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
