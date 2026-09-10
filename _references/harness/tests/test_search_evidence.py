from __future__ import annotations

import copy
import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from runtime_support import atomic_json, record
from search_evidence import boundary_signal, validate_opportunity, validate_definition, g5_readiness
from definition_probe import overlap, run as definitions
import candidate_registry as registry


def test_definition_counterexamples_and_full_diagnostic(tmp_path):
    assert overlap((0, 10), (8.5, 18.5), 'current') == pytest.approx(.15)
    assert overlap((0, 10), (10, 17), 'narrower') == 0
    assert overlap((0, 10), (3, 5), 'narrower') == 1
    assert overlap((0, 10), (8, 14), 'current') != overlap((8, 14), (0, 10), 'current')
    assert overlap((0, 10), (8, 14), 'mean_width') == overlap((8, 14), (0, 10), 'mean_width')
    assert overlap((-4, 6), (4, 14), 'current', (0, 10)) != overlap((-4, 6), (4, 14), 'current')
    report = definitions(tmp_path)
    assert validate_definition(tmp_path, report)['status'] == 'verified'
    assert any(r['feasibility_changed'] for r in report['cases'])
    report['cases'].pop()
    with pytest.raises(ValueError, match='flat/swap'):
        validate_definition(tmp_path, report)


def test_boundary_requires_one_real_probe_or_measured_budget_stop(tmp_path):
    history = [{'limit': k, 'selected_value': k, 'objective': 20 - k} for k in (2, 3, 4)]
    signal = boundary_signal(history)
    assert signal['probe_required']
    atomic_json(tmp_path / 'history.json', history)
    evidence = {'run_id': 'test-run', 'history': record(tmp_path, 'history.json'), 'decision': {'action': 'disclosed'}}
    with pytest.raises(ValueError, match='disclosure alone'):
        validate_opportunity(tmp_path, evidence)
    atomic_json(tmp_path / 'execution.json', {'observed_seconds': .5})
    atomic_json(tmp_path / 'pilot.json', {'observed_seconds': .5, 'measurement_receipt': record(tmp_path, 'execution.json')})
    evidence['decision'] = {'action': 'measured_stop', 'pilot': record(tmp_path, 'pilot.json'), 'remaining_authorized_seconds': 10}
    with pytest.raises(ValueError, match='still fits'):
        validate_opportunity(tmp_path, evidence)
    evidence['decision']['remaining_authorized_seconds'] = .1
    assert validate_opportunity(tmp_path, evidence)['closed']
    atomic_json(tmp_path / 'candidate.json', {'objective': 15})
    (tmp_path / 'user.txt').write_text('Synthetic fixture: authorize one extension up to 5 within 2 seconds.')
    atomic_json(tmp_path / 'authorization.json', {'run_id': 'test-run', 'scopes': ['search_extension'], 'decision': 'accepted',
        'original': record(tmp_path, 'user.txt'), 'artifacts': [record(tmp_path, 'history.json')],
        'maximum_limit': 5, 'maximum_probe_seconds': 2})
    atomic_json(tmp_path / 'probe.json', {'limit': 5, 'history_sha256': signal['history_sha256'],
        'observed_seconds': .6, 'candidate_evidence': [record(tmp_path, 'candidate.json')],
        'authorization': record(tmp_path, 'authorization.json')})
    evidence['decision'] = {'action': 'probe_completed', 'probe': record(tmp_path, 'probe.json')}
    assert validate_opportunity(tmp_path, evidence)['closed']


def test_g5_hard_error_and_remaining_opportunity_are_separate(tmp_path):
    atomic_json(tmp_path / 'reliability.json', {'status': 'pass', 'unresolved_hard_errors': 0})
    review = {'reliability': record(tmp_path, 'reliability.json'), 'opportunity_assessed': False}
    with pytest.raises(ValueError, match='separate remaining-opportunity'):
        g5_readiness(tmp_path, review)
    review['opportunity_assessed'] = True
    assert g5_readiness(tmp_path, review)['ready_for_writing']
    atomic_json(tmp_path / 'reliability.json', {'status': 'pass', 'unresolved_hard_errors': 1})
    review['reliability'] = record(tmp_path, 'reliability.json')
    with pytest.raises(ValueError, match='reliability is not clear'):
        g5_readiness(tmp_path, review)


def candidate(root, name, role, value, evaluations=8, seed=7):
    (root / 'evaluator.py').write_text('frozen evaluator')
    raw = {'objective': {'name': 'length', 'direction': 'minimize', 'value': value},
           'feasible': True, 'raw_metrics': {'length': value, 'missed': 0},
           'definition': {'id': 'coverage-v1', 'denominator': 'target_points', 'aggregation': 'union'}, 'seeds': [seed]}
    atomic_json(root / f'{name}-raw.json', raw)
    cost = {'evaluations': evaluations, 'observed_seconds': .5}
    atomic_json(root / f'{name}-cost.json', cost)
    result = {'schema_version': '1.1', 'candidate_id': name, 'problem_level': 'level-1', 'family': name,
              'role': role, **raw, 'evaluator': {'id': 'evaluator-v1', **record(root, 'evaluator.py')},
              'budget': {'evaluations': 8}, 'actual_budget': {**cost, 'receipt': record(root, f'{name}-cost.json')},
              'precision': {'grid': .1}, 'sample_group': 'common', 'artifact': record(root, f'{name}-raw.json')}
    atomic_json(root / f'{name}.json', result)
    registry.register(root / 'registry', root, root / f'{name}.json')
    return result


def test_real_budget_and_seed_differences_cannot_be_called_strict_ablation(tmp_path):
    candidate(tmp_path, 'baseline', 'strong_baseline', 10)
    candidate(tmp_path, 'ablation', 'ablation', 11)
    candidate(tmp_path, 'more-budget', 'candidate', 8, evaluations=20)
    candidate(tmp_path, 'other-seed', 'candidate', 7, seed=19)
    result = registry.promote(tmp_path / 'registry', tmp_path, problem_level='level-1')
    assert result['selected_candidate_id'] == 'baseline'
    assert {r['candidate_id'] for r in result['excluded']} == {'more-budget', 'other-seed'}
    assert result['strict_ablation']


def test_registry_rejects_metric_and_evaluator_drift(tmp_path):
    item = candidate(tmp_path, 'baseline', 'strong_baseline', 10)
    altered = copy.deepcopy(item); altered['objective']['value'] = 3
    with pytest.raises(ValueError, match='differs from raw'):
        registry.validate_candidate(altered, tmp_path)
    (tmp_path / 'evaluator.py').write_text('different evaluator')
    with pytest.raises(ValueError, match='hash mismatch'):
        registry.validate_candidate(item, tmp_path)


def test_calibration_never_invents_whole_grid_probability():
    from terrain_route_demo import calibrated_margin
    assert calibrated_margin([.1] * 19, .1)['margin'] == .1
    assert calibrated_margin([.1] * 19, .0001)['margin'] is None
    assert 'not simultaneous' in calibrated_margin([.1] * 19, .1)['guarantee']
