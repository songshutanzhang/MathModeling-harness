from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import run_orchestrator as runner
from runtime_support import atomic_json, record
from workflow_state import complete_external, authorization, cost_ledger, state_path


def setup(root, extra=()):
    (root / 'inputs').mkdir()
    (root / 'inputs/problem.txt').write_text('original')
    (root / 'source.py').write_text(
        "import os,pathlib\n"
        "r=pathlib.Path(os.environ['HARNESS_PROJECT_ROOT'])\n"
        "o=pathlib.Path(os.environ['HARNESS_OUTPUT_DIR'])\n"
        "(o/'result.txt').write_text((r/'inputs/problem.txt').read_text())\n")
    task = {'task_id': 'solve', 'stage': 'coding', 'command': [sys.executable, 'source.py'],
            'inputs': ['inputs/problem.txt'], 'sources': ['source.py'], 'outputs': ['result.txt'],
            'max_attempts': 5}
    plan = {'schema_version': '1.0', 'run_id': 'demo-run', 'experiment_id': 'development',
            'problem_identity': 'synthetic', 'objective_identity': 'constant',
            'tasks': [task, *extra]}
    atomic_json(root / 'plan.json', plan)
    atomic_json(root / 'preflight.json', {'status': 'executable'})
    runner.initialize(root, root / '.state', root / 'plan.json', root / 'preflight.json')
    return plan, root / '.state'


def revise(root, state, plan):
    atomic_json(root / 'plan.json', plan)
    runner.initialize(root, state, root / 'plan.json', root / 'preflight.json')


def test_actual_undeclared_problem_read_fails_without_publishing(tmp_path):
    plan, state = setup(tmp_path)
    plan['tasks'][0]['inputs'] = []
    revise(tmp_path, state, plan)
    assert runner.run_task(tmp_path, state, 'solve')['status'] == 'failed'
    assert not (tmp_path / 'result.txt').exists()
    assert not any(e['event_type'] == 'task_completed' for e in runner.read_events(state))


def test_upstream_drift_invalidates_descendant_before_upstream_rerun(tmp_path):
    extra = {'task_id': 'write', 'stage': 'writing', 'execution': 'external',
             'dependencies': ['solve'], 'outputs': ['paper.md']}
    plan, state = setup(tmp_path, [extra])
    runner.run_task(tmp_path, state, 'solve')
    old = runner.task_identity(tmp_path, state, plan, extra)[0]
    (tmp_path / 'source.py').write_text((tmp_path / 'source.py').read_text() + '\n# new source')
    with pytest.raises(ValueError, match='dependency identity is stale'):
        runner.task_identity(tmp_path, state, plan, extra)
    assert runner.status(tmp_path, state)['next_tasks'] == ['solve']


def test_provenance_change_requests_refresh_without_recomputing(tmp_path):
    plan, state = setup(tmp_path)
    (tmp_path / 'wording.md').write_text('draft')
    plan['tasks'][0]['provenance_inputs'] = ['wording.md']
    revise(tmp_path, state, plan)
    runner.run_task(tmp_path, state, 'solve')
    (tmp_path / 'wording.md').write_text('rephrased')
    assert runner.run_task(tmp_path, state, 'solve')['status'] == 'reused'
    assert runner.status(tmp_path, state)['tasks']['solve']['provenance_state'] == 'refresh_required'


def receipt(root, state, plan, task_id):
    task = runner._task(plan, task_id)
    for raw in task['outputs']:
        (root / raw).write_text('evidence')
    return {'run_id': plan['run_id'], 'task_id': task_id, 'status': 'completed',
            'task_identity': runner.task_identity(root, state, plan, task)[0],
            'outputs': [record(root, p) for p in task['outputs']],
            'wall_clock_seconds': None, 'tokens': None}


