#!/usr/bin/env python3
"""Immutable per-call telemetry; retries use new IDs, replay of an ID is idempotent."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = json.loads((ROOT / 'schemas/run_telemetry.schema.json').read_text(encoding='utf-8'))
METRICS = ('input_tokens', 'output_tokens', 'cached_tokens', 'wall_clock_seconds', 'tool_calls', 'context_peak')


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest().upper()


def validate_event(event: dict) -> None:
    Draft202012Validator(SCHEMA).validate(event)
    if not datetime.fromisoformat(event['captured_at']).tzinfo:
        raise ValueError('telemetry timestamp requires timezone')
    for key in METRICS:
        value = event['metrics'][key]
        if (value['value'] is None) != (value['evidence'] == 'missing'):
            raise ValueError(f'inconsistent missing metric: {key}')


def record(directory: Path, event: dict) -> bool:
    validate_event(event)
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / (digest(event['call_id']) + '.json')
    payload = json.dumps(event, sort_keys=True, ensure_ascii=False, indent=2, allow_nan=False) + '\n'
    # Hard-link a complete temporary file: concurrent readers never see a partial record.
    import tempfile
    with tempfile.NamedTemporaryFile(dir=directory, delete=False, suffix='.tmp') as f:
        temporary = Path(f.name)
        f.write(payload.encode('utf-8'))
        f.flush()
        os.fsync(f.fileno())
    try:
        try:
            os.link(temporary, target)
            return True
        except FileExistsError:
            if json.loads(target.read_text(encoding='utf-8')) != event:
                raise ValueError('conflicting telemetry replay for call_id')
            return False
    finally:
        temporary.unlink(missing_ok=True)


def events(directory: Path) -> list[dict]:
    result = []
    ids = set()
    for path in sorted(directory.glob('*.json')):
        item = json.loads(path.read_text(encoding='utf-8'))
        validate_event(item)
        if item['call_id'] in ids or path.stem != digest(item['call_id']):
            raise ValueError('duplicate or renamed telemetry event')
        ids.add(item['call_id'])
        result.append(item)
    if len({e['run_id'] for e in result}) > 1:
        raise ValueError('telemetry directory mixes different runs')
    return sorted(result, key=lambda e: (e['execution_order'], e['call_id']))


def summarize(directory: Path) -> dict:
    records = events(directory)
    by_stage = {}
    for stage in sorted({r['stage'] for r in records}):
        selected = [r for r in records if r['stage'] == stage]
        metrics = {}
        for key in METRICS:
            values = [r['metrics'][key]['value'] for r in selected]
            known = [v for v in values if v is not None]
            aggregate = max(known, default=0) if key == 'context_peak' else sum(known)
            metrics[key] = {'value': aggregate if len(known) == len(values) else None,
                            'observed_subtotal': aggregate, 'missing_calls': len(values)-len(known),
                            'evidence': 'observed' if len(known) == len(values) else 'missing'}
        by_stage[stage] = metrics
    return {'schema_version': '1.0', 'run_id': records[0]['run_id'] if records else None,
            'calls': len(records), 'retry_count': sum(r['attempt'] > 1 for r in records),
            'by_stage': by_stage, 'execution_topology': [{k: r[k] for k in (
                'call_id', 'execution_order', 'execution_instance_id', 'session_or_context_id',
                'model_id', 'reasoning_effort', 'reviewer_visible_inputs', 'reviewer_hidden_inputs',
                'prior_output_exposure', 'prompt_hash', 'input_artifact_hashes')} for r in records],
            'cost_claim_ready': bool(records) and all(r['metrics'][k]['value'] is not None
                for r in records for k in ('input_tokens','output_tokens','wall_clock_seconds','tool_calls'))
                and all(r[k] is not None for r in records for k in
                        ('model_id','reasoning_effort','prompt_hash','config_hash','profile_hash','session_or_context_id')),
            'wall_clock_semantics': 'sum of measured call durations by stage; overlapping calls are not end-to-end latency'}


def render_vault(directory: Path) -> str:
    rows = ['# Run 阶段派生摘要', '', '事实源：不可覆盖的 telemetry 事件；本视图可重新生成。', '']
    for e in events(directory):
        rows.append(f"- [{e['stage']}] {e['kind']} · {e['call_id']} · {e['summary']} · failure={e['failure_class']} · attempt={e['attempt']}")
    return '\n'.join(rows) + '\n'


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument('action', choices=['record','summary','vault','run'])
    p.add_argument('--directory', required=True, type=Path)
    p.add_argument('--event', type=Path, help='Complete event or run template; unknown runtime fields use null')
    p.add_argument('--output', type=Path)
    a, command = p.parse_known_args()
    if a.action != 'run' and command:
        p.error('unexpected command arguments')
    if a.action in {'record','run'}:
        if not a.event:
            p.error('--event is required')
        event = json.loads(a.event.read_text(encoding='utf-8'))
        Draft202012Validator(SCHEMA).validate(event)
        if a.action == 'record':
            record(a.directory, event)
            return 0
        command = command[1:] if command[:1] == ['--'] else command
        if not command:
            p.error('run requires a command after --')
        if (a.directory / (digest(event['call_id']) + '.json')).exists():
            raise ValueError('call already executed; use a new call_id and attempt for retries')
        reservation = a.directory / (digest(event['call_id']) + '.running')
        reserved = False
        try:
            a.directory.mkdir(parents=True, exist_ok=True)
            with reservation.open('x', encoding='utf-8') as f:
                f.write(event['call_id'])
            reserved = True
        except FileExistsError:
            raise ValueError('call is running or interrupted; use a new retry call_id')
        except OSError as exc:
            print(f'Telemetry reservation unavailable; cost claims blocked: {exc}')
        start = time.perf_counter()
        code = 1
        try:
            code = subprocess.run(command, check=False).returncode
        finally:
            event['captured_at'] = datetime.now(timezone.utc).isoformat()
            event['metrics']['wall_clock_seconds'] = {'value': time.perf_counter()-start, 'evidence':'observed'}
            event['metrics']['tool_calls'] = {'value':1, 'evidence':'observed'}
            event['failure_class'] = None if code == 0 else 'command_failed'
            try:
                record(a.directory, event)
            except Exception as exc:
                print(f'Telemetry unavailable; cost claims blocked: {exc}')
            if reserved:
                reservation.unlink(missing_ok=True)
        return code
    payload = render_vault(a.directory) if a.action == 'vault' else json.dumps(summarize(a.directory), ensure_ascii=False, indent=2)+'\n'
    if a.output:
        a.output.parent.mkdir(parents=True, exist_ok=True)
        a.output.write_text(payload, encoding='utf-8')
    else:
        print(payload, end='')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
