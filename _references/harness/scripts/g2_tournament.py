#!/usr/bin/env python3
"""Build a blind G2 critic package and validate tournament chronology."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[1]
CANDIDATE_SCHEMA = json.loads((ROOT / "schemas" / "g2_candidate.schema.json").read_text(encoding="utf-8"))
SELECTION_SCHEMA = json.loads((ROOT / "schemas" / "g2_route_selection.schema.json").read_text(encoding="utf-8"))
BLIND_FILE = "BLIND_CRITIC_INPUT.json"
BINDING_FILE = "ROUTING_BINDING.json"


def routing_module():
    path = Path(__file__).resolve().with_name("reasoning_route.py")
    spec = importlib.util.spec_from_file_location("reasoning_route_for_g2", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    return module


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def load_mapping(path: Path) -> dict:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"mapping required: {path}")
    return data


def load_candidates(bundle: Path) -> list[tuple[Path, dict]]:
    paths = sorted((bundle / "candidates").glob("*.yaml"))
    if len(paths) < 2:
        raise ValueError("G2 tournament requires at least two candidates")
    result = []
    seen: set[str] = set()
    freeze_hash = sha(bundle / "PROBLEM_FREEZE.json")
    for path in paths:
        data = load_mapping(path)
        errors = list(Draft202012Validator(CANDIDATE_SCHEMA).iter_errors(data))
        if errors:
            raise ValueError(f"invalid candidate {path.name}: {errors[0].message}")
        if data["candidate_id"] in seen:
            raise ValueError("duplicate candidate_id")
        if data["problem_freeze_sha256"].upper() != freeze_hash:
            raise ValueError(f"problem freeze hash mismatch: {path.name}")
        seen.add(data["candidate_id"])
        result.append((path, data))
    return result


def blind_payload(bundle: Path) -> dict:
    routes = []
    for path, data in load_candidates(bundle):
        anonymous = {key: value for key, value in data.items() if key not in {"candidate_id", "isolation"}}
        label = "ROUTE-" + sha(path)[:10]
        routes.append({"blind_label": label, "candidate_file_sha256": sha(path), "candidate": anonymous})
    return {
        "schema_version": "1.0",
        "problem_freeze_sha256": sha(bundle / "PROBLEM_FREEZE.json"),
        "forbidden_context": ["candidate identity", "solver advocacy", "other critic opinions", "expected award"],
        "routes": routes,
    }


def build_blind(bundle: Path) -> None:
    output = bundle / BLIND_FILE
    if output.exists():
        raise FileExistsError(f"blind package already exists: {output}")
    output.write_text(json.dumps(blind_payload(bundle), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def validate(
    bundle: Path, *, route_ledger: Path | None = None,
    capability_snapshot: Path | None = None, project_root: Path | None = None,
) -> dict:
    expected = blind_payload(bundle)
    actual = json.loads((bundle / BLIND_FILE).read_text(encoding="utf-8"))
    if actual != expected:
        raise ValueError("BLIND_CRITIC_INPUT.json is stale or contains non-blind context")
    labels = {item["blind_label"] for item in expected["routes"]}
    critic = load_mapping(bundle / "CRITIC_REVIEW.yaml")
    if critic.get("visibility") != "blind_critic_input_only" or critic.get("solver_advocacy_seen") is not False:
        raise ValueError("critic isolation declaration failed")
    reviews = critic.get("reviews")
    if not isinstance(reviews, list) or {item.get("blind_label") for item in reviews} != labels:
        raise ValueError("critic must review every and only blind route")
    for review in reviews:
        if review.get("reliability_gate") not in {"PASS", "FAIL"}:
            raise ValueError("critic reliability_gate is invalid")
        for field in ("structure_score", "validation_score", "upside_score"):
            value = review.get(field)
            if not isinstance(value, (int, float)) or not 0 <= value <= 100:
                raise ValueError(f"critic {field} must be in [0,100]")
    prototypes = load_mapping(bundle / "PROTOTYPE_RESULTS.yaml")
    prototype_items = prototypes.get("prototypes", [])
    prototype_labels = {item.get("blind_label") for item in prototype_items}
    prototype_ids = {item.get("prototype_id") for item in prototype_items}
    if not prototype_labels or not prototype_labels <= labels:
        raise ValueError("prototype labels are invalid")
    if None in prototype_ids or len(prototype_ids) != len(prototype_items):
        raise ValueError("prototype_id must be present and unique")
    selection = load_mapping(bundle / "ROUTE_SELECTION.yaml")
    selection_errors = list(Draft202012Validator(SELECTION_SCHEMA).iter_errors(selection))
    if selection_errors:
        raise ValueError(f"invalid route selection: {selection_errors[0].message}")
    selected = selection.get("selected_blind_label")
    if selected not in prototype_labels:
        raise ValueError("selected route must have a prototype")
    selected_review = next(item for item in reviews if item["blind_label"] == selected)
    if selected_review["reliability_gate"] != "PASS" or selection.get("reliability_gate") != "PASS":
        raise ValueError("a reliability-failed route cannot win")
    if selection["reliability_score"] != selected_review["validation_score"]:
        raise ValueError("selection reliability score must come from the selected critic validation score")
    if selection["competition_upside_score"] != selected_review["upside_score"]:
        raise ValueError("selection upside score must come from the selected critic upside score")
    if not set(selection["prototype_ids"]) <= prototype_ids:
        raise ValueError("selection references an unknown prototype")
    result = {"candidates": len(labels), "prototypes": len(prototype_labels), "selected": selected}
    route_args = (route_ledger, capability_snapshot, project_root)
    if any(value is not None for value in route_args):
        if not all(value is not None for value in route_args):
            raise ValueError("G2 route verification requires ledger, snapshot, and project root")
        route = routing_module()
        route_result = route.validate_bundle_binding(
            bundle / BINDING_FILE, route_ledger, capability_snapshot, project_root,
            bundle_kind="g2", frozen_input_sha256=sha(bundle / "PROBLEM_FREEZE.json"),
            expected_outputs=[path for path, _ in load_candidates(bundle)],
            expected_roles={"candidate"},
        )
        if route_result["topology"] not in {"single", "independent_candidates"}:
            raise ValueError("G2 route topology must be independent_candidates or an explicit single fallback")
        result["route"] = route_result
    elif (bundle / BINDING_FILE).exists():
        raise ValueError("G2 route binding exists but no route ledger/snapshot was supplied")
    else:
        result["route"] = {"evidence_confidence": "legacy_missing"}
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("build-blind", "validate"):
        item = sub.add_parser(name)
        item.add_argument("--bundle", required=True, type=Path)
        if name == "validate":
            item.add_argument("--route-ledger", type=Path)
            item.add_argument("--capability-snapshot", type=Path)
            item.add_argument("--project-root", type=Path)
    args = parser.parse_args()
    bundle = args.bundle.resolve()
    if args.command == "build-blind":
        build_blind(bundle)
        print(f"PASS: created {bundle / BLIND_FILE}")
    else:
        result = validate(
            bundle, route_ledger=args.route_ledger,
            capability_snapshot=args.capability_snapshot, project_root=args.project_root,
        )
        print("PASS: " + json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
