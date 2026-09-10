#!/usr/bin/env python3
"""Preflighted, resumable runner with content identities and atomic output publication."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parent))
from runtime_support import atomic_json, digest, file_hash, input_manifest, read_json, record, runtime_identity, scoped, verify_record, command_runtime
from workflow_state import CATEGORIES, state_path, cost_ledger, complete_external, verify_external, begin_external, refresh_provenance, draft_external

ZERO = "0" * 64
FINAL_KINDS = {"independent_review", "final_review"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_telemetry():
    path = Path(__file__).with_name("run_telemetry.py")
    spec = importlib.util.spec_from_file_location("orchestrator_telemetry", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    return module


def validate_plan(plan: dict) -> None:
    required = {"schema_version", "run_id", "experiment_id", "problem_identity",
                "objective_identity", "tasks"}
    if plan.get("schema_version") != "1.0" or not required <= set(plan):
        raise ValueError("run plan schema/required fields are incomplete")
    for key in ("run_id", "experiment_id", "problem_identity", "objective_identity"):
        if not isinstance(plan[key], str) or len(plan[key].strip()) < 3:
            raise ValueError(f"run plan needs a concrete {key}")
    if not isinstance(plan["tasks"], list) or not plan["tasks"]:
        raise ValueError("run plan needs at least one task")
    ids = [task.get("task_id") for task in plan["tasks"]]
    if any(not isinstance(item, str) or len(item) < 2 for item in ids) or len(ids) != len(set(ids)):
        raise ValueError("task IDs must be unique concrete strings")
    known = set(ids)
    for task in plan["tasks"]:
        if task.get('execution', 'command') not in {'command', 'external'}:
            raise ValueError('unknown task execution mode')
        if task.get('cost_category', 'numeric') not in CATEGORIES:
            raise ValueError('unknown cost category')
        if task.get('execution', 'command') == 'command' and (not isinstance(task.get("command"), list) or not task["command"] or not all(isinstance(v, str) for v in task["command"])):
            raise ValueError(f"task command must be an argv list: {task.get('task_id')}")
        if not isinstance(task.get("outputs"), list) or not task["outputs"]:
            raise ValueError(f"task needs declared outputs: {task.get('task_id')}")
        if set(task.get("dependencies", [])) - known:
            raise ValueError(f"task has unknown dependency: {task.get('task_id')}")
        if task.get("max_attempts", 2) < 1:
            raise ValueError("max_attempts must be positive")
    remaining = {task["task_id"]: set(task.get("dependencies", [])) for task in plan["tasks"]}
    while remaining:
        ready = {key for key, value in remaining.items() if not value}
        if not ready:
            raise ValueError("task graph contains a cycle")
        remaining = {key: value - ready for key, value in remaining.items() if key not in ready}
    budget = plan.get("budget_seconds")
    reserve = plan.get("final_review_reserve_seconds", 0)
    if budget is not None and (type(budget) not in (int, float) or budget <= 0 or reserve < 0 or reserve >= budget):
        raise ValueError("invalid total/final-review budget")


def _event_paths(state_dir: Path) -> list[Path]:
    return sorted((state_dir / "events").glob("*.json"))


def read_events(state_dir: Path) -> list[dict]:
    events, previous = [], ZERO
    for sequence, path in enumerate(_event_paths(state_dir), 1):
        item = read_json(path)
        stored = item.get("event_hash")
        body = {key: value for key, value in item.items() if key != "event_hash"}
        if item.get("sequence") != sequence or item.get("previous_event_hash") != previous or stored != digest(body):
            raise ValueError(f"run event chain mismatch: {path.name}")
        if not path.name.startswith(f"{sequence:06d}-"):
            raise ValueError("run event filename sequence mismatch")
        events.append(item)
        previous = stored
    return events


def append_event(state_dir: Path, event_type: str, payload: dict) -> dict:
    state_dir.mkdir(parents=True, exist_ok=True)
    lock = state_dir / ".events.lock"
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.close(descriptor)
    except FileExistsError as exc:
        raise ValueError("run event ledger is locked") from exc
    try:
        prior = read_events(state_dir)
        item = {"schema_version": "1.0", "sequence": len(prior) + 1,
                "event_id": str(uuid.uuid4()), "event_type": event_type,
                "recorded_at": utc_now(), "payload": payload,
                "previous_event_hash": prior[-1]["event_hash"] if prior else ZERO}
        item["event_hash"] = digest(item)
        target = state_dir / "events" / f"{item['sequence']:06d}-{item['event_id']}.json"
        atomic_json(target, item, immutable=True)
        return item
    finally:
        lock.unlink(missing_ok=True)


def current_revision(state_dir: Path) -> dict:
    revisions = sorted((state_dir / "revisions").glob("*.json"))
    if not revisions:
        raise ValueError("run is not initialized")
    return read_json(revisions[-1])


def initialize(project_root: Path, state_dir: Path, plan_path: Path, preflight_path: Path) -> dict:
    project_root, state_dir = project_root.resolve(), state_path(project_root, state_dir)
    plan = read_json(plan_path)
    validate_plan(plan)
    preflight = read_json(preflight_path)
    if preflight.get("status") != "executable":
        raise ValueError("preflight is blocked; no computation was started")
    _verify_exception(project_root, preflight, plan['run_id'])
    preflight_record = record(project_root, preflight_path)
    plan_record = record(project_root, plan_path)
    revisions = sorted((state_dir / "revisions").glob("*.json"))
    if revisions:
        first = read_json(revisions[0])
        if first["run_id"] != plan["run_id"] or first["experiment_id"] != plan["experiment_id"]:
            raise ValueError("run/experiment identity differs; use a new state directory")
        for key in ("problem_identity", "objective_identity"):
            if first[key] != plan[key]:
                raise ValueError(f"{key} changed; start a new experiment/run")
        latest = read_json(revisions[-1])
        if latest["plan_sha256"] == plan_record["sha256"] and latest["preflight_sha256"] == preflight_record["sha256"]:
            return {"status": "already_initialized", "revision": latest["revision"], "run_id": plan["run_id"]}
    revision = len(revisions) + 1
    value = {
        "schema_version": "1.0", "revision": revision,
        **{key: plan[key] for key in ("run_id", "experiment_id", "problem_identity", "objective_identity")},
        "plan": plan_record, "plan_sha256": plan_record["sha256"],
        "preflight": preflight_record, "preflight_sha256": preflight_record["sha256"],
        "initialized_at": utc_now(),
    }
    atomic_json(state_dir / "revisions" / f"{revision:04d}.json", value, immutable=True)
    append_event(state_dir, "configuration_initialized" if revision == 1 else "configuration_revised",
                 {"revision": revision, "plan_sha256": plan_record["sha256"],
                  "preflight_sha256": preflight_record["sha256"]})
    return {"status": "initialized", "revision": revision, "run_id": plan["run_id"]}


def _verify_exception(project_root: Path, preflight: dict, run_id: str) -> None:
    if preflight.get('exception_receipt'):
        from workflow_state import authorization
        receipt = read_json(verify_record(project_root, preflight['exception_receipt']))
        authorization(project_root, receipt, run_id, 'runtime_capability')
        if not receipt.get('exception') or preflight.get('qualification') != 'not_certified':
            raise ValueError('accepted exception must remain not_certified')


def _plan(project_root: Path, state_dir: Path) -> tuple[dict, dict]:
    revision = current_revision(state_dir)
    path = scoped(project_root, revision["plan"]["path"])
    if file_hash(path) != revision["plan"]["sha256"]:
        raise ValueError("current run plan drifted; initialize a new configuration revision")
    preflight = scoped(project_root, revision["preflight"]["path"])
    if file_hash(preflight) != revision["preflight"]["sha256"] or read_json(preflight).get("status") != "executable":
        raise ValueError("current preflight receipt is missing, drifted, or blocked")
    plan = read_json(path)
    validate_plan(plan)
    _verify_exception(project_root, read_json(preflight), plan['run_id'])
    return revision, plan


def _task(plan: dict, task_id: str) -> dict:
    matches = [task for task in plan["tasks"] if task["task_id"] == task_id]
    if len(matches) != 1:
        raise ValueError(f"unknown task: {task_id}")
    return matches[0]


def _latest_completed(events: list[dict], task_id: str) -> dict | None:
    matches = [event for event in events if event["event_type"] == "task_completed"
               and event["payload"]["task_id"] == task_id]
    return matches[-1] if matches else None


def _verify_outputs(project_root: Path, outputs: list[dict]) -> bool:
    try:
        return all(record(project_root, item["path"])["sha256"] == item["sha256"] for item in outputs)
    except (ValueError, OSError, KeyError):
        return False


def task_identity(project_root: Path, state_dir: Path, plan: dict, task: dict) -> tuple[str, dict]:
    from search_evidence import validate_check
    check_results = [validate_check(project_root, check) for check in task.get('checks', [])]
    paths = [*task.get("inputs", []), *task.get("sources", [])]
    manifest = input_manifest(project_root, paths) if paths else {}
    events = read_events(state_dir)
    dependencies = {}
    dependency_identities = {}
    for dependency in task.get("dependencies", []):
        completed = _latest_completed(events, dependency)
        if completed is None or not _verify_outputs(project_root, completed["payload"]["outputs"]) or not verify_external(project_root, completed['payload']):
            raise ValueError(f"dependency is not currently completed: {dependency}")
        upstream_hash, _ = task_identity(project_root, state_dir, plan, _task(plan, dependency))
        if upstream_hash != completed['payload']['task_identity']:
            raise ValueError(f'dependency identity is stale: {dependency}')
        dependencies[dependency] = completed["payload"]["outputs"]
        dependency_identities[dependency] = upstream_hash
    identity = {
        'read_audit_version': 1 if task.get('read_audit', True) else None,
        'read_auditor_sha256': file_hash(Path(__file__).with_name('audited_python.py')) if task.get('read_audit', True) else None,
        'checks': task.get('checks', []), 'check_results': check_results,
        "task_id": task["task_id"], "stage": task.get("stage"), "kind": task.get("kind", "compute"),
        "command": task.get("command"), "execution": task.get('execution', 'command'),
        "input_manifest": manifest, "dependencies": dependencies,
        'dependency_identities': dependency_identities,
        "configuration": task.get("configuration", {}), "runtime_route": task.get("runtime_route", {}),
        "runtime": command_runtime(task.get('command'), task.get('packages', [])),
    }
    return digest(identity), identity


def _attempt_count(events: list[dict], task_id: str) -> int:
    return sum(event["event_type"] == "task_started" and event["payload"]["task_id"] == task_id for event in events)


def _used_seconds(events: list[dict]) -> float:
    return cost_ledger(events)['active_seconds']


def _check_budget(plan: dict, task: dict, events: list[dict]) -> None:
    if plan.get('deadline'):
        deadline = datetime.fromisoformat(plan['deadline'])
        if deadline.tzinfo is None:
            raise ValueError('deadline needs timezone')
        if datetime.now(timezone.utc) >= deadline:
            raise ValueError('run deadline reached')
    total = plan.get("budget_seconds")
    if total is None:
        return
    remaining = total - _used_seconds(events)
    reserve = plan.get("final_review_reserve_seconds", 0)
    estimate = task.get("estimated_seconds", 0)
    if task.get("kind", "compute") not in FINAL_KINDS and remaining - estimate < reserve:
        raise ValueError("final-review reserve reached; freeze the current best and run independent review")
    if remaining <= 0:
        raise ValueError("run budget exhausted")


def _telemetry_event(plan: dict, task: dict, attempt_id: str, attempt: int,
                     order: int, duration: float, success: bool, identity: dict) -> dict:
    supplied = task.get("telemetry", {})
    missing = {"value": None, "evidence": "missing"}
    return {
        "schema_version": "1.0", "run_id": plan["run_id"],
        "case_id": plan.get("case_id", plan["experiment_id"]),
        "dataset_role": plan.get("dataset_role", "development"),
        "call_id": attempt_id, "stage": task.get("stage", "unknown"), "kind": "tool",
        "attempt": attempt, "execution_order": order, "captured_at": utc_now(),
        "summary": f"{task['task_id']} {'completed' if success else 'failed'}",
        "model_id": supplied.get("model_id"), "reasoning_effort": supplied.get("reasoning_effort"),
        "execution_instance_id": supplied.get("execution_instance_id"),
        "session_or_context_id": supplied.get("session_or_context_id"),
        "failure_class": None if success else "command_failed", "human_intervention": None,
        "prior_output_exposure": supplied.get("prior_output_exposure"),
        "prompt_hash": supplied.get("prompt_hash"), "config_hash": digest(identity["configuration"]),
        "profile_hash": supplied.get("profile_hash"), "profile_version": supplied.get("profile_version"),
        "reviewer_visible_inputs": supplied.get("reviewer_visible_inputs"),
        "reviewer_hidden_inputs": supplied.get("reviewer_hidden_inputs"),
        "active_modules": supplied.get("active_modules"),
        "input_artifact_hashes": identity["input_manifest"],
        "metrics": {
            "input_tokens": dict(missing), "output_tokens": dict(missing), "cached_tokens": dict(missing),
            "wall_clock_seconds": {"value": duration, "evidence": "observed"},
            "tool_calls": {"value": 1, "evidence": "observed"}, "context_peak": dict(missing),
        },
    }


def _quarantine(state_dir: Path, staging: Path, task_id: str, attempt: int) -> str | None:
    if not staging.exists():
        return None
    target = state_dir / "quarantine" / task_id / f"attempt-{attempt:04d}-{uuid.uuid4().hex[:8]}"
    target.parent.mkdir(parents=True, exist_ok=True)
    staging.replace(target)
    return str(target)


def _run_logged(command, *, project_root, environment, timeout, log_dir):
    """Stream bytes directly to disk; logging failure never triggers command replay."""
    handles, warning = [], None
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        handles.append((log_dir / 'stdout.log').open('xb'))
        handles.append((log_dir / 'stderr.log').open('xb'))
    except OSError as exc:
        warning = str(exc)
        for handle in handles:
            handle.close()
        handles = []
    try:
        result = subprocess.run(command, cwd=project_root, env=environment, check=False,
                                timeout=timeout,
                                stdout=handles[0] if handles else None,
                                stderr=handles[1] if handles else None)
        return result, warning
    finally:
        for handle in handles:
            try:
                handle.close()
            except OSError:
                pass


def run_task(project_root: Path, state_dir: Path, task_id: str) -> dict:
    project_root, state_dir = project_root.resolve(), state_path(project_root, state_dir)
    revision, plan = _plan(project_root, state_dir)
    task = _task(plan, task_id)
    events = read_events(state_dir)
    identity_hash, identity = task_identity(project_root, state_dir, plan, task)
    completed = _latest_completed(events, task_id)
    if completed and completed["payload"].get("task_identity") == identity_hash and _verify_outputs(project_root, completed["payload"]["outputs"]) and verify_external(project_root, completed['payload']):
        append_event(state_dir, "task_reused", {"task_id": task_id, "task_identity": identity_hash,
                                                  "completed_event_hash": completed["event_hash"]})
        return {"task_id": task_id, "status": "reused", "task_identity": identity_hash,
                "outputs": completed["payload"]["outputs"]}
    if task.get('execution') == 'external':
        return {'task_id': task_id, 'status': 'awaiting_receipt', 'task_identity': identity_hash}
    _check_budget(plan, task, events)
    marker = state_dir / "running" / f"{task_id}.json"
    if marker.exists():
        raise ValueError(f"task has an interrupted/running marker; recover first: {task_id}")
    attempt = _attempt_count(events, task_id) + 1
    if attempt > task.get("max_attempts", 2):
        raise ValueError(f"task attempt limit exceeded: {task_id}")
    attempt_id = f"{plan['run_id']}:{task_id}:{attempt}:{identity_hash[:12]}"
    staging = state_dir / "staging" / task_id / f"attempt-{attempt:04d}"
    if staging.exists():
        _quarantine(state_dir, staging, task_id, attempt)
    staging.mkdir(parents=True)
    marker_value = {"task_id": task_id, "attempt": attempt, "attempt_id": attempt_id,
                    "task_identity": identity_hash, "staging": str(staging), "started_at": utc_now(),
                    "owner_pid": os.getpid()}
    marker_value['cost_category'] = task.get('cost_category', 'numeric')
    log_dir = state_dir / 'logs' / task_id / f'attempt-{attempt:04d}'
    marker_value['logs'] = {'stdout': str(log_dir / 'stdout.log'), 'stderr': str(log_dir / 'stderr.log')}
    atomic_json(marker, marker_value, immutable=True)
    started = append_event(state_dir, "task_started", {**marker_value, "revision": revision["revision"]})
    environment = os.environ.copy()
    environment.update({"HARNESS_OUTPUT_DIR": str(staging), "HARNESS_PROJECT_ROOT": str(project_root),
                        "HARNESS_TASK_ID": task_id, "HARNESS_ATTEMPT_ID": attempt_id})
    began = time.perf_counter()
    code, failure = 1, None
    try:
        command = task['command']
        if 'python' in Path(command[0]).stem.lower() and task.get('read_audit', True):
            entry = 1
            while entry < len(command) and command[entry].startswith('-') and command[entry] not in {'-c', '-m'}:
                entry += 2 if command[entry] in {'-W', '-X'} else 1
            if entry == len(command):
                raise ValueError('Python task has no auditable entrypoint')
            provenance = input_manifest(project_root, task['provenance_inputs']) if task.get('provenance_inputs') else {}
            dependency_paths = [r['path'] for records in identity['dependencies'].values() for r in records]
            audit_config = staging / '.read-audit.json'
            atomic_json(audit_config, {'root': str(project_root), 'argv': command[entry:],
                'allowed': [*identity['input_manifest'], *provenance, *dependency_paths],
                'ignored': [str(state_dir)] + [str(p) for p in [Path(command[0]).resolve().parent.parent]
                    if p.is_relative_to(project_root) and p != project_root]})
            command = [*command[:entry], str(Path(__file__).with_name('audited_python.py')), str(audit_config)]
        timeout = task.get('timeout_seconds')
        if plan.get('budget_seconds'):
            remaining = plan['budget_seconds'] - _used_seconds(events)
            if task.get('kind') not in FINAL_KINDS:
                remaining -= plan.get('final_review_reserve_seconds', 0)
            timeout = min(timeout or remaining, remaining)
        if plan.get('deadline'):
            remaining = (datetime.fromisoformat(plan['deadline']) - datetime.now(timezone.utc)).total_seconds()
            if remaining <= 0:
                raise ValueError('run deadline reached during preparation')
            timeout = min(timeout or remaining, remaining)
        process, log_warning = _run_logged(command, project_root=project_root,
            environment=environment, timeout=timeout, log_dir=log_dir)
        if log_warning:
            append_event(state_dir, 'log_unavailable', {'task_id': task_id, 'attempt': attempt, 'error': log_warning})
        code = process.returncode
    except subprocess.TimeoutExpired:
        failure = "timeout"
    except OSError as exc:
        failure = f'command_start_failed: {exc}'
    except (ValueError, RuntimeError) as exc:
        failure = f'task_preparation_failed: {exc}'
    duration = time.perf_counter() - began
    if code == 0 and failure is None:
        output_records = []
        committed = False
        try:
            for relative in task["outputs"]:
                source = scoped(staging, relative)
                if not source.is_file():
                    raise ValueError(f"task did not produce declared output: {relative}")
            journal = []
            for relative in task['outputs']:
                target = scoped(project_root, relative)
                backup = state_dir / 'superseded' / task_id / f'attempt-{attempt:04d}' / relative
                if target.exists():
                    backup.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(target, backup)
                journal.append({'path': relative, 'backup': str(backup) if target.exists() else None})
            marker_value['publication'] = journal
            atomic_json(marker, marker_value)
            for relative in task["outputs"]:
                source = scoped(staging, relative)
                target = scoped(project_root, relative)
                target.parent.mkdir(parents=True, exist_ok=True)
                os.replace(source, target)
                output_records.append(record(project_root, relative))
            telemetry = _telemetry_event(plan, task, attempt_id, attempt, len(read_events(state_dir)) + 1, duration, True, identity)
            _load_telemetry().record(state_dir / "telemetry", telemetry)
            completed_event = append_event(state_dir, "task_completed", {
                "task_id": task_id, "attempt": attempt, "attempt_id": attempt_id,
                "task_identity": identity_hash, "identity": identity,
                "outputs": output_records, "wall_clock_seconds": duration,
                "cost_category": task.get('cost_category', 'numeric'),
                'logs': marker_value['logs'],
                "provenance_manifest": input_manifest(project_root, task['provenance_inputs']) if task.get('provenance_inputs') else {},
                "started_event_hash": started["event_hash"],
            })
            committed = True
            marker.unlink(missing_ok=True)
            _quarantine(state_dir, staging, task_id, attempt)
            return {"task_id": task_id, "status": "completed", "attempt": attempt,
                    "task_identity": identity_hash, "outputs": output_records}
        except Exception as exc:
            if committed:
                return {'task_id': task_id, 'status': 'completed', 'attempt': attempt,
                        'task_identity': identity_hash, 'outputs': output_records,
                        'cleanup_pending': str(exc)}
            failure = f"publication_failed: {exc}"
            _rollback_publication(project_root, state_dir, marker_value)
    failure = failure or f"command_exit_{code}"
    quarantined = _quarantine(state_dir, staging, task_id, attempt)
    append_event(state_dir, "task_failed", {"task_id": task_id, "attempt": attempt,
                 "attempt_id": attempt_id, "task_identity": identity_hash, "failure": failure,
                 "quarantine": quarantined, "wall_clock_seconds": duration,
                 "cost_category": task.get('cost_category', 'numeric'),
                 'logs': marker_value['logs'],
                 "started_event_hash": started["event_hash"]})
    marker.unlink(missing_ok=True)
    telemetry = _telemetry_event(plan, task, attempt_id, attempt, len(read_events(state_dir)), duration, False, identity)
    try:
        _load_telemetry().record(state_dir / "telemetry", telemetry)
    except Exception as exc:
        append_event(state_dir, 'telemetry_failed', {'task_id': task_id, 'error': str(exc)})
    return {"task_id": task_id, "status": "failed", "attempt": attempt, "failure": failure}


def _rollback_publication(project_root: Path, state_dir: Path, item: dict) -> None:
    for entry in item.get('publication', []):
        target = scoped(project_root, entry['path'])
        if entry['backup']:
            backup = scoped(state_dir, entry['backup'])
            shutil.copy2(backup, target)
        else:
            target.unlink(missing_ok=True)


def recover(project_root: Path, state_dir: Path) -> dict:
    project_root, state_dir = project_root.resolve(), state_path(project_root, state_dir)
    _revision, plan = _plan(project_root, state_dir)
    recovered = []
    for marker in sorted((state_dir / "running").glob("*.json")):
        item = read_json(marker)
        if item.get('owner_pid'):
            try:
                import psutil
                if psutil.pid_exists(item['owner_pid']):
                    continue
            except ImportError:
                raise ValueError('live-process check needs psutil; do not recover an unknown owner')
        completed = _latest_completed(read_events(state_dir), item['task_id'])
        if completed and completed['payload'].get('attempt_id') == item['attempt_id']:
            marker.unlink(missing_ok=True)
            continue
        _rollback_publication(project_root, state_dir, item)
        staging = scoped(state_dir, item["staging"])
        quarantined = _quarantine(state_dir, staging, item["task_id"], item["attempt"])
        append_event(state_dir, "task_interrupted", {
            **item, "reason": "stale running marker recovered", "quarantine": quarantined,
            "wall_clock_seconds": None,
        })
        marker.unlink(missing_ok=True)
        recovered.append(item["task_id"])
    return {"run_id": plan["run_id"], "status": "recovered", "interrupted_tasks": recovered,
            "approval_policy": "external approval ledgers are preserved and never inferred or reset"}


def status(project_root: Path, state_dir: Path) -> dict:
    project_root, state_dir = project_root.resolve(), state_path(project_root, state_dir)
    revision, plan = _plan(project_root, state_dir)
    events = read_events(state_dir)
    tasks = {}
    for task in plan["tasks"]:
        task_id = task["task_id"]
        marker = state_dir / "running" / f"{task_id}.json"
        completed = _latest_completed(events, task_id)
        current_identity = None
        try:
            current_identity = task_identity(project_root, state_dir, plan, task)[0]
        except ValueError:
            pass
        if marker.exists():
            state = "interrupted_or_running"
        elif completed and completed["payload"].get("task_identity") == current_identity and _verify_outputs(project_root, completed["payload"]["outputs"]) and verify_external(project_root, completed['payload']):
            state = "completed"
        elif completed:
            state = "stale"
        elif any(e["event_type"] == "task_failed" and e["payload"]["task_id"] == task_id for e in events):
            state = "failed"
        else:
            state = "pending"
        if state == 'pending' and (state_dir / 'external' / f'{task_id}.json').exists():
            state = 'awaiting_receipt'
        tasks[task_id] = {"state": state, "current_identity": current_identity,
                          "stage": task.get('stage'), "execution": task.get('execution', 'command'),
                          "dimensions": completed['payload'].get('dimensions', {}) if state == 'completed' else {},
                          "attempts": _attempt_count(events, task_id)}
        if completed and task.get('provenance_inputs'):
            try:
                current_provenance = input_manifest(project_root, task['provenance_inputs'])
                tasks[task_id]['provenance_state'] = 'verified' if completed['payload'].get('provenance_manifest') == current_provenance else 'refresh_required'
                refreshes = [e['payload'] for e in events if e['event_type'] == 'provenance_verified'
                             and e['payload']['task_id'] == task_id]
                if refreshes and refreshes[-1]['task_identity'] == current_identity and refreshes[-1]['provenance_manifest'] == current_provenance:
                    verify_record(project_root, refreshes[-1]['receipt'])
                    tasks[task_id]['provenance_state'] = 'verified'
            except ValueError:
                tasks[task_id]['provenance_state'] = 'missing'
    next_tasks = [t['task_id'] for t in plan['tasks'] if tasks[t['task_id']]['state'] != 'completed'
                  and all(tasks[d]['state'] == 'completed' for d in t.get('dependencies', []))]
    preflight = read_json(scoped(project_root, revision['preflight']['path']))
    gate_vector = None
    if plan.get('human_gate_ledger'):
        gate_path = scoped(project_root, plan['human_gate_ledger'])
        gate_script = Path(__file__).resolve().parents[2] / 'scripts/grouped_gate.py'
        spec = importlib.util.spec_from_file_location('workflow_grouped_gate', gate_script)
        grouped = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(grouped)
        gate_vector = grouped.status_vector(read_json(gate_path), project_root, revision['preflight']['path'])
    provenance_pending = [tid for tid, item in tasks.items() if item.get('provenance_state') in {'refresh_required', 'missing'}]
    return {"schema_version": "1.0", "run_id": plan["run_id"], "revision": revision["revision"],
            "used_seconds": _used_seconds(events), "budget_seconds": plan.get("budget_seconds"),
            "final_review_reserve_seconds": plan.get("final_review_reserve_seconds", 0),
            "tasks": tasks, "next_tasks": next_tasks, "cost_ledger": cost_ledger(events),
            "qualification": preflight.get('qualification', 'not_assessed'),
            "formal_gate_status": gate_vector,
            "provenance_pending": provenance_pending,
            "current_stage": tasks[next_tasks[0]]['stage'] if next_tasks else ('provenance_refresh' if provenance_pending else 'complete'),
            "chain_head": events[-1]["event_hash"] if events else ZERO}


def run_all(project_root: Path, state_dir: Path) -> dict:
    project_root, state_dir = project_root.resolve(), state_path(project_root, state_dir)
    _revision, plan = _plan(project_root, state_dir)
    results = []
    pending = {task["task_id"]: task for task in plan["tasks"]}
    settled = set()
    while pending:
        ready = [task for task in pending.values() if set(task.get("dependencies", [])) <= settled]
        if not ready:
            raise ValueError("no runnable tasks remain")
        for task in ready:
            result = run_task(project_root, state_dir, task["task_id"])
            results.append(result)
            if result["status"] not in {"completed", "reused"}:
                return {"status": result['status'], "results": results}
            settled.add(task["task_id"])
            pending.pop(task["task_id"])
    current = status(project_root, state_dir)
    return {"status": 'provenance_refresh_required' if current['provenance_pending'] else "completed", "results": results}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["init", "run", "run-all", "recover", "status", "complete-external", 'start-external', 'refresh-provenance', 'draft-external'])
    parser.add_argument("--project-root", required=True, type=Path)
    parser.add_argument("--state-dir", required=True, type=Path)
    parser.add_argument("--plan", type=Path)
    parser.add_argument("--preflight", type=Path)
    parser.add_argument("--task-id")
    parser.add_argument('--receipt', type=Path)
    args = parser.parse_args()
    args.project_root = args.project_root.resolve()
    args.state_dir = state_path(args.project_root, args.state_dir)
    for field in ('plan', 'preflight', 'receipt'):
        if getattr(args, field):
            setattr(args, field, scoped(args.project_root, getattr(args, field)))
    if args.action == "init":
        if not args.plan or not args.preflight:
            parser.error("init requires --plan and --preflight")
        result = initialize(args.project_root, args.state_dir, args.plan, args.preflight)
    elif args.action == 'draft-external':
        if not args.task_id or not args.receipt:
            parser.error('draft-external requires --task-id and --receipt (new draft path)')
        result = draft_external(args.project_root, args.state_dir, args.task_id, args.receipt)
    elif args.action == 'start-external':
        if not args.task_id:
            parser.error('start-external requires --task-id')
        result = begin_external(args.project_root, args.state_dir, args.task_id)
    elif args.action == 'refresh-provenance':
        if not args.task_id or not args.receipt:
            parser.error('refresh-provenance requires --task-id and --receipt')
        result = refresh_provenance(args.project_root, args.state_dir, args.task_id, args.receipt)
    elif args.action == 'complete-external':
        if not args.task_id or not args.receipt:
            parser.error('complete-external requires --task-id and --receipt')
        result = complete_external(args.project_root, args.state_dir, args.task_id, args.receipt)
    elif args.action == "run":
        if not args.task_id:
            parser.error("run requires --task-id")
        result = run_task(args.project_root, args.state_dir, args.task_id)
    elif args.action == "run-all":
        result = run_all(args.project_root, args.state_dir)
    elif args.action == "recover":
        result = recover(args.project_root, args.state_dir)
    else:
        result = status(args.project_root, args.state_dir)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") not in {"failed"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
