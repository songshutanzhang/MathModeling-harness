#!/usr/bin/env python3
"""Record explicit, evidence-bound stage signals; never load a heavy module to detect it."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import yaml

POLICY = Path(__file__).resolve().parents[1] / 'harness_profile_policy.yaml'
SIGNALS = {
    'knowledge_gap': 'knowledge_retrieval_required',
    'special_route': 'special_model_required',
    'diagram_requested': 'non_data_figure_required',
    'upside_requested': 'upside_review_required',
    'failure': 'recovery_required', 'timeout': 'recovery_required',
    'budget_exceeded': 'recovery_required',
}


def detect(signal: str, stage: str, evidence: Path) -> dict:
    policy = yaml.safe_load(POLICY.read_text(encoding='utf-8'))
    if signal not in SIGNALS:
        raise ValueError(f'unknown signal: {signal}')
    condition = SIGNALS[signal]
    if stage not in policy['condition_stages'][condition]:
        raise ValueError('signal not applicable to stage')
    return {'signal': signal, 'condition': condition, 'stages': [stage],
            'detector': policy['condition_owners'][condition],
            'captured_at': datetime.now(timezone.utc).isoformat(),
            'evidence': {'path': str(evidence.resolve()),
                         'sha256': hashlib.sha256(evidence.read_bytes()).hexdigest().upper()}}


def validate(path: Path, mode: str) -> dict:
    data = json.loads(path.read_text(encoding='utf-8'))
    policy = yaml.safe_load(POLICY.read_text(encoding='utf-8'))
    if data.get('schema_version') != '1.0' or data.get('mode') != mode:
        raise ValueError('condition events schema/mode mismatch')
    if mode not in policy['allowed_modes'] or not isinstance(data.get('events'), list):
        raise ValueError('invalid condition events')
    scopes = {}
    for event in data['events']:
        condition = event['condition']
        if SIGNALS.get(event['signal']) != condition:
            raise ValueError('unknown or inconsistent condition signal')
        if event['detector'] != policy['condition_owners'][condition]:
            raise ValueError('condition trigger owner mismatch')
        if mode in policy.get('condition_forbidden_modes', {}).get(condition, []):
            raise ValueError('condition forbidden in evaluation')
        if not datetime.fromisoformat(event['captured_at']).tzinfo:
            raise ValueError('condition timestamp must include timezone')
        if not event['stages'] or not set(event['stages']) <= set(policy['condition_stages'][condition]):
            raise ValueError('invalid condition stages')
        evidence = event['evidence']
        if hashlib.sha256(Path(evidence['path']).read_bytes()).hexdigest().upper() != evidence['sha256']:
            raise ValueError('condition evidence drift')
        scopes.setdefault(condition, set()).update(event['stages'])
    return {'condition_scopes': {k: sorted(v) for k, v in sorted(scopes.items())}}


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument('--mode', required=True)
    p.add_argument('--signal', required=True, choices=SIGNALS)
    p.add_argument('--stage', required=True)
    p.add_argument('--evidence', required=True, type=Path)
    p.add_argument('--previous', type=Path, help='Carry frozen earlier stage events into a new file')
    p.add_argument('--output', required=True, type=Path)
    a = p.parse_args()
    events = []
    if a.previous:
        validate(a.previous, a.mode)
        events = json.loads(a.previous.read_text(encoding='utf-8'))['events']
    events.append(detect(a.signal, a.stage, a.evidence))
    data = {'schema_version': '1.0', 'mode': a.mode, 'events': events}
    # Validate before publishing the immutable output.
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        check = Path(td) / 'events.json'
        check.write_text(json.dumps(data), encoding='utf-8')
        validate(check, a.mode)
    a.output.parent.mkdir(parents=True, exist_ok=True)
    with a.output.open('x', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
