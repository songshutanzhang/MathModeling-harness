import os
from pathlib import Path
import subprocess
import sys
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import contest_release
import run_orchestrator as runner
from workflow_state import draft_external, complete_external
from runtime_support import atomic_json, read_json
from test_workflow_recovery import setup, revise


def test_draft_does_not_complete_or_approve_and_detects_missing_outputs(tmp_path):
    task = {'task_id': 'approve', 'execution': 'external', 'kind': 'approval',
            'dependencies': ['solve'], 'outputs': ['approval.txt']}
    plan, state = setup(tmp_path, [task])
    runner.run_task(tmp_path, state, 'solve')
    head = runner.read_events(state)[-1]['event_hash']
    draft_external(tmp_path, state, 'approve', Path('draft.json'))
    draft = read_json(tmp_path / 'draft.json')
    assert draft['status'] == 'draft' and draft['authorization'] is None
    assert draft['missing_outputs'] == ['approval.txt'] and draft['tokens'] is None
    assert runner.read_events(state)[-1]['event_hash'] == head
    with pytest.raises(ValueError, match='run/status'):
        complete_external(tmp_path, state, 'approve', tmp_path / 'draft.json')
    (tmp_path / 'approval.txt').write_text('exists but not approved')
    draft_external(tmp_path, state, 'approve', Path('draft-v2.json'))
    assert read_json(tmp_path / 'draft-v2.json')['outputs'][0]['sha256']
    assert runner.read_events(state)[-1]['event_hash'] == head


def test_log_capture_is_byte_exact_and_keeps_exit_status(tmp_path):
    command = [sys.executable, '-c', "import os;os.write(1,b'out\\x00\\xff');os.write(2,b'err\\r\\n');raise SystemExit(7)"]
    direct = subprocess.run(command, capture_output=True)
    result, warning = runner._run_logged(command, project_root=tmp_path, environment=os.environ.copy(), timeout=5, log_dir=tmp_path/'logs')
    assert result.returncode == direct.returncode == 7 and warning is None
    assert (tmp_path/'logs/stdout.log').read_bytes() == direct.stdout
    assert (tmp_path/'logs/stderr.log').read_bytes() == direct.stderr


def test_logging_unavailable_executes_once_and_retains_success(tmp_path):
    blocker = tmp_path/'blocked'; blocker.write_text('not a directory')
    command = [sys.executable, '-c', "from pathlib import Path;p=Path('calls');p.write_text(p.read_text()+'x' if p.exists() else 'x')"]
    result, warning = runner._run_logged(command, project_root=tmp_path, environment=os.environ.copy(), timeout=5, log_dir=blocker/'logs')
    assert result.returncode == 0 and warning
    assert (tmp_path/'calls').read_text() == 'x'


def test_timeout_retains_partial_log(tmp_path):
    with pytest.raises(subprocess.TimeoutExpired):
        runner._run_logged([sys.executable,'-c',"import os,time;os.write(2,b'before timeout');time.sleep(5)"],
            project_root=tmp_path, environment=os.environ.copy(), timeout=.5, log_dir=tmp_path/'logs')
    assert (tmp_path/'logs/stderr.log').read_bytes() == b'before timeout'


def test_numeric_result_unchanged_with_logging(tmp_path):
    plan, state = setup(tmp_path)
    result = runner.run_task(tmp_path,state,'solve')
    assert result['status'] == 'completed' and (tmp_path/'result.txt').read_text() == 'original'
    assert (state/'logs/solve/attempt-0001/stdout.log').exists()
    assert runner.run_task(tmp_path,state,'solve')['status'] == 'reused'


def test_seal_rejects_drift_and_overwrite_and_launcher_normalizes_cwd(tmp_path, monkeypatch):
    source = tmp_path/'source'; (source/'1start-mathmodel').mkdir(parents=True)
    (source/'1start-mathmodel/SKILL.md').write_text('fixture')
    scripts=source/'_references/harness/scripts';scripts.mkdir(parents=True)
    (scripts/'run_orchestrator.py').write_text("import sys,json;print(json.dumps(sys.argv[1:]))")
    monkeypatch.setattr(contest_release, 'DEFAULT_ENTRIES', ['1start-mathmodel/SKILL.md'])
    release=tmp_path/'release'
    contest_release.seal(source,release,Path(sys.executable),[])
    with pytest.raises(ValueError,match='already exists'):
        contest_release.seal(source,release,Path(sys.executable),[])
    calls=[]
    original=contest_release.subprocess.run
    def capture(argv, **kw):
        if str(argv[1]).endswith('run_orchestrator.py'):
            calls.append(argv)
            return subprocess.CompletedProcess(argv,0)
        return original(argv,**kw)
    monkeypatch.setattr(contest_release.subprocess,'run',capture)
    case=tmp_path/'case';case.mkdir()
    monkeypatch.chdir(tmp_path)
    assert contest_release.launch(release,['status','--project-root','case']) == 0
    monkeypatch.chdir(case)
    assert contest_release.launch(release,['status','--project-root','.']) == 0
    assert calls[0] == calls[1]
    (release/'1start-mathmodel/SKILL.md').write_text('drift')
    with pytest.raises(ValueError,match='release drift'):
        contest_release.verify(release)
