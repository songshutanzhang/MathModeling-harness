#!/usr/bin/env python3
"""Manage G1-G6 business approvals; model routing lives in reasoning_route.py."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "2.0"
ACTOR_ROLE = "参赛队员（匿名）"
GENESIS_HASH = "0" * 64
GATES: dict[str, dict[str, Any]] = {
    "G1": {"title": "题意解释、问题拆解与关键假设", "depends_on": []},
    "G2": {"title": "基线、候选模型与核心算法路线", "depends_on": ["G1"]},
    "G3": {"title": "目标函数、约束、评价指标与验证计划", "depends_on": ["G2"]},
    "G4": {"title": "数据处理、关键参数与生产运行口径", "depends_on": ["G3"]},
    "G5": {"title": "结果解释、关键结论与不确定性判断", "depends_on": ["G4"]},
    "G6": {"title": "最终论文、AI 声明与提交材料", "depends_on": ["G5"]},
}
GATE_ORDER = tuple(GATES)
VALID_STATUSES = {"pending", "approved", "revision_requested", "rejected", "invalidated"}
PACKET_HEADINGS = (
    "## 决策范围", "## 输入及版本", "## 候选方案与备选方案",
    "## 推荐方案与依据", "## 关键假设与风险", "## 验证计划",
    "## 回拨点", "## 推理强度路由（独立于审批）", "## AI 合规分类",
)
PLACEHOLDER_RE = re.compile(r"\b(?:TODO|TBD)\b|待补充|待填写|TODO：", re.I)
IDENTITY_RE = re.compile(r"(?:姓名|学号|指导教师|学校名称|参赛学校|所在学校|赛区)\s*[:：]")


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def event_digest(event: dict[str, Any]) -> str:
    return sha256_bytes(canonical(event).encode("utf-8"))


def resolve_scoped(project_root: Path, raw: str | Path) -> tuple[Path, str]:
    root = project_root.resolve()
    candidate = Path(raw)
    path = candidate.resolve() if candidate.is_absolute() else (root / candidate).resolve()
    try:
        relative = path.relative_to(root).as_posix()
    except ValueError as exc:
        raise ValueError(f"path must stay inside project root: {path}") from exc
    return path, relative


def hash_path(path: Path) -> tuple[str, str]:
    if path.is_file():
        return "file", sha256_bytes(path.read_bytes())
    if path.is_dir():
        digest_value = hashlib.sha256()
        for item in sorted(entry for entry in path.rglob("*") if entry.is_file()):
            digest_value.update(item.relative_to(path).as_posix().encode("utf-8"))
            digest_value.update(b"\0")
            digest_value.update(hashlib.sha256(item.read_bytes()).digest())
        return "directory", digest_value.hexdigest()
    raise ValueError(f"artifact does not exist: {path}")


def artifact_record(project_root: Path, raw: str | Path) -> dict[str, str]:
    path, relative = resolve_scoped(project_root, raw)
    kind, digest_value = hash_path(path)
    return {"path": relative, "kind": kind, "sha256": digest_value}


def check_artifact_record(project_root: Path, record: dict[str, Any], label: str) -> list[str]:
    raw = record.get("path")
    if not isinstance(raw, str) or not raw:
        return [f"{label} has no path"]
    try:
        path, _ = resolve_scoped(project_root, raw)
        kind, digest_value = hash_path(path)
    except ValueError as exc:
        return [f"{label}: {exc}"]
    errors = []
    if record.get("kind") != kind:
        errors.append(f"{label} kind changed: {raw}")
    if record.get("sha256") != digest_value:
        errors.append(f"{label} hash changed: {raw}")
    return errors


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"gate file does not exist: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"gate file is not valid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError("gate file root must be a JSON object")
    return value


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def append_event(document: dict[str, Any], gate_id: str, event_type: str, payload: dict[str, Any]) -> None:
    events = document["audit_chain"]
    event = {
        "sequence": len(events) + 1, "recorded_at": utc_now(), "gate_id": gate_id,
        "event_type": event_type, "payload": payload,
        "previous_event_hash": events[-1]["event_hash"] if events else GENESIS_HASH,
    }
    event["event_hash"] = event_digest(event)
    events.append(event)
    document["updated_at"] = event["recorded_at"]


def initial_document() -> dict[str, Any]:
    now = utc_now()
    document = {
        "schema_version": SCHEMA_VERSION, "created_at": now, "updated_at": now,
        "privacy": "不得记录姓名、学校、学号、指导教师或赛区信息",
        "routing_authority": "run/REASONING_ROUTE_LEDGER.jsonl",
        "gates": {
            gate: {
                "title": definition["title"], "depends_on": definition["depends_on"],
                "status": "pending", "decision": None,
            }
            for gate, definition in GATES.items()
        },
        "audit_chain": [],
    }
    append_event(document, "SYSTEM", "initialized", {
        "schema_version": SCHEMA_VERSION, "gate_order": list(GATE_ORDER),
        "routing_authority": document["routing_authority"],
    })
    return document


def validate_chain(document: dict[str, Any]) -> list[str]:
    events = document.get("audit_chain")
    if not isinstance(events, list) or not events:
        return ["audit_chain is missing or empty"]
    errors = []
    previous = GENESIS_HASH
    for sequence, raw in enumerate(events, start=1):
        if not isinstance(raw, dict):
            errors.append(f"audit event {sequence} is not an object")
            continue
        event = dict(raw)
        stored = event.pop("event_hash", None)
        if event.get("sequence") != sequence:
            errors.append(f"audit event sequence mismatch at {sequence}")
        if event.get("previous_event_hash") != previous:
            errors.append(f"audit chain previous hash mismatch at event {sequence}")
        calculated = event_digest(event)
        if stored != calculated:
            errors.append(f"audit event hash mismatch at event {sequence}")
        previous = stored if isinstance(stored, str) else calculated
    return errors


def reconstructed_state(document: dict[str, Any]) -> dict[str, dict[str, Any]]:
    state = {gate: {"status": "pending", "decision": None} for gate in GATE_ORDER}
    for event in document.get("audit_chain", []):
        gate = event.get("gate_id")
        if gate not in state:
            continue
        kind = event.get("event_type")
        if kind == "approved":
            state[gate] = {"status": "approved", "decision": event.get("payload", {}).get("decision")}
        elif kind in {"revision_requested", "rejected", "invalidated"}:
            state[gate] = {"status": kind, "decision": None}
    return state


def load_router():
    path = Path(__file__).resolve().parents[1] / "harness" / "scripts" / "reasoning_route.py"
    spec = importlib.util.spec_from_file_location("reasoning_route", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    return module


def check_route_reference(
    project_root: Path, gate_id: str, reference: dict[str, Any], snapshot_record: dict[str, Any],
) -> list[str]:
    errors = check_artifact_record(project_root, snapshot_record, f"{gate_id} capability snapshot")
    if errors:
        return errors
    required = {"path", "event_id", "event_hash", "task_id"}
    if not isinstance(reference, dict) or not required <= set(reference):
        return [f"{gate_id} route reference is incomplete"]
    try:
        ledger, _ = resolve_scoped(project_root, reference["path"])
        snapshot, _ = resolve_scoped(project_root, snapshot_record["path"])
        expected = load_router().completed_gate_reference(ledger, snapshot, project_root, gate_id)
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        return [f"{gate_id} route reference: {exc}"]
    if canonical(reference) != canonical(expected):
        return [f"{gate_id} route reference does not match latest completed route event"]
    return []


def validate_document(
    document: dict[str, Any], project_root: Path,
    required: list[str] | tuple[str, ...], check_artifacts: bool,
) -> list[str]:
    if document.get('schema_version') == '3.0':
        spec = importlib.util.spec_from_file_location('grouped_gate_compat', Path(__file__).with_name('grouped_gate.py'))
        grouped = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(grouped)
        try:
            grouped.verify_required(document, project_root, required)
            return []
        except (ValueError, OSError, KeyError, TypeError) as exc:
            return [str(exc)]
    errors = []
    if document.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"unsupported schema_version: {document.get('schema_version')}; migrate to 2.0")
    if document.get("routing_authority") != "run/REASONING_ROUTE_LEDGER.jsonl":
        errors.append("gate file routing_authority is invalid")
    gates = document.get("gates")
    if not isinstance(gates, dict):
        return errors + ["gates object is missing"]
    errors.extend(validate_chain(document))
    rebuilt = reconstructed_state(document)
    decision_ids: set[str] = set()
    for gate_id in GATE_ORDER:
        current = gates.get(gate_id)
        if not isinstance(current, dict):
            errors.append(f"missing gate state: {gate_id}")
            continue
        expected_state = {
            "title": GATES[gate_id]["title"], "depends_on": GATES[gate_id]["depends_on"],
            **rebuilt[gate_id],
        }
        if current.get("status") not in VALID_STATUSES:
            errors.append(f"invalid gate status: {gate_id}={current.get('status')}")
        if canonical(current) != canonical(expected_state):
            errors.append(f"gate state does not match audit chain: {gate_id}")
        if current.get("status") != "approved":
            continue
        for dependency in GATES[gate_id]["depends_on"]:
            if gates.get(dependency, {}).get("status") != "approved":
                errors.append(f"{gate_id} is approved while dependency {dependency} is not")
        decision = current.get("decision")
        if not isinstance(decision, dict):
            errors.append(f"approved gate has no decision object: {gate_id}")
            continue
        required_fields = (
            "decision_id", "selected_option", "rationale", "verification_plan",
            "approval_evidence", "actor_role", "rollback_checkpoint", "packet",
            "artifacts", "ai_involvement", "route_reference", "capability_snapshot",
        )
        for field in required_fields:
            if field not in decision or decision[field] in (None, "", []):
                errors.append(f"{gate_id} decision is missing {field}")
        decision_id = decision.get("decision_id")
        if decision_id in decision_ids:
            errors.append(f"duplicate decision_id in audit chain: {decision_id}")
        elif isinstance(decision_id, str):
            decision_ids.add(decision_id)
        if decision.get("actor_role") != ACTOR_ROLE:
            errors.append(f"{gate_id} actor role must remain anonymous")
        ai = decision.get("ai_involvement", {})
        if ai.get("used") is True and not ai.get("categories"):
            errors.append(f"{gate_id} records AI involvement without purpose categories")
        if check_artifacts:
            records = [decision.get("packet"), decision.get("rollback_checkpoint"), *decision.get("artifacts", [])]
            for index, record in enumerate(records, start=1):
                if not isinstance(record, dict):
                    errors.append(f"{gate_id} artifact record {index} is invalid")
                else:
                    errors.extend(check_artifact_record(project_root, record, f"{gate_id} artifact {index}"))
            if isinstance(decision.get("capability_snapshot"), dict):
                errors.extend(check_route_reference(
                    project_root, gate_id, decision.get("route_reference"), decision["capability_snapshot"],
                ))
    for gate_id in required:
        if gate_id not in GATES:
            errors.append(f"unknown required gate: {gate_id}")
        elif gates.get(gate_id, {}).get("status") != "approved":
            errors.append(f"required gate {gate_id} is not approved ({gates.get(gate_id, {}).get('status', 'missing')})")
    if IDENTITY_RE.search(json.dumps(document, ensure_ascii=False)):
        errors.append("gate audit contains possible identity, school, adviser, or region information")
    return errors


def validate_packet(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8", errors="replace")
    errors = [f"decision packet is missing heading: {heading}" for heading in PACKET_HEADINGS if heading not in text]
    if PLACEHOLDER_RE.search(text):
        errors.append("decision packet still contains placeholders")
    if IDENTITY_RE.search(text):
        errors.append("decision packet contains possible identity information")
    return errors


def fail_if_errors(errors: list[str]) -> None:
    if errors:
        raise ValueError("; ".join(errors))


def invalidate_downstream(document: dict[str, Any], gate_id: str, reason: str, caused_by_event: str) -> list[str]:
    invalidated = []
    for downstream in GATE_ORDER[GATE_ORDER.index(gate_id) + 1:]:
        state = document["gates"][downstream]
        if state["status"] == "pending":
            continue
        state.update(status="invalidated", decision=None)
        append_event(document, downstream, "invalidated", {
            "reason": reason, "caused_by": gate_id, "caused_by_event": caused_by_event,
        })
        invalidated.append(downstream)
    return invalidated


def command_init(args: argparse.Namespace) -> None:
    gate_file, _ = resolve_scoped(args.project_root, args.file)
    if gate_file.exists():
        raise ValueError(f"gate file already exists: {gate_file}")
    write_json(gate_file, initial_document())
    print(f"PASS: initialized {gate_file}")


def command_status(args: argparse.Namespace) -> None:
    gate_file, _ = resolve_scoped(args.project_root, args.file)
    document = read_json(gate_file)
    if document.get('schema_version') == '3.0':
        fail_if_errors(validate_document(document, args.project_root, [], True))
        print('PASS: grouped v3 (route / execution / delivery); use grouped_gate.py status for phase details')
        return
    fail_if_errors(validate_document(document, args.project_root, [], False))
    for gate in GATE_ORDER:
        print(f"{gate}: {document['gates'][gate]['status']}")


def command_approve(args: argparse.Namespace) -> None:
    gate_file, gate_relative = resolve_scoped(args.project_root, args.file)
    document = read_json(gate_file)
    if document.get('schema_version') == '3.0':
        raise ValueError('grouped protocol uses grouped_gate.py approve --phase route|delivery; no per-Gate approval')
    # A new approval may only build on still-valid prerequisite evidence and route receipts.
    fail_if_errors(validate_document(document, args.project_root, [], True))
    if any(
        event.get("payload", {}).get("decision", {}).get("decision_id") == args.decision_id
        for event in document["audit_chain"] if event.get("event_type") == "approved"
    ):
        raise ValueError(f"decision_id already exists: {args.decision_id}")
    for prerequisite in GATE_ORDER[:GATE_ORDER.index(args.gate)]:
        if document["gates"][prerequisite]["status"] != "approved":
            raise ValueError(f"cannot approve {args.gate} before {prerequisite}")
    packet_path, _ = resolve_scoped(args.project_root, args.packet)
    fail_if_errors(validate_packet(packet_path))
    router = load_router()
    ledger_path, _ = resolve_scoped(args.project_root, args.route_ledger)
    snapshot_path, _ = resolve_scoped(args.project_root, args.capability_snapshot)
    route_reference = router.completed_gate_reference(ledger_path, snapshot_path, args.project_root, args.gate)
    packet = artifact_record(args.project_root, args.packet)
    rollback = artifact_record(args.project_root, args.rollback_checkpoint)
    artifacts = [artifact_record(args.project_root, item) for item in args.artifact]
    recorded_paths = {packet["path"], rollback["path"], *(item["path"] for item in artifacts)}
    if gate_relative in recorded_paths:
        raise ValueError("HUMAN_GATES.json cannot hash itself as an approval artifact")
    categories = list(dict.fromkeys(args.ai_category or []))
    if args.ai_involvement == "yes" and not categories:
        raise ValueError("AI involvement is yes but no --ai-category was provided")
    if args.ai_involvement == "no" and categories:
        raise ValueError("AI involvement is no but --ai-category was provided")
    if args.gate == "G6":
        paths = [Path(item["path"]) for item in artifacts]
        if not any(path.suffix.lower() == ".docx" for path in paths):
            raise ValueError("G6 must lock the final editable DOCX as an artifact")
        if not any(path.suffix.lower() == ".pdf" for path in paths):
            raise ValueError("G6 must lock the final derived PDF as an artifact")
        if not any(path.name.upper() == "FINAL_DELIVERY.JSON" for path in paths):
            raise ValueError("G6 must lock FINAL_DELIVERY.json as an artifact")
    for label, value in {
        "selected option": args.selected_option, "rationale": args.rationale,
        "verification plan": args.verification, "approval evidence": args.approval_evidence,
    }.items():
        if len(value.strip()) < 4:
            raise ValueError(f"{label} is too short to be auditable")
    decision = {
        "decision_id": args.decision_id, "selected_option": args.selected_option,
        "rationale": args.rationale, "verification_plan": args.verification,
        "approval_evidence": args.approval_evidence, "actor_role": ACTOR_ROLE,
        "approved_at": utc_now(), "packet": packet, "rollback_checkpoint": rollback,
        "artifacts": artifacts,
        "ai_involvement": {"used": args.ai_involvement == "yes", "categories": categories},
        "route_reference": route_reference,
        "capability_snapshot": artifact_record(args.project_root, args.capability_snapshot),
    }
    serialized = json.dumps(decision, ensure_ascii=False)
    if PLACEHOLDER_RE.search(serialized):
        raise ValueError("approval decision contains placeholders")
    if IDENTITY_RE.search(serialized):
        raise ValueError("approval decision contains possible identity information")
    document["gates"][args.gate].update(status="approved", decision=decision)
    append_event(document, args.gate, "approved", {"decision": decision})
    invalidated = invalidate_downstream(document, args.gate, f"upstream gate {args.gate} received a new approval", "approved")
    write_json(gate_file, document)
    print(f"PASS: {args.gate} approved as {args.decision_id}")
    if invalidated:
        print(f"INFO: invalidated downstream gates: {', '.join(invalidated)}")


def command_review(args: argparse.Namespace) -> None:
    gate_file, _ = resolve_scoped(args.project_root, args.file)
    document = read_json(gate_file)
    if document.get('schema_version') == '3.0':
        raise ValueError('grouped protocol uses phase invalidation and revised decision packets; no per-Gate review')
    fail_if_errors(validate_document(document, args.project_root, [], False))
    packet_path, _ = resolve_scoped(args.project_root, args.packet)
    fail_if_errors(validate_packet(packet_path))
    payload = {
        "reason": args.rationale, "approval_evidence": args.approval_evidence,
        "actor_role": ACTOR_ROLE, "packet": artifact_record(args.project_root, args.packet),
    }
    document["gates"][args.gate].update(status=args.status, decision=None)
    append_event(document, args.gate, args.status, payload)
    invalidated = invalidate_downstream(document, args.gate, f"upstream gate {args.gate} is {args.status}", args.status)
    write_json(gate_file, document)
    print(f"PASS: {args.gate} recorded as {args.status}")
    if invalidated:
        print(f"INFO: invalidated downstream gates: {', '.join(invalidated)}")


def command_invalidate(args: argparse.Namespace) -> None:
    gate_file, _ = resolve_scoped(args.project_root, args.file)
    document = read_json(gate_file)
    if document.get('schema_version') == '3.0':
        raise ValueError('use grouped_gate.py invalidate --phase route|execution|delivery')
    fail_if_errors(validate_document(document, args.project_root, [], False))
    document["gates"][args.gate].update(status="invalidated", decision=None)
    append_event(document, args.gate, "invalidated", {"reason": args.reason, "trigger": args.trigger})
    invalidated = invalidate_downstream(document, args.gate, args.reason, "invalidated")
    write_json(gate_file, document)
    print(f"PASS: invalidated {args.gate}")
    if invalidated:
        print(f"INFO: invalidated downstream gates: {', '.join(invalidated)}")


def command_verify(args: argparse.Namespace) -> None:
    gate_file, _ = resolve_scoped(args.project_root, args.file)
    errors = validate_document(read_json(gate_file), args.project_root, args.require or [], args.check_artifacts)
    if errors:
        for error in errors:
            print(f"FAIL: {error}")
        print(f"RESULT: FAIL ({len(errors)} errors)")
        raise SystemExit(1)
    print("RESULT: PASS")


def add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--file", type=Path, required=True)
    parser.add_argument("--project-root", type=Path, required=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init"); add_common(init); init.set_defaults(handler=command_init)
    status = sub.add_parser("status"); add_common(status); status.set_defaults(handler=command_status)
    approve = sub.add_parser("approve"); add_common(approve)
    approve.add_argument("--gate", choices=GATE_ORDER, required=True)
    approve.add_argument("--decision-id", required=True); approve.add_argument("--packet", required=True)
    approve.add_argument("--selected-option", required=True); approve.add_argument("--rationale", required=True)
    approve.add_argument("--verification", required=True); approve.add_argument("--rollback-checkpoint", required=True)
    approve.add_argument("--approval-evidence", required=True); approve.add_argument("--ai-involvement", choices=("yes", "no"), required=True)
    approve.add_argument("--ai-category", action="append"); approve.add_argument("--artifact", action="append", required=True)
    approve.add_argument("--route-ledger", required=True); approve.add_argument("--capability-snapshot", required=True)
    approve.set_defaults(handler=command_approve)
    review = sub.add_parser("review"); add_common(review)
    review.add_argument("--gate", choices=GATE_ORDER, required=True); review.add_argument("--status", choices=("revision_requested", "rejected"), required=True)
    review.add_argument("--packet", required=True); review.add_argument("--rationale", required=True); review.add_argument("--approval-evidence", required=True)
    review.set_defaults(handler=command_review)
    invalidate = sub.add_parser("invalidate"); add_common(invalidate)
    invalidate.add_argument("--gate", choices=GATE_ORDER, required=True); invalidate.add_argument("--reason", required=True)
    invalidate.add_argument("--trigger", choices=("artifact_changed", "scope_changed", "upstream_changed", "manual"), required=True)
    invalidate.set_defaults(handler=command_invalidate)
    verify = sub.add_parser("verify"); add_common(verify)
    verify.add_argument("--require", nargs="*", choices=GATE_ORDER); verify.add_argument("--check-artifacts", action="store_true")
    verify.set_defaults(handler=command_verify)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    args.project_root = args.project_root.resolve()
    try:
        args.handler(args)
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        print(f"FAIL: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
