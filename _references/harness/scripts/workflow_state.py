"""Whole-run receipts, scoped authorization and measured cost accounting."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import math

from runtime_support import record, verify_record, read_json, scoped, atomic_json, input_manifest

CATEGORIES = ('numeric', 'llm', 'tool', 'writing', 'review', 'waiting')


def state_path(root: Path, raw: Path) -> Path:
    """Relative state paths are always project relative, never cwd relative."""
    root = root.resolve()
    result = scoped(root, raw)
    if not raw.is_absolute():
        for size in range(1, min(len(raw.parts), len(root.parts)) + 1):
            if tuple(p.casefold() for p in raw.parts[:size]) == tuple(p.casefold() for p in root.parts[-size:]):
                raise ValueError('duplicated project prefix in state path; use a path relative to --project-root')
    return result


def authorization(root: Path, receipt: dict, run_id: str, scope: str) -> dict:
    if receipt.get('run_id') != run_id or scope not in receipt.get('scopes', []):
        raise ValueError('authorization run/scope mismatch')
    if receipt.get('decision') != 'accepted':
        raise ValueError('authorization is not accepted')
    verify_record(root, receipt['original'])
    if not receipt.get('artifacts'):
        raise ValueError('authorization needs the reviewed artifact hashes')
    for item in receipt['artifacts']:
        verify_record(root, item)
    if receipt.get('exception'):
        if not receipt.get('uncertified_fields') or not receipt.get('alternative_evidence'):
            raise ValueError('exception needs uncertified fields and alternative evidence')
        for item in receipt['alternative_evidence']:
            verify_record(root, item)
    return {'authorization': 'accepted',
            'qualification': 'not_certified' if receipt.get('exception') else 'not_assessed',
            'uncertified_fields': receipt.get('uncertified_fields', [])}


def cost_ledger(events: list[dict]) -> dict:
    result = {key: {'observed_seconds': 0.0, 'missing_observations': 0} for key in CATEGORIES}
    token_total, token_missing = 0, 0
    for event in events:
        if event['event_type'] not in {'task_completed', 'task_failed', 'task_interrupted'}:
            continue
        value = event['payload']
        category = value.get('cost_category', 'numeric')
        bucket = result[category]
        seconds = value.get('wall_clock_seconds')
        if seconds is None:
            bucket['missing_observations'] += 1
        else:
            bucket['observed_seconds'] += seconds
        tokens = value.get('tokens')
        if tokens is None:
            token_missing += 1
        else:
            token_total += tokens
    return {'categories': result, 'tokens': {'observed': token_total, 'missing_observations': token_missing},
            'complete_accounting': not token_missing and not any(v['missing_observations'] for v in result.values()),
            'active_seconds': sum(v['observed_seconds'] for k, v in result.items() if k != 'waiting')}


def complete_external(root: Path, state: Path, task_id: str, receipt_path: Path) -> dict:
    import run_orchestrator as runner
    revision, plan = runner._plan(root, state)
    task = runner._task(plan, task_id)
    if task.get('execution', 'command') != 'external':
        raise ValueError('receipt completion is only for external nodes')
    receipt_record = record(root, receipt_path)
    receipt = read_json(verify_record(root, receipt_record))
    identity_hash, identity = runner.task_identity(root, state, plan, task)
    if receipt.get('task_identity') != identity_hash or receipt.get('task_id') != task_id:
        raise ValueError('receipt task identity mismatch')
    if receipt.get('run_id') != plan['run_id'] or receipt.get('status') != 'completed':
        raise ValueError('receipt run/status mismatch')
    outputs = [record(root, raw) for raw in task['outputs']]
    if outputs != receipt.get('outputs'):
        raise ValueError('external output evidence mismatch')
    dimensions = {'mathematical': 'not_assessed', 'delivery': 'not_assessed',
                  'authorization': 'not_assessed', 'qualification': 'not_assessed'}
    if task.get('kind') == 'approval':
        dimensions.update(authorization(root, receipt['authorization'], plan['run_id'], task_id))
    seconds = receipt.get('wall_clock_seconds')
    if seconds is not None and (type(seconds) not in (float, int) or not math.isfinite(seconds) or seconds < 0):
        raise ValueError('observed cost must be nonnegative finite or missing/null')
    tokens = receipt.get('tokens')
    if tokens is not None and (type(tokens) is not int or tokens < 0):
        raise ValueError('tokens must be observed nonnegative integer or missing/null')
    prior = runner._latest_completed(runner.read_events(state), task_id)
    if prior and prior['payload'].get('receipt') == receipt_record:
        (state / 'external' / f'{task_id}.json').unlink(missing_ok=True)
        return {'status': 'reused', 'task_id': task_id}
    event = runner.append_event(state, 'task_completed', {
        'task_id': task_id, 'task_identity': identity_hash, 'identity': identity,
        'outputs': outputs, 'receipt': receipt_record, 'dimensions': dimensions,
        'cost_category': task.get('cost_category', 'tool'), 'wall_clock_seconds': seconds,
        'tokens': tokens, 'revision': revision['revision'],
    })
    (state / 'external' / f'{task_id}.json').unlink(missing_ok=True)
    return {'status': 'completed', 'task_id': task_id, 'event_hash': event['event_hash']}


def begin_external(root: Path, state: Path, task_id: str) -> dict:
    import run_orchestrator as runner
    revision, plan = runner._plan(root, state)
    task = runner._task(plan, task_id)
    if task.get('execution') != 'external':
        raise ValueError('start-external requires an external node')
    identity_hash, identity = runner.task_identity(root, state, plan, task)
    marker = state / 'external' / f'{task_id}.json'
    if marker.exists():
        prior = read_json(marker)
        if prior['task_identity'] != identity_hash:
            raise ValueError('external work identity drifted; preserve the old receipt and start a revised node')
        return prior
    runner._check_budget(plan, task, runner.read_events(state))
    value = {'run_id': plan['run_id'], 'task_id': task_id, 'task_identity': identity_hash,
             'status': 'awaiting_receipt', 'started_at': runner.utc_now(),
             'cost_category': task.get('cost_category', 'tool'), 'wall_clock_seconds': None, 'tokens': None}
    atomic_json(marker, value, immutable=True)
    runner.append_event(state, 'external_started', value)
    return value


def draft_external(root: Path, state: Path, task_id: str, output: Path) -> dict:
    """Read-only observation of work, followed by an immutable draft file, never approval."""
    import run_orchestrator as runner
    _, plan = runner._plan(root, state)
    task = runner._task(plan, task_id)
    if task.get('execution') != 'external':
        raise ValueError('draft receipt requires an external node')
    identity, _ = runner.task_identity(root, state, plan, task)
    outputs, missing = [], []
    for raw in task['outputs']:
        path = scoped(root, raw)
        if path.is_file():
            outputs.append(record(root, path))
        else:
            missing.append(raw)
    draft = {'run_id': plan['run_id'], 'task_id': task_id, 'task_identity': identity,
             'status': 'draft', 'outputs': outputs, 'missing_outputs': missing,
             'cost_category': task.get('cost_category', 'tool'),
             'wall_clock_seconds': None, 'tokens': None}
    if task.get('kind') == 'approval':
        draft['authorization'] = None
    target = scoped(root, output)
    protected = {scoped(root, raw) for raw in task['outputs']}
    if target in protected or target.is_relative_to(state.resolve()):
        raise ValueError('draft output must not overwrite task outputs or runtime state')
    atomic_json(target, draft, immutable=True)
    return {'status': 'draft', 'task_id': task_id, 'receipt': record(root, target), 'missing_outputs': missing}


def refresh_provenance(root: Path, state: Path, task_id: str, receipt_path: Path) -> dict:
    import run_orchestrator as runner
    _, plan = runner._plan(root, state)
    task = runner._task(plan, task_id)
    completed = runner._latest_completed(runner.read_events(state), task_id)
    identity_hash, _ = runner.task_identity(root, state, plan, task)
    if not completed or completed['payload']['task_identity'] != identity_hash:
        raise ValueError('numerical task must be current before provenance refresh')
    receipt = read_json(receipt_path)
    manifest = input_manifest(root, task.get('provenance_inputs', []))
    if receipt.get('task_identity') != identity_hash or receipt.get('provenance_manifest') != manifest:
        raise ValueError('provenance sidecar does not bind current inputs and numerical identity')
    if receipt.get('numerical_outputs') != completed['payload']['outputs']:
        raise ValueError('provenance sidecar numerical outputs mismatch')
    for item in receipt['numerical_outputs']:
        verify_record(root, item)
    return runner.append_event(state, 'provenance_verified', {
        'task_id': task_id, 'task_identity': identity_hash,
        'provenance_manifest': manifest, 'receipt': record(root, receipt_path)})


def verify_external(root: Path, payload: dict) -> bool:
    try:
        if 'receipt' in payload:
            receipt = read_json(verify_record(root, payload['receipt']))
            if 'authorization' in receipt:
                authorization(root, receipt['authorization'], receipt['run_id'], receipt['task_id'])
        return True
    except (ValueError, OSError, KeyError):
        return False
