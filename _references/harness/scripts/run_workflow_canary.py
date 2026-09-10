"""Persistent end-to-end synthetic canary for the B-postmortem workflow changes."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import sys

import candidate_registry
import run_orchestrator as runner
from runtime_support import atomic_json, record, read_json
from workflow_state import begin_external, complete_external
from performance_pilot import extract


SOLVER = '''import os, time
from pathlib import Path
import numpy as np
from runtime_support import atomic_json
from evaluator import evaluate
out = Path(os.environ['HARNESS_OUTPUT_DIR'])
for name, shift in [('baseline', 0.), ('ablation', 0.), ('candidate', .06428571428571428)]:
    began = time.perf_counter()
    values = np.array([evaluate(x + shift) for seed in [7, 19] for x in np.linspace(0., 1., 8)])
    seconds = time.perf_counter() - began
    atomic_json(out / f'results/{name}-raw.json', {
        'objective': {'name': 'quadratic_loss', 'direction': 'minimize', 'value': values.min()},
        'feasible': True, 'raw_metrics': {'evaluations': np.int64(len(values)), 'values': values},
        'definition': {'id': 'squared_error', 'denominator': 'one', 'aggregation': 'minimum'}, 'seeds': [7, 19]})
    atomic_json(out / f'results/{name}-cost.json', {'evaluations': np.int64(len(values)), 'observed_seconds': seconds})
'''


def finish(root, state, plan, task_id, auth=None):
    start = begin_external(root, state, task_id)
    task = runner._task(plan, task_id)
    receipt = {**start, 'status': 'completed', 'outputs': [record(root, p) for p in task['outputs']]}
    if auth:
        receipt['authorization'] = auth
    path = root / 'receipts' / f'{task_id}.json'
    atomic_json(path, receipt, immutable=True)
    return complete_external(root, state, task_id, path)


def run(output: Path):
    if output.exists() and any(output.iterdir()):
        raise ValueError('use a new empty canary directory; prior receipts are immutable')
    root = output.resolve(); root.mkdir(parents=True, exist_ok=True)
    source = root / 'source'; source.mkdir()
    (source / 'solver.py').write_text(SOLVER, encoding='utf-8')
    (source / 'evaluator.py').write_text('def evaluate(x):\n    return (x - .35) ** 2\n', encoding='utf-8')
    shutil.copy2(Path(__file__).with_name('runtime_support.py'), source / 'runtime_support.py')
    plan = {'schema_version': '1.0', 'run_id': 'workflow-canary', 'experiment_id': 'synthetic-development',
        'problem_identity': 'quadratic-example', 'objective_identity': 'squared-distance-v1',
        'dataset_role': 'development', 'budget_seconds': 30., 'final_review_reserve_seconds': 3.,
        'tasks': [
            {'task_id': 'solve', 'stage': 'coding', 'command': [sys.executable, 'source/solver.py'],
             'sources': ['source'], 'inputs': [], 'outputs': [f'results/{name}-{kind}.json'
                 for name in ['baseline', 'ablation', 'candidate'] for kind in ['raw', 'cost']], 'packages': ['numpy'],
             'cost_category': 'numeric', 'max_attempts': 2},
            {'task_id': 'select', 'stage': 'coding', 'execution': 'external', 'dependencies': ['solve'],
             'outputs': ['selection/PROMOTION.json'], 'cost_category': 'tool'},
            {'task_id': 'review', 'stage': 'review', 'execution': 'external', 'dependencies': ['select'],
             'outputs': ['review/reliability.json'], 'cost_category': 'review'},
            {'task_id': 'write', 'stage': 'writing', 'execution': 'external', 'dependencies': ['review'],
             'outputs': ['paper.md'], 'cost_category': 'writing'},
            {'task_id': 'approve', 'stage': 'approval', 'kind': 'approval', 'execution': 'external',
             'dependencies': ['write'], 'outputs': ['approval/accepted.json'], 'cost_category': 'waiting'}]}
    atomic_json(root / 'PLAN.v1.json', plan, immutable=True)
    atomic_json(root / 'PREFLIGHT.json', {'status': 'executable', 'scope': 'synthetic runtime fixture'}, immutable=True)
    state = root / '.runtime'
    runner.initialize(root, state, root / 'PLAN.v1.json', root / 'PREFLIGHT.json')
    result = runner.run_all(root, state)
    assert result['status'] == 'awaiting_receipt'
    pilot = extract(root, state, 'solve', root / 'PILOT.json')
    registry = root / 'registry'
    for name, role in [('baseline', 'strong_baseline'), ('ablation', 'ablation'), ('candidate', 'candidate')]:
        raw = read_json(root / f'results/{name}-raw.json')
        cost = read_json(root / f'results/{name}-cost.json')
        descriptor = {'schema_version': '1.1', 'candidate_id': name, 'problem_level': 'level-1',
            'family': name, 'role': role, **raw, 'evaluator': {'id': 'quadratic-v1', **record(root, 'source/evaluator.py')},
            'budget': {'evaluations': 16}, 'actual_budget': {**cost, 'receipt': record(root, f'results/{name}-cost.json')},
            'precision': {'arithmetic': 'float64'}, 'sample_group': 'fixed-common-grid',
            'artifact': record(root, f'results/{name}-raw.json')}
        path = root / f'{name}.json'; atomic_json(path, descriptor, immutable=True)
        candidate_registry.register(registry, root, path)
    promotion = candidate_registry.promote(registry, root, problem_level='level-1')
    atomic_json(root / 'selection/PROMOTION.json', promotion, immutable=True)
    finish(root, state, plan, 'select')
    atomic_json(root / 'review/reliability.json', {'status': 'pass', 'unresolved_hard_errors': 0,
        'scope': 'synthetic workflow fixture, not an independent LLM review'}, immutable=True)
    finish(root, state, plan, 'review')
    atomic_json(root / 'checks/promotion.json', {'registry': 'registry', 'problem_level': 'level-1',
        'promotion': record(root, 'selection/PROMOTION.json')}, immutable=True)
    atomic_json(root / 'checks/g5.json', {'reliability': record(root, 'review/reliability.json'),
        'opportunity_assessed': True, 'opportunities': []}, immutable=True)
    plan['tasks'][3]['checks'] = [
        {'kind': 'candidate_promotion', 'evidence': record(root, 'checks/promotion.json')},
        {'kind': 'g5', 'evidence': record(root, 'checks/g5.json')}]
    atomic_json(root / 'PLAN.v2.json', plan, immutable=True)
    runner.initialize(root, state, root / 'PLAN.v2.json', root / 'PREFLIGHT.json')
    writing_start = begin_external(root, state, 'write')
    before = runner.status(root, state)
    assert before['current_stage'] == 'writing' and before['tasks']['write']['state'] == 'awaiting_receipt'
    runner.recover(root, state)
    assert begin_external(root, state, 'write') == writing_start
    (root / 'paper.md').write_text('Synthetic workflow canary. Selected: ' + promotion['selected_candidate_id'], encoding='utf-8')
    finish(root, state, plan, 'write')
    (root / 'synthetic-user-message.txt').write_text('FIXTURE ONLY: accept the documented capability exception for workflow-canary.', encoding='utf-8')
    auth = {'run_id': plan['run_id'], 'scopes': ['approve'], 'decision': 'accepted',
            'original': record(root, 'synthetic-user-message.txt'), 'artifacts': [record(root, 'paper.md')],
            'exception': True, 'uncertified_fields': ['effective_model_effort'],
            'alternative_evidence': [record(root, 'review/reliability.json')]}
    atomic_json(root / 'approval/accepted.json', auth, immutable=True)
    finish(root, state, plan, 'approve', auth)
    runner.recover(root, state)
    final = runner.status(root, state)
    replay = runner.run_all(root, state)
    acceptance = {'numpy_serialization': read_json(root / 'results/baseline-raw.json')['raw_metrics']['evaluations'] == 16,
        'strict_candidate_promotion': promotion['strict_ablation'],
        'writing_resume': before['current_stage'] == 'writing', 'complete_graph': final['current_stage'] == 'complete',
        'approval_reused': all(r['status'] == 'reused' for r in replay['results']),
        'exception_not_certified': final['tasks']['approve']['dimensions']['qualification'] == 'not_certified',
        'missing_cost_preserved': not final['cost_ledger']['complete_accounting'],
        'pilot_measured_before_approval': pilot['observed_seconds'] > 0}
    result = {'schema_version': '1.0', 'dataset_role': 'synthetic_structural_canary',
              'acceptance': acceptance, 'status': final, 'promotion': promotion, 'pilot': pilot,
              'claim_limit': 'External review and approval messages are explicitly synthetic fixtures; this does not certify a real review or blind-test performance.'}
    atomic_json(root / 'CANARY_REPORT.json', result, immutable=True)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, required=True)
    result = run(parser.parse_args().output_dir)
    print(json.dumps(result['acceptance'], indent=2))
    raise SystemExit(0 if all(result['acceptance'].values()) else 1)
