"""Measured search-boundary decisions and definition diagnostics for model freezing."""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from runtime_support import atomic_json, verify_record, record, digest


def boundary_signal(history: list[dict], *, direction='minimize', tolerance=1e-9) -> dict:
    if direction not in {'minimize', 'maximize'} or len(history) < 2:
        raise ValueError('boundary assessment needs an objective direction and at least two levels')
    limits = [row['limit'] for row in history]
    if limits != sorted(set(limits)):
        raise ValueError('search levels must be unique and increasing')
    if any(not math.isfinite(row['objective']) for row in history):
        raise ValueError('objectives must be finite')
    sign = 1 if direction == 'maximize' else -1
    gains = [sign * (b['objective'] - a['objective']) for a, b in zip(history, history[1:])]
    at_boundary = history[-1]['selected_value'] == history[-1]['limit']
    return {'at_boundary': at_boundary, 'recent_gains': gains,
            'probe_required': at_boundary and all(g > tolerance for g in gains[-2:]),
            'history_sha256': digest(history)}


def validate_opportunity(root: Path, evidence: dict) -> dict:
    history = json.loads(verify_record(root, evidence['history']).read_text(encoding='utf-8'))
    signal = boundary_signal(history, direction=evidence.get('direction', 'minimize'))
    if not signal['probe_required']:
        return {**signal, 'disposition': 'no_boundary_signal', 'closed': True}
    decision = evidence.get('decision', {})
    action = decision.get('action')
    if action == 'probe_completed':
        probe = json.loads(verify_record(root, decision['probe']).read_text(encoding='utf-8'))
        if probe.get('history_sha256') != signal['history_sha256'] or probe.get('limit', 0) <= history[-1]['limit']:
            raise ValueError('probe does not extend this frozen search history')
        if type(probe.get('observed_seconds')) not in (int, float) or not math.isfinite(probe['observed_seconds']) or probe['observed_seconds'] < 0:
            raise ValueError('probe requires observed cost')
        from workflow_state import authorization
        auth = json.loads(verify_record(root, probe['authorization']).read_text(encoding='utf-8'))
        authorization(root, auth, evidence['run_id'], 'search_extension')
        if probe['limit'] > auth.get('maximum_limit', 0) or probe['observed_seconds'] > auth.get('maximum_probe_seconds', 0):
            raise ValueError('probe exceeds the accepted structural scope or time budget')
        if not probe.get('candidate_evidence'):
            raise ValueError('probe requires evaluated candidate evidence')
        for item in probe['candidate_evidence']:
            verify_record(root, item)
    elif action == 'measured_stop':
        pilot = json.loads(verify_record(root, decision['pilot']).read_text(encoding='utf-8'))
        observed = pilot.get('observed_seconds')
        if type(observed) not in (int, float) or not math.isfinite(observed) or observed <= 0:
            raise ValueError('stop needs a measured pilot, not an estimated duration')
        if not pilot.get('measurement_receipt'):
            raise ValueError('pilot needs an execution receipt')
        measured = json.loads(verify_record(root, pilot['measurement_receipt']).read_text(encoding='utf-8'))
        if measured.get('observed_seconds', measured.get('payload', {}).get('wall_clock_seconds')) != observed:
            raise ValueError('pilot duration differs from execution receipt')
        remaining = decision.get('remaining_authorized_seconds')
        if type(remaining) not in (int, float) or remaining < 0 or observed <= remaining:
            raise ValueError('low-cost opportunity still fits the authorized budget; run one bounded probe')
    elif action == 'outside_authorization':
        from workflow_state import authorization
        auth = json.loads(verify_record(root, decision['authorization']).read_text(encoding='utf-8'))
        authorization(root, auth, evidence['run_id'], 'search_scope')
        if auth.get('maximum_limit') != history[-1]['limit'] or not decision.get('reason'):
            raise ValueError('out-of-scope decision needs the binding search limit and reason')
    else:
        raise ValueError('boundary opportunity unresolved: disclosure alone is not a disposition')
    return {**signal, 'disposition': action, 'closed': True}


def validate_definition(root: Path, evidence: dict) -> dict:
    required = {'flat', 'swap', 'touch', 'nested', 'clip'}
    rows = evidence.get('cases', [])
    if {r.get('case') for r in rows} != required:
        raise ValueError('definition diagnostic needs flat/swap/touch/nested/clip cases')
    for row in rows:
        if not row.get('definitions') or type(row.get('feasibility_changed')) is not bool or type(row.get('ranking_changed')) is not bool:
            raise ValueError('definition diagnostic must state feasibility and ranking effects')
        if not row.get('evidence'):
            raise ValueError('definition diagnostic needs executable evidence')
        verify_record(root, row['evidence'])
    if not evidence.get('selected_definition') or not evidence.get('selection_reason'):
        raise ValueError('definition must be chosen with a reason before freezing')
    return {'status': 'verified', 'selected_definition': evidence['selected_definition'], 'cases': sorted(required)}


def g5_readiness(root: Path, review: dict) -> dict:
    if review.get('reliability_bundle'):
        from validate_g5_bundle import validate
        from runtime_support import scoped
        checked = validate(scoped(root, review['reliability_bundle']), reliability_only=True)
        reliability = {'status': 'pass' if checked['action'] == 'accept' else 'failed',
                       'unresolved_hard_errors': checked['open_hard_failures']}
    else:
        reliability = json.loads(verify_record(root, review['reliability']).read_text(encoding='utf-8'))
    if reliability.get('status') != 'pass' or reliability.get('unresolved_hard_errors') != 0:
        raise ValueError('G5 reliability is not clear for writing')
    opportunities = [validate_opportunity(root, json.loads(verify_record(root, r).read_text(encoding='utf-8')))
                     for r in review.get('opportunities', [])]
    if review.get('opportunity_assessed') is not True:
        raise ValueError('G5 needs a separate remaining-opportunity assessment')
    return {'mathematical': 'pass', 'opportunity_dispositions': opportunities, 'ready_for_writing': True,
            'reliability_source': 'validated_bundle' if review.get('reliability_bundle') else 'bound_receipt'}


def validate_check(root: Path, check: dict) -> dict:
    evidence = json.loads(verify_record(root, check['evidence']).read_text(encoding='utf-8'))
    if check['kind'] == 'candidate_promotion':
        from candidate_registry import promote
        from runtime_support import scoped
        actual = promote(scoped(root, evidence['registry']), root,
                         problem_level=evidence['problem_level'], incumbent_id=evidence.get('incumbent_id'),
                         minimum_gain=evidence.get('minimum_gain', 0.))
        expected = json.loads(verify_record(root, evidence['promotion']).read_text(encoding='utf-8'))
        if actual != expected or not actual['strict_ablation']:
            raise ValueError('promotion receipt is stale or lacks strict raw/budget/definition evidence')
        return {'status': 'verified', 'selected_candidate_id': actual['selected_candidate_id'],
                'registry_sha256': actual['registry_sha256']}
    functions = {'opportunity': validate_opportunity, 'definition': validate_definition, 'g5': g5_readiness}
    if check['kind'] not in functions:
        raise ValueError('unknown model-freeze check')
    return functions[check['kind']](root, evidence)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('kind', choices=['opportunity', 'definition', 'g5', 'candidate_promotion'])
    parser.add_argument('--project-root', required=True, type=Path)
    parser.add_argument('--evidence', required=True, type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    result = validate_check(args.project_root, {'kind': args.kind, 'evidence': record(args.project_root, args.evidence)})
    if args.output:
        atomic_json(args.output, result)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
