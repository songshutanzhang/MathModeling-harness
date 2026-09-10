#!/usr/bin/env python3
"""Resolve and verify model effort/topology independently from human gates."""

from __future__ import annotations

import argparse
import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_DIR = ROOT / "schemas"
ZERO = "0" * 64
FORMAL_MODES = {"evaluation_run", "live_competition", "release_candidate"}
EFFORTS = ("none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra")
TOPOLOGIES = ("single", "independent_candidates", "dual_review", "ensemble")
TRANSITIONS = {
    None: {"assessed"},
    "assessed": {"applied", "degraded", "blocked"},
    "applied": {"completed"},
    "degraded": {"completed"},
    "completed": {"reassessed"},
    "blocked": set(),
    "reassessed": set(),
}
FORMAL_DEFAULTS = {
    "g1_interpretation": ("high", "single"),
    "g2_candidate_generation": ("ultra", "independent_candidates"),
    "g2_adjudication": ("max", "single"),
    "g3_formalization": ("max", "single"),
    "g4_implementation": ("high", "single"),
    "g5_failure_review": ("ultra", "dual_review"),
    "g5_ceiling_review": ("ultra", "dual_review"),
    "g5_adjudication": ("max", "single"),
    "g6_final_review": ("ultra", "ensemble"),
}
TRAINING_TOPOLOGY = {
    "g2_candidate_generation": "independent_candidates",
    "g5_failure_review": "dual_review",
    "g5_ceiling_review": "dual_review",
    "architecture_meta_review": "ensemble",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def digest(value: dict[str, Any], *, excluding: str) -> str:
    payload = {key: item for key, item in value.items() if key != excluding}
    return hashlib.sha256(canonical(payload)).hexdigest().upper()


def file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def load_schema(name: str) -> dict[str, Any]:
    return load_json(SCHEMA_DIR / name)


def schema_errors(value: dict[str, Any], name: str) -> list[str]:
    validator = Draft202012Validator(load_schema(name), format_checker=FormatChecker())
    return [error.message for error in validator.iter_errors(value)]


def fail_schema(value: dict[str, Any], name: str) -> None:
    errors = schema_errors(value, name)
    if errors:
        raise ValueError(f"{name}: {errors[0]}")


def scoped(root: Path, raw: str | Path) -> tuple[Path, str]:
    root = root.resolve()
    candidate = Path(raw)
    path = candidate.resolve() if candidate.is_absolute() else (root / candidate).resolve()
    try:
        relative = path.relative_to(root).as_posix()
    except ValueError as exc:
        raise ValueError(f"path escapes project root: {raw}") from exc
    return path, relative


def artifact(root: Path, raw: str | Path) -> dict[str, str]:
    path, relative = scoped(root, raw)
    if not path.is_file():
        raise FileNotFoundError(path)
    return {"path": relative, "sha256": file_sha(path)}


def validate_artifact(root: Path, record: dict[str, str], label: str) -> None:
    path, _ = scoped(root, record.get("path", ""))
    if not path.is_file():
        raise ValueError(f"{label} is missing: {record.get('path')}")
    if file_sha(path) != str(record.get("sha256", "")).upper():
        raise ValueError(f"{label} hash mismatch: {record.get('path')}")


def seal_snapshot(source: dict[str, Any]) -> dict[str, Any]:
    result = dict(source)
    result["snapshot_sha256"] = digest(result, excluding="snapshot_sha256")
    validate_snapshot_value(result)
    return result


def validate_snapshot_value(snapshot: dict[str, Any]) -> dict[str, Any]:
    fail_schema(snapshot, "model_capability_snapshot.schema.json")
    if snapshot["snapshot_sha256"] != digest(snapshot, excluding="snapshot_sha256"):
        raise ValueError("capability snapshot self hash mismatch")
    models = snapshot["models"]
    model_ids = [item["model_id"] for item in models]
    if len(model_ids) != len(set(model_ids)):
        raise ValueError("capability snapshot has duplicate model_id")
    current = snapshot["current"]
    model = next((item for item in models if item["model_id"] == current["model_id"]), None)
    if model is None:
        raise ValueError("current model is absent from capability snapshot")
    if current["reasoning_effort"] not in model["supported_reasoning_efforts"]:
        raise ValueError("current reasoning effort is unsupported by current model")
    if "single" not in snapshot["supported_topologies"]:
        raise ValueError("runtime must declare single topology")
    supported_efforts = {effort for item in models for effort in item["supported_reasoning_efforts"]}
    for topology, efforts in snapshot["topology_effort_requirements"].items():
        if topology not in snapshot["supported_topologies"]:
            raise ValueError(f"topology requirement declared for unsupported topology: {topology}")
        if not set(efforts) <= supported_efforts:
            raise ValueError(f"topology effort requirement is unsupported: {topology}")
    return snapshot


def validate_snapshot(path: Path) -> dict[str, Any]:
    return validate_snapshot_value(load_json(path))


def seal_topology(source: dict[str, Any]) -> dict[str, Any]:
    result = dict(source)
    result["receipt_sha256"] = digest(result, excluding="receipt_sha256")
    return result


def validate_topology_value(receipt: dict[str, Any], project_root: Path) -> dict[str, Any]:
    fail_schema(receipt, "topology_execution_receipt.schema.json")
    if receipt["receipt_sha256"] != digest(receipt, excluding="receipt_sha256"):
        raise ValueError("topology receipt self hash mismatch")
    units = receipt["execution_units"]
    unit_ids = [item["unit_id"] for item in units]
    contexts = [item["context_id"] for item in units]
    if len(unit_ids) != len(set(unit_ids)):
        raise ValueError("topology receipt has duplicate unit_id")
    if len(contexts) != len(set(contexts)):
        raise ValueError("topology receipt does not prove distinct contexts")
    for unit in units:
        if unit["visible_input_sha256"] != receipt["frozen_input_sha256"]:
            raise ValueError("topology unit visible input differs from frozen input")
        validate_artifact(project_root, unit["output"], f"topology unit {unit['unit_id']} output")
    return receipt


def validate_topology(path: Path, project_root: Path) -> dict[str, Any]:
    return validate_topology_value(load_json(path), project_root)


def read_ledger(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    events = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError(f"ledger line {line_number} is not an object")
        events.append(value)
    return events


def append_event(path: Path, event: dict[str, Any]) -> dict[str, Any]:
    events = read_ledger(path)
    event = dict(event)
    event.update({
        "schema_version": "1.0",
        "sequence": len(events) + 1,
        "event_id": "RR-" + uuid.uuid4().hex[:16].upper(),
        "recorded_at": utc_now(),
        "previous_event_hash": events[-1]["event_hash"] if events else ZERO,
    })
    event["event_hash"] = digest(event, excluding="event_hash")
    fail_schema(event, "reasoning_route_event.schema.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
    return event


def current_model(snapshot: dict[str, Any]) -> dict[str, str]:
    return {
        "model_id": snapshot["current"]["model_id"],
        "reasoning_effort": snapshot["current"]["reasoning_effort"],
        "topology": "single",
    }


def default_request(snapshot: dict[str, Any], mode: str, task_class: str) -> dict[str, str]:
    route = current_model(snapshot)
    if mode in FORMAL_MODES:
        effort, topology = FORMAL_DEFAULTS.get(task_class, ("high", "single"))
        eligible = [
            item["model_id"] for item in snapshot["models"]
            if effort in item["supported_reasoning_efforts"]
        ]
        model_id = route["model_id"] if route["model_id"] in eligible else (eligible[0] if eligible else route["model_id"])
        route.update(model_id=model_id, reasoning_effort=effort, topology=topology)
    else:
        route["topology"] = TRAINING_TOPOLOGY.get(task_class, "single")
    return route


def fallback_routes(snapshot: dict[str, Any], requested: dict[str, str]) -> list[dict[str, str]]:
    current = current_model(snapshot)
    result = [] if current == requested else [current]
    return result


def assess(
    ledger: Path, snapshot_path: Path, *, mode: str, task_id: str, stage: str,
    task_class: str, gate_id: str | None = None, risk_signals: list[str] | None = None,
    requested_effort: str | None = None, requested_topology: str | None = None,
) -> dict[str, Any]:
    snapshot = validate_snapshot(snapshot_path)
    if mode in FORMAL_MODES and gate_id is None:
        raise ValueError("formal route assessment requires gate_id")
    if mode not in FORMAL_MODES and gate_id is not None:
        raise ValueError("non-formal route assessment must not bind a human gate")
    requested = default_request(snapshot, mode, task_class)
    if requested_effort:
        requested["reasoning_effort"] = requested_effort
    if requested_topology:
        requested["topology"] = requested_topology
    signals = sorted(set(risk_signals or []))
    return append_event(ledger, {
        "task_id": task_id, "execution_mode": mode, "stage": stage,
        "task_class": task_class, "gate_id": gate_id, "status": "assessed",
        "risk_signals": signals, "requested": requested, "resolved": None,
        "capability_snapshot_sha256": snapshot["snapshot_sha256"],
        "application_receipt": None, "topology_receipt": None, "outputs": [],
        "fallback": fallback_routes(snapshot, requested),
        "evidence_confidence": "limited", "limitation": "awaiting effective-setting receipt",
    })


def task_events(events: list[dict[str, Any]], task_id: str) -> list[dict[str, Any]]:
    return [event for event in events if event["task_id"] == task_id]


def latest_task_event(events: list[dict[str, Any]], task_id: str) -> dict[str, Any]:
    matches = task_events(events, task_id)
    if not matches:
        raise ValueError(f"unknown route task: {task_id}")
    return matches[-1]


def _model(snapshot: dict[str, Any], model_id: str) -> dict[str, Any]:
    model = next((item for item in snapshot["models"] if item["model_id"] == model_id), None)
    if model is None:
        raise ValueError(f"effective model is absent from capability snapshot: {model_id}")
    return model


def validate_application_binding(
    receipt: dict[str, Any], assessment: dict[str, Any], resolved: dict[str, str],
    snapshot: dict[str, Any],
) -> None:
    if receipt["task_id"] != assessment["task_id"]:
        raise ValueError("application receipt points to wrong task")
    if receipt["assessment_event_id"] != assessment["event_id"]:
        raise ValueError("application receipt points to wrong assessment")
    effective = {
        "model_id": receipt["effective_model_id"],
        "reasoning_effort": receipt["effective_reasoning_effort"],
        "topology": receipt["effective_topology"],
    }
    if effective != resolved:
        raise ValueError("application receipt disagrees with resolved route")
    model = _model(snapshot, receipt["effective_model_id"])
    if receipt["effective_reasoning_effort"] not in model["supported_reasoning_efforts"]:
        raise ValueError("application receipt reports unsupported reasoning effort")
    if receipt["effective_topology"] not in snapshot["supported_topologies"]:
        raise ValueError("application receipt reports unsupported topology")


def validate_topology_binding(
    receipt: dict[str, Any], assessment: dict[str, Any], resolved: dict[str, str],
    snapshot: dict[str, Any],
) -> None:
    if receipt["task_id"] != assessment["task_id"]:
        raise ValueError("topology receipt points to wrong task")
    if receipt["assessment_event_id"] != assessment["event_id"]:
        raise ValueError("topology receipt points to wrong assessment")
    if receipt["topology"] != resolved["topology"]:
        raise ValueError("topology receipt disagrees with resolved route")
    allowed_efforts = snapshot["topology_effort_requirements"].get(receipt["topology"], [])
    if resolved["reasoning_effort"] not in allowed_efforts:
        raise ValueError("effective effort does not establish the requested isolated topology")


def apply(
    ledger: Path, snapshot_path: Path, receipt_path: Path, *, task_id: str,
    project_root: Path, topology_receipt_path: Path | None = None,
    allow_degraded: bool = False,
) -> dict[str, Any]:
    snapshot = validate_snapshot(snapshot_path)
    events = read_ledger(ledger)
    previous = latest_task_event(events, task_id)
    if previous["status"] != "assessed":
        raise ValueError("route application requires the latest task event to be assessed")
    receipt = load_json(receipt_path)
    fail_schema(receipt, "model_application_receipt.schema.json")
    if not snapshot["supports_effective_setting_receipt"]:
        raise ValueError("capability snapshot does not permit an effective-setting receipt")
    if receipt["task_id"] != task_id or receipt["assessment_event_id"] != previous["event_id"]:
        raise ValueError("application receipt does not bind the assessed task/event")
    topology = receipt["effective_topology"]
    resolved = {
        "model_id": receipt["effective_model_id"],
        "reasoning_effort": receipt["effective_reasoning_effort"],
        "topology": topology,
    }
    validate_application_binding(receipt, previous, resolved, snapshot)
    topology_record = None
    if topology != "single":
        if topology_receipt_path is None:
            raise ValueError("non-single topology requires an isolated execution receipt")
        topology_receipt = validate_topology(topology_receipt_path, project_root)
        validate_topology_binding(topology_receipt, previous, resolved, snapshot)
        topology_record = artifact(project_root, topology_receipt_path)
    exact = resolved == previous["requested"]
    status = "applied" if exact else "degraded"
    if status == "degraded" and not allow_degraded:
        raise ValueError("effective route differs from request; explicit degraded fallback is required")
    limitation = None
    confidence = "verified"
    if status == "degraded":
        confidence = "limited"
        limitation = (
            f"requested {previous['requested']['reasoning_effort']}/{previous['requested']['topology']}; "
            f"effective {resolved['reasoning_effort']}/{resolved['topology']}"
        )
    return append_event(ledger, {
        **{key: previous[key] for key in ("task_id", "execution_mode", "stage", "task_class", "gate_id", "risk_signals", "requested", "capability_snapshot_sha256", "fallback")},
        "status": status, "resolved": resolved,
        "application_receipt": artifact(project_root, receipt_path),
        "topology_receipt": topology_record, "outputs": [],
        "evidence_confidence": confidence, "limitation": limitation,
    })


def block(ledger: Path, *, task_id: str, reason: str) -> dict[str, Any]:
    events = read_ledger(ledger)
    previous = latest_task_event(events, task_id)
    if previous["status"] != "assessed":
        raise ValueError("only an assessed route can be blocked")
    return append_event(ledger, {
        **{key: previous[key] for key in ("task_id", "execution_mode", "stage", "task_class", "gate_id", "risk_signals", "requested", "capability_snapshot_sha256", "fallback")},
        "status": "blocked", "resolved": None, "application_receipt": None,
        "topology_receipt": None, "outputs": [], "evidence_confidence": "blocked",
        "limitation": reason,
    })


def complete(ledger: Path, *, task_id: str, project_root: Path, outputs: list[str]) -> dict[str, Any]:
    events = read_ledger(ledger)
    previous = latest_task_event(events, task_id)
    if previous["status"] not in {"applied", "degraded"}:
        raise ValueError("route completion requires an applied or degraded route")
    records = [artifact(project_root, item) for item in outputs]
    if not records:
        raise ValueError("route completion requires at least one bound output")
    return append_event(ledger, {
        **{key: previous[key] for key in ("task_id", "execution_mode", "stage", "task_class", "gate_id", "risk_signals", "requested", "resolved", "capability_snapshot_sha256", "application_receipt", "topology_receipt", "fallback", "evidence_confidence", "limitation")},
        "status": "completed", "outputs": records,
    })


def reassess(ledger: Path, snapshot_path: Path, *, task_id: str) -> dict[str, Any]:
    snapshot = validate_snapshot(snapshot_path)
    events = read_ledger(ledger)
    previous = latest_task_event(events, task_id)
    if previous["status"] != "completed":
        raise ValueError("reassessment requires a completed bounded task")
    baseline = current_model(snapshot)
    return append_event(ledger, {
        **{key: previous[key] for key in ("task_id", "execution_mode", "stage", "task_class", "gate_id", "risk_signals", "capability_snapshot_sha256", "application_receipt", "topology_receipt", "outputs", "fallback")},
        "status": "reassessed", "requested": baseline, "resolved": baseline,
        "evidence_confidence": "verified", "limitation": None,
    })


def validate_ledger(
    ledger: Path, snapshot_path: Path, project_root: Path, *, require_settled: bool = False,
) -> dict[str, Any]:
    snapshot = validate_snapshot(snapshot_path)
    events = read_ledger(ledger)
    if not events:
        raise ValueError("reasoning route ledger is empty")
    previous_hash = ZERO
    states: dict[str, str] = {}
    assessments: dict[str, dict[str, Any]] = {}
    seen_ids: set[str] = set()
    for sequence, event in enumerate(events, start=1):
        fail_schema(event, "reasoning_route_event.schema.json")
        if event["sequence"] != sequence or event["previous_event_hash"] != previous_hash:
            raise ValueError(f"route ledger chain mismatch at sequence {sequence}")
        if event["event_hash"] != digest(event, excluding="event_hash"):
            raise ValueError(f"route ledger event hash mismatch at sequence {sequence}")
        if event["event_id"] in seen_ids:
            raise ValueError("duplicate route event_id")
        seen_ids.add(event["event_id"])
        previous_hash = event["event_hash"]
        if event["capability_snapshot_sha256"] != snapshot["snapshot_sha256"]:
            raise ValueError("route event capability snapshot binding mismatch")
        prior = states.get(event["task_id"])
        if event["status"] not in TRANSITIONS[prior]:
            raise ValueError(f"invalid route transition for {event['task_id']}: {prior}->{event['status']}")
        states[event["task_id"]] = event["status"]
        if event["status"] == "assessed":
            assessments[event["task_id"]] = event
        else:
            assessment = assessments[event["task_id"]]
            stable_fields = (
                "execution_mode", "stage", "task_class", "gate_id", "risk_signals",
                "capability_snapshot_sha256", "fallback",
            )
            if any(event[field] != assessment[field] for field in stable_fields):
                raise ValueError("route task metadata drifted after assessment")
            if event["status"] != "reassessed" and event["requested"] != assessment["requested"]:
                raise ValueError("route request drifted after assessment")
        if event["status"] in {"applied", "degraded"}:
            receipt_record = event["application_receipt"]
            if receipt_record is None:
                raise ValueError("applied/degraded route lacks application receipt")
            validate_artifact(project_root, receipt_record, "model application receipt")
            receipt_path, _ = scoped(project_root, receipt_record["path"])
            receipt = load_json(receipt_path)
            fail_schema(receipt, "model_application_receipt.schema.json")
            validate_application_binding(receipt, assessment, event["resolved"], snapshot)
            if event["resolved"]["topology"] != "single":
                if event["topology_receipt"] is None:
                    raise ValueError("non-single route lacks topology receipt")
                validate_artifact(project_root, event["topology_receipt"], "topology receipt")
                topology_path, _ = scoped(project_root, event["topology_receipt"]["path"])
                topology_receipt = validate_topology(topology_path, project_root)
                validate_topology_binding(topology_receipt, assessment, event["resolved"], snapshot)
        for index, output in enumerate(event["outputs"], start=1):
            validate_artifact(project_root, output, f"route output {index}")
    if require_settled:
        unsettled = {task: status for task, status in states.items() if status not in {"reassessed", "blocked"}}
        if unsettled:
            raise ValueError(f"route tasks are not settled: {unsettled}")
    return {"events": len(events), "tasks": len(states), "states": states, "chain_head": previous_hash}


def completed_gate_reference(
    ledger: Path, snapshot_path: Path, project_root: Path, gate_id: str,
) -> dict[str, str]:
    validate_ledger(ledger, snapshot_path, project_root)
    events = read_ledger(ledger)
    completed = [event for event in events if event["gate_id"] == gate_id and event["status"] == "completed"]
    if not completed:
        raise ValueError(f"no completed route event for {gate_id}")
    event = completed[-1]
    later = [item for item in events if item["task_id"] == event["task_id"] and item["sequence"] > event["sequence"]]
    if not later or later[-1]["status"] != "reassessed":
        raise ValueError(f"completed high-value route for {gate_id} lacks reassessment")
    return {
        "path": scoped(project_root, ledger)[1],
        "event_id": event["event_id"],
        "event_hash": event["event_hash"],
        "task_id": event["task_id"],
    }


def create_bundle_binding(
    ledger: Path, snapshot_path: Path, project_root: Path, *, task_id: str,
    bundle_kind: str, frozen_input_sha256: str,
) -> dict[str, Any]:
    validate_ledger(ledger, snapshot_path, project_root)
    if bundle_kind not in {"g2", "g5"}:
        raise ValueError("bundle kind must be g2 or g5")
    events = read_ledger(ledger)
    applications = [
        event for event in events
        if event["task_id"] == task_id and event["status"] in {"applied", "degraded"}
    ]
    if not applications:
        raise ValueError(f"route task has no applied/degraded event: {task_id}")
    event = applications[-1]
    expected_class = "g2_candidate_generation" if bundle_kind == "g2" else "g5_failure_review"
    if event["task_class"] != expected_class:
        raise ValueError(f"{bundle_kind} bundle is bound to wrong route task class")
    value = {
        "schema_version": "1.0", "bundle_kind": bundle_kind,
        "task_id": task_id, "application_event_id": event["event_id"],
        "application_event_hash": event["event_hash"],
        "frozen_input_sha256": frozen_input_sha256.upper(),
        "resolved": event["resolved"], "topology_receipt": event["topology_receipt"],
        "evidence_confidence": event["evidence_confidence"],
    }
    value["binding_sha256"] = digest(value, excluding="binding_sha256")
    fail_schema(value, "route_bundle_binding.schema.json")
    return value


def validate_bundle_binding(
    binding_path: Path, ledger: Path, snapshot_path: Path, project_root: Path, *,
    bundle_kind: str, frozen_input_sha256: str, expected_outputs: list[Path],
    expected_roles: set[str] | None = None,
) -> dict[str, Any]:
    summary = validate_ledger(ledger, snapshot_path, project_root)
    binding = load_json(binding_path)
    fail_schema(binding, "route_bundle_binding.schema.json")
    if binding["binding_sha256"] != digest(binding, excluding="binding_sha256"):
        raise ValueError("route bundle binding self hash mismatch")
    if binding["bundle_kind"] != bundle_kind:
        raise ValueError("route bundle kind mismatch")
    if binding["frozen_input_sha256"] != frozen_input_sha256.upper():
        raise ValueError("route bundle frozen input hash mismatch")
    events = read_ledger(ledger)
    matches = [event for event in events if event["event_id"] == binding["application_event_id"]]
    if len(matches) != 1:
        raise ValueError("route bundle application event is missing or duplicated")
    event = matches[0]
    if event["status"] not in {"applied", "degraded"}:
        raise ValueError("route bundle must reference an applied/degraded event")
    if event["task_id"] != binding["task_id"] or event["event_hash"] != binding["application_event_hash"]:
        raise ValueError("route bundle application event binding mismatch")
    if (
        event["resolved"] != binding["resolved"]
        or event["topology_receipt"] != binding["topology_receipt"]
        or event["evidence_confidence"] != binding["evidence_confidence"]
    ):
        raise ValueError("route bundle resolved route binding mismatch")
    expected_class = "g2_candidate_generation" if bundle_kind == "g2" else "g5_failure_review"
    if event["task_class"] != expected_class:
        raise ValueError("route bundle references the wrong task class")
    expected = {(scoped(project_root, path)[1], file_sha(path)) for path in expected_outputs}
    topology = event["resolved"]["topology"]
    if topology == "single":
        if binding["topology_receipt"] is not None:
            raise ValueError("single route must not bind a topology receipt")
        return {**summary, "topology": topology, "evidence_confidence": "limited"}
    receipt_record = binding["topology_receipt"]
    if receipt_record is None:
        raise ValueError("non-single route bundle lacks topology receipt")
    receipt_path, _ = scoped(project_root, receipt_record["path"])
    receipt = validate_topology(receipt_path, project_root)
    if receipt["frozen_input_sha256"] != frozen_input_sha256.upper():
        raise ValueError("topology receipt frozen input hash mismatch")
    actual = {(unit["output"]["path"], unit["output"]["sha256"]) for unit in receipt["execution_units"]}
    if actual != expected:
        raise ValueError("topology receipt outputs do not exactly match bundle outputs")
    if expected_roles is not None and {unit["role"] for unit in receipt["execution_units"]} != expected_roles:
        raise ValueError("topology receipt roles do not match bundle roles")
    return {**summary, "topology": topology, "evidence_confidence": binding["evidence_confidence"]}


def immutable_write(path: Path, value: dict[str, Any]) -> None:
    if path.exists():
        raise FileExistsError(f"immutable output exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    seal = sub.add_parser("snapshot-seal")
    seal.add_argument("--input", required=True, type=Path); seal.add_argument("--output", required=True, type=Path)
    check_snapshot = sub.add_parser("snapshot-validate")
    check_snapshot.add_argument("--snapshot", required=True, type=Path)
    seal_top = sub.add_parser("topology-seal")
    seal_top.add_argument("--input", required=True, type=Path); seal_top.add_argument("--output", required=True, type=Path)
    check_top = sub.add_parser("topology-validate")
    check_top.add_argument("--receipt", required=True, type=Path); check_top.add_argument("--project-root", required=True, type=Path)
    assess_parser = sub.add_parser("assess")
    assess_parser.add_argument("--ledger", required=True, type=Path); assess_parser.add_argument("--snapshot", required=True, type=Path)
    assess_parser.add_argument("--mode", required=True); assess_parser.add_argument("--task-id", required=True)
    assess_parser.add_argument("--stage", required=True); assess_parser.add_argument("--task-class", required=True)
    assess_parser.add_argument("--gate-id"); assess_parser.add_argument("--risk-signal", action="append", default=[])
    assess_parser.add_argument("--requested-effort", choices=EFFORTS); assess_parser.add_argument("--requested-topology", choices=TOPOLOGIES)
    apply_parser = sub.add_parser("apply")
    apply_parser.add_argument("--ledger", required=True, type=Path); apply_parser.add_argument("--snapshot", required=True, type=Path)
    apply_parser.add_argument("--receipt", required=True, type=Path); apply_parser.add_argument("--topology-receipt", type=Path)
    apply_parser.add_argument("--task-id", required=True); apply_parser.add_argument("--project-root", required=True, type=Path)
    apply_parser.add_argument("--allow-degraded", action="store_true")
    block_parser = sub.add_parser("block")
    block_parser.add_argument("--ledger", required=True, type=Path); block_parser.add_argument("--task-id", required=True); block_parser.add_argument("--reason", required=True)
    complete_parser = sub.add_parser("complete")
    complete_parser.add_argument("--ledger", required=True, type=Path); complete_parser.add_argument("--task-id", required=True)
    complete_parser.add_argument("--project-root", required=True, type=Path); complete_parser.add_argument("--output", action="append", required=True)
    reassess_parser = sub.add_parser("reassess")
    reassess_parser.add_argument("--ledger", required=True, type=Path); reassess_parser.add_argument("--snapshot", required=True, type=Path); reassess_parser.add_argument("--task-id", required=True)
    validate_parser = sub.add_parser("validate")
    validate_parser.add_argument("--ledger", required=True, type=Path); validate_parser.add_argument("--snapshot", required=True, type=Path)
    validate_parser.add_argument("--project-root", required=True, type=Path); validate_parser.add_argument("--require-settled", action="store_true")
    bind_parser = sub.add_parser("bind")
    bind_parser.add_argument("--ledger", required=True, type=Path); bind_parser.add_argument("--snapshot", required=True, type=Path)
    bind_parser.add_argument("--project-root", required=True, type=Path); bind_parser.add_argument("--task-id", required=True)
    bind_parser.add_argument("--bundle-kind", required=True, choices=("g2", "g5")); bind_parser.add_argument("--frozen-input-sha256", required=True)
    bind_parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.command == "snapshot-seal": result = seal_snapshot(load_json(args.input)); immutable_write(args.output, result)
    elif args.command == "snapshot-validate": result = validate_snapshot(args.snapshot)
    elif args.command == "topology-seal": result = seal_topology(load_json(args.input)); immutable_write(args.output, result)
    elif args.command == "topology-validate": result = validate_topology(args.receipt, args.project_root)
    elif args.command == "assess": result = assess(args.ledger, args.snapshot, mode=args.mode, task_id=args.task_id, stage=args.stage, task_class=args.task_class, gate_id=args.gate_id, risk_signals=args.risk_signal, requested_effort=args.requested_effort, requested_topology=args.requested_topology)
    elif args.command == "apply": result = apply(args.ledger, args.snapshot, args.receipt, task_id=args.task_id, project_root=args.project_root, topology_receipt_path=args.topology_receipt, allow_degraded=args.allow_degraded)
    elif args.command == "block": result = block(args.ledger, task_id=args.task_id, reason=args.reason)
    elif args.command == "complete": result = complete(args.ledger, task_id=args.task_id, project_root=args.project_root, outputs=args.output)
    elif args.command == "reassess": result = reassess(args.ledger, args.snapshot, task_id=args.task_id)
    elif args.command == "bind":
        result = create_bundle_binding(args.ledger, args.snapshot, args.project_root, task_id=args.task_id, bundle_kind=args.bundle_kind, frozen_input_sha256=args.frozen_input_sha256)
        immutable_write(args.output, result)
    else: result = validate_ledger(args.ledger, args.snapshot, args.project_root, require_settled=args.require_settled)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
