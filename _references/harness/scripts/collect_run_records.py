#!/usr/bin/env python3
"""Collect evidence-bounded records from historical training runs.

Missing cost telemetry remains missing. The collector never converts file
counts or timestamps into invented token, latency, or quality measurements.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[1]
RUN_RECORD_SCHEMA = json.loads(
    (ROOT / "schemas" / "harness_run_record.schema.json").read_text(encoding="utf-8")
)


MARKERS = {
    "problem_freeze": "modeling/g2/PROBLEM_FREEZE.json",
    "g2_selection": "modeling/g2/ROUTE_SELECTION.yaml",
    "results_contract": "results/results.json",
    "semantic_paper": "paper/paper.md",
    "lightweight_manifest": "run/LIGHTWEIGHT_MANIFEST.yaml",
    "word_loop_registry": "paper/revisions/WORD_LOOPS.json",
    "model_capability_snapshot": "run/MODEL_CAPABILITY_SNAPSHOT.json",
    "reasoning_route_ledger": "run/REASONING_ROUTE_LEDGER.jsonl",
}


def load_local_script(name: str):
    path = ROOT / "scripts" / name
    spec = importlib.util.spec_from_file_location(name.replace(".py", ""), path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    return module


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def load_mapping(path: Path) -> dict[str, Any]:
    if path.suffix.lower() == ".json":
        data = json.loads(path.read_text(encoding="utf-8"))
    else:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def artifact_record(run: Path, relative: str) -> dict[str, Any]:
    path = run / relative
    if not path.is_file():
        return {"path": relative, "present": False, "evidence": "observed"}
    return {
        "path": relative, "present": True, "bytes": path.stat().st_size,
        "sha256": sha256(path), "evidence": "observed",
    }


def _score(mapping: dict[str, Any], key: str) -> dict[str, Any]:
    value = mapping.get(key)
    if isinstance(value, (int, float)):
        return {"value": value, "evidence": "observed"}
    return {"value": None, "evidence": "missing"}


def latest_g5_bundle(run: Path) -> Path | None:
    root = run / "review" / "g5"
    if not root.is_dir():
        return None

    def version(path: Path) -> tuple[int, str]:
        name = path.name.lower()
        return (int(name[1:]), name) if name.startswith("v") and name[1:].isdigit() else (-1, name)

    bundles = [path for path in root.iterdir() if path.is_dir() and (path / "G5_DECISION.yaml").is_file()]
    return max(bundles, key=version) if bundles else None


def g5_integrity(bundle: Path | None, run: Path | None = None) -> dict[str, Any]:
    if bundle is None:
        return {"value": "missing", "evidence": "observed", "error": None}
    try:
        decision = load_mapping(bundle / 'G5_DECISION.yaml')
        args = {'reliability_only': decision.get('review_protocol') == 'reliability_only'}
        if run is not None and (bundle / 'ROUTING_BINDING.json').is_file():
            args.update(route_ledger=run/'run/REASONING_ROUTE_LEDGER.jsonl',
                        capability_snapshot=run/'run/MODEL_CAPABILITY_SNAPSHOT.json', project_root=run)
        load_local_script("validate_g5_bundle.py").validate(bundle, **args)
    except Exception as exc:  # historical integrity is evidence, not a collector crash
        return {"value": "fail", "evidence": "observed", "error": str(exc)}
    return {"value": "pass", "evidence": "observed", "error": None}


def reasoning_route_telemetry(run: Path) -> dict[str, Any]:
    snapshot = run / MARKERS["model_capability_snapshot"]
    ledger = run / MARKERS["reasoning_route_ledger"]
    empty = {
        "events": None, "tasks": None, "effective_reasoning_efforts": None,
        "effective_topologies": None, "degraded_tasks": None,
        "blocked_tasks": None, "settled": None,
    }
    if not snapshot.is_file() and not ledger.is_file():
        return {"integrity": {"value": "missing", "evidence": "observed", "error": None}, **empty}
    if not snapshot.is_file() or not ledger.is_file():
        missing = "capability snapshot" if not snapshot.is_file() else "route ledger"
        return {"integrity": {"value": "fail", "evidence": "observed", "error": f"missing {missing}"}, **empty}
    try:
        route = load_local_script("reasoning_route.py")
        result = route.validate_ledger(ledger, snapshot, run)
        events = route.read_ledger(ledger)
    except Exception as exc:  # malformed historical evidence remains visible without becoming trusted
        return {"integrity": {"value": "fail", "evidence": "observed", "error": str(exc)}, **empty}
    applied = [event for event in events if event["status"] in {"applied", "degraded"}]
    states = result["states"]
    return {
        "integrity": {"value": "pass", "evidence": "observed", "error": None},
        "events": result["events"], "tasks": result["tasks"],
        "effective_reasoning_efforts": sorted({event["resolved"]["reasoning_effort"] for event in applied}),
        "effective_topologies": sorted({event["resolved"]["topology"] for event in applied}),
        "degraded_tasks": len({event["task_id"] for event in applied if event["status"] == "degraded"}),
        "blocked_tasks": sum(status == "blocked" for status in states.values()),
        "settled": all(status in {"reassessed", "blocked"} for status in states.values()),
    }


def governed_footprint(run: Path) -> dict[str, Any]:
    """Count reviewable artifacts while excluding dependencies and private inputs."""

    excluded_names = {"node_modules", "official-input", "source_texts", "scratch", "tmp", "__pycache__"}
    counts = {"files": 0, "bytes": 0, "docx": 0, "pdf": 0, "png": 0}
    for root, dirs, files in os.walk(run):
        dirs[:] = [name for name in dirs if name not in excluded_names]
        root_path = Path(root)
        for name in files:
            if name.endswith(".inspect.ndjson"):
                continue
            path = root_path / name
            counts["files"] += 1
            counts["bytes"] += path.stat().st_size
            suffix = path.suffix.lower().lstrip(".")
            if suffix in {"docx", "pdf", "png"}:
                counts[suffix] += 1
    return {**counts, "evidence": "observed", "exclusions": sorted(excluded_names)}


def collect_run(run: Path) -> dict[str, Any]:
    artifacts = {key: artifact_record(run, relative) for key, relative in MARKERS.items()}
    g5_bundle = latest_g5_bundle(run)
    g5_relative = (
        (g5_bundle / "G5_DECISION.yaml").relative_to(run).as_posix()
        if g5_bundle else "review/g5/<missing>/G5_DECISION.yaml"
    )
    artifacts["g5_decision"] = artifact_record(run, g5_relative)
    case_mode_path = run / "compliance" / "CASE_MODE.yaml"
    governance_path = run / "compliance" / "ARTIFACT_GOVERNANCE.json"
    g2_path = run / MARKERS["g2_selection"]
    g5_path = run / g5_relative
    case_mode = load_mapping(case_mode_path) if case_mode_path.is_file() else {}
    governance = load_mapping(governance_path) if governance_path.is_file() else {}
    g2 = load_mapping(g2_path) if g2_path.is_file() else {}
    g5 = load_mapping(g5_path) if g5_path.is_file() else {}
    integrity = g5_integrity(g5_bundle, run)
    route_telemetry = reasoning_route_telemetry(run)
    telemetry_dir = run / 'run' / 'telemetry'
    telemetry = {'status': 'missing', 'path': None}
    if telemetry_dir.is_dir():
        try:
            telemetry = {'status': 'available', 'path': 'run/telemetry',
                         'summary': load_local_script('run_telemetry.py').summarize(telemetry_dir)}
        except Exception as exc:
            telemetry = {'status': 'invalid', 'path': 'run/telemetry', 'error': str(exc)}
    candidate_dir = run / "modeling" / "g2" / "candidates"
    candidates = len(list(candidate_dir.glob("*.yaml"))) if candidate_dir.is_dir() else 0
    artifact_complete = all(artifacts[key]["present"] for key in (
        "problem_freeze", "g2_selection", "results_contract", "g5_decision", "semantic_paper"
    ))
    if not artifact_complete:
        status = "partial"
    elif integrity["value"] == "pass":
        status = "artifact_complete_integrity_valid"
    else:
        status = "artifact_complete_integrity_failed"
    trusted_g5 = integrity["value"] == "pass"
    g5_evidence = "observed" if trusted_g5 else ("integrity_failed" if g5 else "missing")
    return {
        "schema_version": "1.0",
        "run_id": run.name,
        "run_path": run.name,
        "status": status,
        "mode": case_mode.get("mode") or case_mode.get("execution_mode"),
        "artifact_tier": governance.get("resolved_tier") or governance.get("artifact_tier"),
        "route": {
            "g2_candidate_count": {"value": candidates, "evidence": "observed"},
            "g2_selected": {"value": g2.get("selected_blind_label"), "evidence": "observed" if g2 else "missing"},
            "g5_action": {"value": g5.get("recommended_action") if trusted_g5 else None, "evidence": g5_evidence},
            "g5_bundle_path": {"value": g5_bundle.relative_to(run).as_posix() if g5_bundle else None, "evidence": "observed" if g5_bundle else "missing"},
            "g5_integrity": integrity,
        },
        "reasoning_routes": route_telemetry,
        "telemetry": telemetry,
        "quality": {
            "reliability_score": _score(g5, "reliability_score") if trusted_g5 else {"value": None, "evidence": g5_evidence},
            "competition_upside_score": _score(g5, "competition_upside_score") if trusted_g5 else {"value": None, "evidence": g5_evidence},
        },
        "cost": {
            "token_usage": {"value": None, "evidence": "missing"},
            "wall_clock_seconds": {"value": None, "evidence": "missing"},
            "tool_calls": {"value": None, "evidence": "missing"},
            "context_peak": {"value": None, "evidence": "missing"},
        },
        "artifacts": artifacts,
        "governed_footprint": governed_footprint(run),
    }


def collect(runs_root: Path) -> list[dict[str, Any]]:
    records = [collect_run(path) for path in sorted(runs_root.iterdir()) if path.is_dir()]
    validator = Draft202012Validator(RUN_RECORD_SCHEMA)
    for record in records:
        errors = list(validator.iter_errors(record))
        if errors:
            raise ValueError(f"invalid run record {record['run_id']}: {errors[0].message}")
    return records


def summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    artifact_complete = [item for item in records if item["status"].startswith("artifact_complete")]
    integrity_valid = [item for item in records if item["status"] == "artifact_complete_integrity_valid"]
    integrity_failed = [item for item in records if item["status"] == "artifact_complete_integrity_failed"]
    tier_counts: dict[str, int] = {}
    actions: dict[str, int] = {}
    integrity: dict[str, int] = {}
    route_integrity: dict[str, int] = {}
    for item in records:
        tier = item.get("artifact_tier") or "missing"
        tier_counts[tier] = tier_counts.get(tier, 0) + 1
        action_record = item["route"]["g5_action"]
        action = action_record["value"] or action_record["evidence"]
        actions[action] = actions.get(action, 0) + 1
        state = item["route"]["g5_integrity"]["value"]
        integrity[state] = integrity.get(state, 0) + 1
        route_state = item["reasoning_routes"]["integrity"]["value"]
        route_integrity[route_state] = route_integrity.get(route_state, 0) + 1
    return {
        "schema_version": "1.0",
        "runs_observed": len(records),
        "artifact_complete_runs": len(artifact_complete),
        "integrity_valid_runs": len(integrity_valid),
        "integrity_failed_runs": len(integrity_failed),
        "partial_runs": len(records) - len(artifact_complete),
        "artifact_tiers": tier_counts,
        "g5_actions": actions,
        "latest_g5_integrity": integrity,
        "reasoning_route_integrity": route_integrity,
        "cost_telemetry": "missing; no estimates substituted",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs-root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--summary-output", type=Path)
    args = parser.parse_args()
    records = collect(args.runs_root.resolve())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        "".join(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n" for item in records),
        encoding="utf-8",
    )
    result = summary(records)
    if args.summary_output:
        args.summary_output.parent.mkdir(parents=True, exist_ok=True)
        args.summary_output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