def test_whole_workflow_resume_approval_exception_and_stale_hash(tmp_path):
    write = {'task_id': 'write', 'stage': 'writing', 'execution': 'external',
             'dependencies': ['solve'], 'outputs': ['paper.md'], 'cost_category': 'writing'}
    approve = {'task_id': 'approve', 'stage': 'approval', 'kind': 'approval', 'execution': 'external',
               'dependencies': ['write'], 'outputs': ['approved.txt'], 'cost_category': 'waiting'}
    plan, state = setup(tmp_path, [write, approve])
    assert runner.run_all(tmp_path, state)['status'] == 'awaiting_receipt'
    assert runner.status(tmp_path, state)['current_stage'] == 'writing'
    writing_receipt = receipt(tmp_path, state, plan, 'write')
    atomic_json(tmp_path / 'writing.json', writing_receipt)
    complete_external(tmp_path, state, 'write', tmp_path / 'writing.json')
    assert runner.status(tmp_path, state)['current_stage'] == 'approval'
    approval_receipt = receipt(tmp_path, state, plan, 'approve')
    (tmp_path / 'user-message.txt').write_text('Accept capability exception for this run and these artifacts')
    approval_receipt['authorization'] = {
        'run_id': plan['run_id'], 'scopes': ['approve'], 'decision': 'accepted',
        'original': record(tmp_path, 'user-message.txt'), 'artifacts': [record(tmp_path, 'paper.md')],
        'exception': True, 'uncertified_fields': ['effective_effort'],
        'alternative_evidence': [record(tmp_path, 'result.txt')]}
    atomic_json(tmp_path / 'approval.json', approval_receipt)
    complete_external(tmp_path, state, 'approve', tmp_path / 'approval.json')
    runner.recover(tmp_path, state)
    status = runner.status(tmp_path, state)
    assert status['next_tasks'] == []
    assert status['tasks']['approve']['dimensions']['qualification'] == 'not_certified'
    assert status['cost_ledger']['categories']['waiting']['missing_observations'] == 1
    assert not status['cost_ledger']['complete_accounting']
    assert complete_external(tmp_path, state, 'approve', tmp_path / 'approval.json')['status'] == 'reused'
    (tmp_path / 'user-message.txt').write_text('changed')
    assert runner.status(tmp_path, state)['tasks']['approve']['state'] == 'stale'


def test_exception_cannot_waive_missing_dependency(tmp_path):
    from dependency_preflight import accept_route_exception
    (tmp_path / 'original.txt').write_text('accepted')
    auth = {'run_id': 'run-1', 'scopes': ['runtime_capability'], 'decision': 'accepted',
            'original': record(tmp_path, 'original.txt'), 'artifacts': [record(tmp_path, 'original.txt')],
            'exception': True, 'uncertified_fields': ['ultra'],
            'alternative_evidence': [record(tmp_path, 'original.txt')],
            'accepted_failures': ['route G5: effort unavailable: ultra']}
    atomic_json(tmp_path / 'auth.json', auth)
    result = accept_route_exception({'status': 'blocked', 'failures': [
        'route G5: effort unavailable: ultra', 'active dependency missing: solver.py']},
        tmp_path, 'run-1', tmp_path / 'auth.json')
    assert result['status'] == 'blocked' and result['qualification'] == 'not_certified'
    with pytest.raises(ValueError, match='run/scope'):
        authorization(tmp_path, auth, 'other-run', 'runtime_capability')


def test_telemetry_failure_rolls_back_all_outputs_and_never_records_success(tmp_path, monkeypatch):
    plan, state = setup(tmp_path)
    (tmp_path / 'result.txt').write_text('frozen old result')
    class BrokenTelemetry:
        def record(self, *args):
            raise ValueError('simulated telemetry enum error')
    monkeypatch.setattr(runner, '_load_telemetry', lambda: BrokenTelemetry())
    assert runner.run_task(tmp_path, state, 'solve')['status'] == 'failed'
    assert (tmp_path / 'result.txt').read_text() == 'frozen old result'
    events = runner.read_events(state)
    assert not any(e['event_type'] == 'task_completed' for e in events)
    assert any(e['event_type'] == 'telemetry_failed' for e in events)


def test_spawn_error_is_a_recoverable_failed_attempt(tmp_path):
    plan, state = setup(tmp_path)
    plan['tasks'][0]['command'] = ['surely-no-such-executable-20260909']
    revise(tmp_path, state, plan)
    result = runner.run_task(tmp_path, state, 'solve')
    assert result['status'] == 'failed' and 'command_start_failed' in result['failure']
    assert not (state / 'running/solve.json').exists()


def test_state_paths_are_project_relative_from_either_cwd(tmp_path, monkeypatch):
    case = tmp_path / 'case'; case.mkdir()
    monkeypatch.chdir(tmp_path)
    assert state_path(case, Path('.state')) == case / '.state'
    with pytest.raises(ValueError, match='duplicated project prefix'):
        state_path(case, Path('case/.state'))
    monkeypatch.chdir(case)
    assert state_path(case, Path('.state')) == case / '.state'


def test_cost_accounts_waiting_separately_and_keeps_missing():
    events = [{'event_type': 'task_completed', 'payload': {'cost_category': k, 'wall_clock_seconds': v}}
              for k, v in [('numeric', 2), ('llm', None), ('waiting', 200), ('writing', 5)]]
    ledger = cost_ledger(events)
    assert ledger['active_seconds'] == 7
    assert ledger['categories']['llm']['missing_observations'] == 1
    assert ledger['tokens']['missing_observations'] == 4
