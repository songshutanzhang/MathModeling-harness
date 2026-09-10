from __future__ import annotations
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import yaml
import pytest

ROOT = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / (name+'.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding='utf-8')
    return path


def ids(profile, stage=None):
    return {m['id'] for m in (profile['stage_modules'][stage] if stage else profile['active_modules'])}


@pytest.mark.parametrize('mode,tier', [('training_run','tier1'),('training_run','tier2'),
    ('reference_case_ingestion','tier1'),('evaluation_run','tier3'),('live_competition','tier3'),('release_candidate','tier3')])
def test_all_legal_profiles_cover_stages_and_dependencies(mode, tier):
    r = load('resolve_harness_profile')
    p = r.resolve(mode=mode, tier=tier)
    assert set().union(*(ids(p, s) for s in p['stage_modules'])) == ids(p)
    registry = yaml.safe_load((ROOT/'component_registry.yaml').read_text(encoding='utf-8'))
    for component in registry['components']:
        if component['id'] in ids(p):
            assert set(component['dependencies']) <= ids(p), component['id']
    if mode == 'evaluation_run':
        assert not {'knowledge-retrieval','source-learning','capability-selector'} & ids(p)
    if tier == 'tier3':
        assert {'human-gates','contest-compliance'} <= ids(p)
    else:
        assert 'human-gates' not in ids(p)


@pytest.mark.parametrize('mode,tier', [('training_run','tier3'),('reference_case_ingestion','tier2'),
                                      ('evaluation_run','tier2'),('unknown','tier1')])
def test_illegal_profiles_fail(mode, tier):
    with pytest.raises(ValueError):
        load('resolve_harness_profile').resolve(mode=mode,tier=tier)


def test_evaluation_cannot_enable_knowledge_or_rescue():
    r=load('resolve_harness_profile')
    for kwargs in [{'conditions':['knowledge_retrieval_required']},{'experimental':['ceiling-rescue']}]:
        with pytest.raises(ValueError):
            r.resolve(mode='evaluation_run',tier='tier3',**kwargs)


def test_policy_drift_and_uncovered_stage_fail(tmp_path):
    r=load('resolve_harness_profile'); v=load('validate_harness_profile')
    g=write(tmp_path/'g.json',{'mode':'training_run','resolved_tier':'tier1'})
    p=r.resolve_from_governance(g)
    p['policy_sha256']='0'*64
    with pytest.raises(ValueError, match='policy_sha256'):
        v.validate(write(tmp_path/'p.json',p),g)
    policy=r.load_policy()
    for stage in policy['stage_modules']:
        policy['stage_modules'][stage]=[m for m in policy['stage_modules'][stage] if m!='solver-execution']
    with pytest.raises(ValueError, match='stage union'):
        r.resolve(mode='training_run',tier='tier1',policy=policy)


def test_draft_audit_upgrade_and_cross_mode_predecessor(tmp_path):
    r=load('resolve_harness_profile'); v=load('validate_harness_profile')
    g=write(tmp_path/'g1.json',{'mode':'training_run','resolved_tier':'tier1'})
    first=write(tmp_path/'p1.json',r.resolve_from_governance(g))
    g2=write(tmp_path/'g2.json',{'mode':'training_run','resolved_tier':'tier2','supersedes':{'sha256':r.sha256(g)}})
    upgraded=r.resolve_from_governance(g2,supersedes_path=first)
    assert {'word-delivery','page-render-audit'} <= ids(upgraded)
    assert v.validate(write(tmp_path/'p2.json',upgraded),g2,previous_path=first)['revision']==2
    with pytest.raises(ValueError):
        r.resolve_from_governance(g,supersedes_path=tmp_path/'p2.json')
    foreign=json.loads(first.read_text(encoding='utf-8')); foreign['mode']='reference_case_ingestion'
    with pytest.raises(ValueError, match='mode/tier'):
        r.resolve_from_governance(g2,supersedes_path=write(tmp_path/'foreign.json',foreign))


def test_recovery_is_bound_to_event_stage_and_detects_drift(tmp_path):
    r=load('resolve_harness_profile'); d=load('condition_detectors'); v=load('validate_harness_profile')
    proof=write(tmp_path/'failure.json',{'exit_code':1})
    event=d.detect('failure','coding',proof)
    events=write(tmp_path/'events.json',{'schema_version':'1.0','mode':'training_run','events':[event]})
    g=write(tmp_path/'g.json',{'mode':'training_run','resolved_tier':'tier1'})
    p=r.resolve_from_governance(g,condition_events_path=events)
    assert 'recovery-controller' in ids(p,'coding')
    assert 'recovery-controller' not in ids(p,'writing')
    assert all('recovery-detector' in ids(p,s) for s in p['stage_modules'])
    file=write(tmp_path/'p.json',p)
    assert v.validate(file,g)['profile']=='draft'
    proof.write_text('changed',encoding='utf-8')
    with pytest.raises(ValueError, match='evidence drift'):
        v.validate(file,g)


def make_bundle(tmp_path, *, hard=False, independent='pass'):
    h=load('validate_g5_bundle')
    evidence={'schema_version':'1.0','problem_rule_hashes':['A'*64],'assumptions':[],
              'mathematical_model':'m','results':'r','figures':[],'baseline':'b','validation':[]}
    write(tmp_path/'EVIDENCE_PACKAGE.json',evidence)
    hunter={'review_id':'FH-1','role':'failure_hunter','visibility':'evidence_package_only',
            'other_review_seen':False,'evidence_package_sha256':h.sha(tmp_path/'EVIDENCE_PACKAGE.json'),
            'reliability_score':90,'hard_failures':[{'failure_id':'HF-1','status':'open'}] if hard else []}
    write(tmp_path/'FAILURE_HUNTER.yaml',hunter)
    write(tmp_path/'SOLVER_RESPONSE.yaml',{'review_ids_addressed':['FH-1']})
    write(tmp_path/'INDEPENDENT_VALIDATION.yaml',{'solver_response_sha256':h.sha(tmp_path/'SOLVER_RESPONSE.yaml'),'status':independent})
    write(tmp_path/'G5_DECISION.yaml',{'schema_version':'1.0','execution_mode':'training_run',
          'review_bundle_id':'G5-1','hard_failures':['HF-1'] if hard else [],'soft_failures':[],
          'validation_quality':90,'reliability_score':90,'recommended_action':'accept'})
    return h


def test_reliability_without_upside_preserves_hard_gate(tmp_path):
    h=make_bundle(tmp_path)
    assert h.validate(tmp_path,reliability_only=True)['action']=='accept'
    with pytest.raises(FileNotFoundError):
        h.validate(tmp_path)
    r=load('resolve_harness_profile')
    baseline=r.resolve(mode='training_run',tier='tier1')
    ablated=r.resolve(mode='training_run',tier='tier1',disable_upside_review=True)
    assert ids(baseline)-ids(ablated)=={'g5-blind-upside-review'}
    make_bundle(tmp_path,hard=True)
    with pytest.raises(ValueError, match='open hard'):
        h.validate(tmp_path,reliability_only=True)
    make_bundle(tmp_path,independent='fail')
    with pytest.raises(ValueError, match='independent validation'):
        h.validate(tmp_path,reliability_only=True)


def telemetry_event(call_id='call-1', attempt=1):
    return {'schema_version':'1.0','run_id':'smoke','case_id':'synthetic', 'dataset_role':'structural',
            'call_id':call_id,'stage':'coding','kind':'tool','attempt':attempt,'execution_order':attempt,
            'captured_at':'2026-09-05T00:00:00+00:00','summary':'验证约束并记录失败原因',
            **{k:None for k in ('model_id','reasoning_effort','execution_instance_id','session_or_context_id',
                               'failure_class','human_intervention','prior_output_exposure','prompt_hash',
                               'config_hash','profile_hash','profile_version','reviewer_visible_inputs',
                               'reviewer_hidden_inputs','active_modules')},
            'input_artifact_hashes':{},'metrics':{k:{'value':None,'evidence':'missing'} for k in
                ('input_tokens','output_tokens','cached_tokens','wall_clock_seconds','tool_calls','context_peak')}}


def test_telemetry_idempotence_retries_missing_and_vault(tmp_path):
    t=load('run_telemetry'); e=telemetry_event()
    e['metrics']['wall_clock_seconds']={'value':2.0,'evidence':'observed'}
    assert t.record(tmp_path,e)
    assert not t.record(tmp_path,e)
    retry=copy.deepcopy(e); retry.update(call_id='call-2',attempt=2,execution_order=2)
    t.record(tmp_path,retry)
    summary=t.summarize(tmp_path)
    assert summary['calls']==2 and summary['retry_count']==1
    assert summary['by_stage']['coding']['wall_clock_seconds']['value']==4
    assert not summary['cost_claim_ready']
    assert summary['by_stage']['coding']['input_tokens']['value'] is None
    e['summary']='changed'
    with pytest.raises(ValueError,match='conflicting'):
        t.record(tmp_path,e)
    assert 'call-2' in t.render_vault(tmp_path)


def test_telemetry_cli_measures_real_short_run(tmp_path):
    template=write(tmp_path/'event.json',telemetry_event())
    ledger=tmp_path/'telemetry'
    result=subprocess.run([sys.executable,str(ROOT/'scripts/run_telemetry.py'),'run','--directory',str(ledger),
                           '--event',str(template),'--',sys.executable,'-c','assert sum(range(10)) == 45'],capture_output=True,text=True)
    assert result.returncode==0, result.stderr
    s=load('run_telemetry').summarize(ledger)
    assert s['by_stage']['coding']['tool_calls']['value']==1
    assert s['by_stage']['coding']['wall_clock_seconds']['value']>0
    assert not s['cost_claim_ready']


def test_snapshot_replays_original_inputs_after_source_drift(tmp_path):
    s=load('evidence_snapshot'); root=tmp_path/'case'; root.mkdir()
    source=root/'result.json'; source.write_text('{"result":42}',encoding='utf-8')
    manifest=s.capture(root,tmp_path/'store',[{'path':'result.json'}])
    source.write_text('{"result":43}',encoding='utf-8')
    out=tmp_path/'replay'; result=s.verify(manifest,root,out)
    assert result['historical_snapshot']=='valid'
    assert result['sources'][0]['current_source']=='drifted'
    assert json.loads((out/'result.json').read_text(encoding='utf-8'))['result']==42
    with pytest.raises(FileExistsError):
        s.verify(manifest,root,out)
    data=json.loads(manifest.read_text(encoding='utf-8'))
    blob=tmp_path/'store/objects'/data['entries'][0]['object_sha256']; blob.write_text('corrupt',encoding='utf-8')
    with pytest.raises(ValueError, match='object hash'):
        s.verify(manifest)


def test_snapshot_hash_only_and_escape_fail_closed(tmp_path):
    s=load('evidence_snapshot'); root=tmp_path/'case'; root.mkdir(); (root/'source').write_text('private')
    m=s.capture(root,tmp_path/'store',[{'path':'source','retention':'hash_only'}])
    assert not s.verify(m)['replayable']
    with pytest.raises(ValueError,match='cannot be replayed'):
        s.verify(m,replay_to=tmp_path/'replay')
    with pytest.raises(ValueError,match='escapes'):
        s.capture(root,tmp_path/'store',[{'path':'../outside'}])


def test_registry_rejects_cycle_and_missing_owner(tmp_path):
    v=load('validate_component_registry')
    data=yaml.safe_load((ROOT/'component_registry.yaml').read_text(encoding='utf-8'))
    data['components'][0]['dependencies']=['g2-tournament']
    path=tmp_path/'registry.yaml'; path.write_text(yaml.safe_dump(data),encoding='utf-8')
    with pytest.raises(ValueError,match='cycle'):
        v.validate(path,ROOT/'harness_profile_policy.yaml')


def test_single_check_entry_reuses_only_unchanged_success(tmp_path):
    case=tmp_path/'case'; case.mkdir(); h=make_bundle(case)
    v=load('validate_once')
    first=v.execute('g5',case,tmp_path/'cache',bundle=case,reliability_only=True)
    again=v.execute('g5',case,tmp_path/'cache',bundle=case,reliability_only=True)
    assert first['returncode']==0 and first['validator_calls']==1
    assert again['returncode']==0 and again['validator_calls']==0 and again['reused']
    make_bundle(case,hard=True)
    changed=v.execute('g5',case,tmp_path/'cache',bundle=case,reliability_only=True)
    assert changed['returncode']!=0 and not changed['reused']
    with pytest.raises(ValueError,match='outside'):
        v.execute('g5',case,case/'cache',bundle=case,reliability_only=True)


def test_generated_matrix_is_current_and_all_conditions_have_dependencies():
    views=load('generate_vnext_views'); matrix=views.build_matrix()
    saved=json.loads((ROOT/'meta/PROFILE_MODULE_MATRIX.json').read_text(encoding='utf-8'))
    assert matrix==saved
    assert len(matrix['conditional_scenarios'])==148


def test_yaml_whitelist_cannot_invent_a_rescue_implementation():
    r=load('resolve_harness_profile'); policy=r.load_policy()
    policy['executable_experimental_modules']=['ceiling-rescue']
    with pytest.raises(ValueError,match='executable contract'):
        r.resolve(mode='training_run',tier='tier1',policy=policy,experimental=['ceiling-rescue'])


def test_cached_g5_cannot_ignore_evidence_outside_case(tmp_path):
    case=tmp_path/'case'; case.mkdir(); make_bundle(case)
    source=write(tmp_path/'external.json',{'x':1})
    e=json.loads((case/'EVIDENCE_PACKAGE.json').read_text(encoding='utf-8'))
    e['artifact_root']='..'; e['results']={'path':'external.json','sha256':hashlib.sha256(source.read_bytes()).hexdigest().upper()}
    write(case/'EVIDENCE_PACKAGE.json',e)
    with pytest.raises(ValueError,match='cache input boundary'):
        load('validate_once').execute('g5',case,tmp_path/'cache',bundle=case,reliability_only=True)


def test_collector_understands_explicit_reliability_protocol(tmp_path):
    case=tmp_path/'case'; bundle=case/'review/g5/v1'; bundle.mkdir(parents=True)
    make_bundle(bundle)
    decision=json.loads((bundle/'G5_DECISION.yaml').read_text(encoding='utf-8'))
    decision['review_protocol']='reliability_only'
    write(bundle/'G5_DECISION.yaml',decision)
    record=load('collect_run_records').collect_run(case)
    assert record['route']['g5_integrity']['value']=='pass'
    assert record['quality']['competition_upside_score']['value'] is None
