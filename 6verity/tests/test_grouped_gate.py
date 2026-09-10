from __future__ import annotations
import copy
import importlib.util
import json
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[2]


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m


group = load(ROOT/'_references/scripts/grouped_gate.py', 'grouped_gate_test')
legacy = load(Path(__file__).with_name('test_human_gate.py'), 'legacy_gate_fixtures')


def test_executable_does_not_upgrade_uncertified_qualification(tmp_path):
    preflight = tmp_path / 'preflight.json'
    preflight.write_text(json.dumps({'status': 'executable', 'qualification': 'not_certified'}), encoding='utf-8')
    vector = group.status_vector(group.initial('evaluation_run'), tmp_path, preflight)
    assert vector['qualification']['state'] == 'not_certified'
    assert vector['submission_ready'] is False


def test_scoped_capability_exception_preserves_technical_checks_and_original_approval(case):
    root = case.project
    r = receipt(case, 'route')
    original = root / 'original-user.txt'
    original.write_text('Synthetic fixture user accepts unverified runtime capability for this route.', encoding='utf-8')
    artifact = group.base.artifact_record
    auth = {'run_id': 'fixture-run', 'scopes': ['gate:route'], 'decision': 'accepted', 'exception': True,
            'original': artifact(root, original),
            'artifacts': [artifact(root, r['report']), *[artifact(root, p) for p in r['artifacts'].values()]],
            'uncertified_fields': ['effective_reasoning_effort'], 'alternative_evidence': [artifact(root, original)]}
    auth_path = root / 'exception.json'
    write(auth_path, auth)
    r.update(capability_exception=str(auth_path), run_id='fixture-run')
    document = group.initial('evaluation_run')
    group.check(document, root, 'route', r)
    vector = group.status_vector(document, root)
    assert vector['qualification']['state'] == 'not_certified'
    assert not vector['authorization']['route_approved']
    original.write_text('changed evidence', encoding='utf-8')
    with pytest.raises(ValueError, match='hash mismatch'):
        group.validate(document, root)


@pytest.fixture
def case():
    helper = legacy.HumanGateTests()
    helper.setUp()
    yield helper
    helper.tearDown()


def write(path, data):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(data),encoding='utf-8')
    return str(path)


def receipt(case, phase):
    root=case.project
    report=root/f'reports/{phase}.md'; report.parent.mkdir(exist_ok=True)
    report.write_text('\n\n'.join('## '+h+'\n\n具体方法、验证证据和用户需要判断的取舍。' for h in group.HEADINGS[phase]),encoding='utf-8')
    artifacts={role:write(root/f'artifacts/{phase}/{role}.json',{'role':role}) for role in group.REQUIRED_ARTIFACTS[phase]}
    if phase=='route':
        write(Path(artifacts['execution_contract']),{'continue_after_execution_report':True,
            'fixed_assumptions':['冻结题面解释'],'allowed_changes':['局部参数调试'],
            'reapproval_triggers':['路线变更或预算越界'],'max_local_retries':2,'max_wall_clock_seconds':600})
    r={'schema_version':'1.0','phase':phase,'report':str(report),'checks':{g:'pass' for g in group.PHASES[phase]},
       'issues':[],'artifacts':artifacts,'route_ledger':str(case.ledger),'capability_snapshot':str(case.snapshot)}
    if phase=='execution': r.update(within_approved_scope=True,within_approved_budget=True)
    if phase=='delivery':
        r.update(ai_used=True,review_isolation='distinct_contexts')
        for role,suffix in [('paper_docx','.docx'),('paper_pdf','.pdf'),('ai_details_pdf','.pdf')]:
            artifacts[role]=write(root/f'artifacts/delivery/{role}{suffix}',{'role':role})
        artifacts['final_manifest']=write(root/'submission/FINAL_DELIVERY.json',{
            'docx':{'path':artifacts['paper_docx'],'sha256':group.base.artifact_record(root,artifacts['paper_docx'])['sha256'],'editable':True},
            'pdf':{'path':artifacts['paper_pdf'],'sha256':group.base.artifact_record(root,artifacts['paper_pdf'])['sha256'],'derived_from_same_loop_docx':True},
            'visual_qa':'all pages passed'})
        bundle=root/'review/g5/v1'; bundle.mkdir(parents=True)
        helpers=load(ROOT/'_references/harness/tests/test_vnext_architecture.py','g5_fixtures')
        g5=helpers.make_bundle(bundle)
        ceiling={'review_id':'CR-1','role':'ceiling_reviewer','visibility':'evidence_package_only',
                 'other_review_seen':False,'evidence_package_sha256':g5.sha(bundle/'EVIDENCE_PACKAGE.json'),
                 'competition_upside_score':80}
        write(bundle/'CEILING_REVIEWER.yaml',ceiling)
        write(bundle/'SOLVER_RESPONSE.yaml',{'review_ids_addressed':['FH-1','CR-1']})
        write(bundle/'INDEPENDENT_VALIDATION.yaml',{'solver_response_sha256':g5.sha(bundle/'SOLVER_RESPONSE.yaml'),'status':'pass'})
        d=json.loads((bundle/'G5_DECISION.yaml').read_text(encoding='utf-8'))
        d.update(baseline_quality=75,innovation_quality=80,competition_upside_score=80,ceiling_bottlenecks=[],alternative_routes=[])
        write(bundle/'G5_DECISION.yaml',d)
        for role,filename in {'evidence_package':'EVIDENCE_PACKAGE.json','failure_review':'FAILURE_HUNTER.yaml',
            'ceiling_review':'CEILING_REVIEWER.yaml','solver_response':'SOLVER_RESPONSE.yaml',
            'independent_validation':'INDEPENDENT_VALIDATION.yaml','g5_decision':'G5_DECISION.yaml'}.items():
            artifacts[role]=str(bundle/filename)
        write(Path(artifacts['final_review_input']),{'artifacts':{role:group.base.artifact_record(root,artifacts[role]) for role in
            ('paper_docx','paper_pdf','final_manifest','ai_statement','ai_log','ai_details_pdf','supporting_materials')}})
    return r


def prepare_final_routes(case, receipt):
    router=case.router; root=case.project
    for gate,task_class,input_role,roles,topology in [
        ('G5','g5_failure_review','evidence_package',{'failure_hunter':'failure_review','ceiling_reviewer':'ceiling_review'},'dual_review'),
        ('G6','g6_final_review','final_review_input',{'structure_reviewer':'structure_review','prize_reviewer':'prize_review'},'ensemble')]:
        task_id='final-'+gate
        assessed=router.assess(case.ledger,case.snapshot,mode='evaluation_run',task_id=task_id,
            stage='verification',task_class=task_class,gate_id=gate,requested_effort='ultra',requested_topology=topology)
        frozen=router.file_sha(Path(receipt['artifacts'][input_role]))
        units=[]
        for role,artifact_role in roles.items():
            path=Path(receipt['artifacts'][artifact_role])
            units.append({'unit_id':gate+'-'+role,'role':role,'context_id':gate+'-'+role,
                          'visible_input_sha256':frozen,'output':{'path':path.relative_to(root).as_posix(),'sha256':router.file_sha(path)}})
        tr=write(root/f'run/{gate}-topology.json',router.seal_topology({'schema_version':'1.0','receipt_id':'TR-'+gate,
            'captured_at':'2026-09-07T00:00:00+00:00','task_id':task_id,'assessment_event_id':assessed['event_id'],
            'topology':topology,'shared_context':False,'frozen_input_sha256':frozen,'execution_units':units}))
        model=write(root/f'run/{gate}-model.json',{'schema_version':'1.0','receipt_id':'MR-'+gate,
            'captured_at':'2026-09-07T00:00:00+00:00','source':'reasoning_effort_interface','task_id':task_id,
            'assessment_event_id':assessed['event_id'],'effective_model_id':'model','effective_reasoning_effort':'ultra','effective_topology':topology})
        router.apply(case.ledger,case.snapshot,Path(model),task_id=task_id,project_root=root,topology_receipt_path=Path(tr))
        router.complete(case.ledger,task_id=task_id,project_root=root,outputs=[receipt['artifacts'][r] for r in roles.values()])
        router.reassess(case.ledger,case.snapshot,task_id=task_id)


def route_approved(case):
    doc=group.initial('evaluation_run'); r=receipt(case,'route')
    for g in ['G1','G2']: case.prepare_route(g)
    group.check(doc,case.project,'route',r)
    digest=group.state(doc)['route']['checkpoint']['checkpoint_event_hash']
    group.approve(doc,case.project,'route','D-route','用户明确批准当前路线及有界自动执行',digest)
    return doc


def execution_checked(case):
    doc=route_approved(case); r=receipt(case,'execution')
    for g in ['G3','G4']: case.prepare_route(g)
    group.check(doc,case.project,'execution',r)
    return doc


def test_two_approvals_with_continuous_middle_and_legacy_verify(case):
    doc=execution_checked(case)
    assert group.state(doc)['execution']['approval'] is None
    assert len([e for e in doc['audit_chain'] if e['event_type']=='approved'])==1
    assert group.base.validate_document(doc,case.project,['G1','G2','G3','G4'],True)==[]
    r=receipt(case,'delivery'); prepare_final_routes(case,r)
    group.check(doc,case.project,'delivery',r)
    with pytest.raises(ValueError,match='PENDING_FINAL_APPROVAL'):
        group.verify_required(doc,case.project,['G6'])
    h=group.state(doc)['delivery']['checkpoint']['checkpoint_event_hash']
    group.approve(doc,case.project,'delivery','D-final','用户明确批准当前论文和完整交付文件',h)
    assert group.base.validate_document(doc,case.project,list(group.base.GATE_ORDER),True)==[]
    assert len([e for e in doc['audit_chain'] if e['event_type']=='approved'])==2


def test_cannot_skip_route_or_approve_middle(case):
    with pytest.raises(ValueError,match='route approval'):
        group.check(group.initial('evaluation_run'),case.project,'execution',receipt(case,'execution'))
    with pytest.raises(ValueError,match='not a human approval'):
        group.approve(group.initial('evaluation_run'),case.project,'execution','D','允许继续','x')


@pytest.mark.parametrize('change', ['budget','scope','hard_failure','user_decision','technical_fail'])
def test_blocking_results_do_not_advance(case,change):
    doc=route_approved(case); r=receipt(case,'execution')
    for g in ['G3','G4']: case.prepare_route(g)
    if change=='budget': r['within_approved_budget']=False
    if change=='scope': r['within_approved_scope']=False
    if change=='technical_fail': r['checks']['G4']='fail'
    if change in {'hard_failure','user_decision'}:
        r['issues']=[{'id':'I1','impact':'结果改变','next_check':'需要重算','status':'open',
                      'blocking':change=='hard_failure','requires_user_decision':change=='user_decision'}]
    before=copy.deepcopy(doc)
    with pytest.raises(ValueError): group.check(doc,case.project,'execution',r)
    assert doc==before


def test_nonblocking_uncertainty_can_reach_review(case):
    doc=route_approved(case); r=receipt(case,'execution')
    for g in ['G3','G4']: case.prepare_route(g)
    r['issues']=[{'id':'I1','impact':'边界条件证据有限','next_check':'最终独立扰动检查',
                  'status':'open','blocking':False,'requires_user_decision':False}]
    group.check(doc,case.project,'execution',r)
    assert group.state(doc)['execution']['checkpoint']['issues']==r['issues']


def test_drift_requires_invalidation_without_losing_route(case):
    doc=execution_checked(case)
    checkpoint=group.state(doc)['execution']['checkpoint']
    path=case.project/checkpoint['artifacts']['results']['path']; path.write_text('changed',encoding='utf-8')
    with pytest.raises(ValueError): group.validate(doc,case.project)
    group.base.append_event(doc,'execution','invalidated',{'reason':'结果修改重跑'})
    assert group.validate(doc,case.project)['route']['approval'] is not None
    assert group.state(doc)['delivery']['checkpoint'] is None


def test_final_cannot_claim_ultra_from_single_high(case):
    doc=execution_checked(case); r=receipt(case,'delivery')
    for g in ['G5','G6']: case.prepare_route(g)
    with pytest.raises(ValueError,match='Ultra'):
        group.check(doc,case.project,'delivery',r)


def test_final_manifest_and_ai_materials_cannot_be_omitted(case):
    doc=execution_checked(case); r=receipt(case,'delivery'); prepare_final_routes(case,r)
    del r['artifacts']['ai_details_pdf']
    with pytest.raises(ValueError,match='AI usage details'):
        group.check(doc,case.project,'delivery',r)


def test_stale_display_hash_and_repeated_decision_id_fail(case):
    doc=route_approved(case)
    with pytest.raises(ValueError,match='displayed'):
        group.approve(doc,case.project,'route','new','用户批准旧版内容','wrong-hash')
    h=group.state(doc)['route']['checkpoint']['checkpoint_event_hash']
    with pytest.raises(ValueError,match='already used'):
        group.approve(doc,case.project,'route','D-route','用户批准当前内容',h)


def test_imported_approval_is_bound_idempotent_and_survives_resume(case):
    doc=group.initial('evaluation_run'); r=receipt(case,'route')
    for gate in ['G1','G2']: case.prepare_route(gate)
    group.check(doc,case.project,'route',r)
    checkpoint=group.state(doc)['route']['checkpoint']
    approval={
        'schema_version':'1.0','decision_id':'IMPORTED-ROUTE-1','decision':'approved','phase':'route',
        'checkpoint_event_hash':checkpoint['checkpoint_event_hash'],
        'checkpoint_artifacts_sha256':group.checkpoint_artifacts_digest(checkpoint),
        'approval_evidence':'用户此前明确批准该路线、合同和有界连续执行。',
        'source_event_id':'conversation-event-1','source_recorded_at':'2026-09-08T00:00:00+00:00',
    }
    path=Path(write(case.project/'compliance/approval-import.json',approval))
    expected=group.base.artifact_record(case.project,path)['sha256']
    assert group.import_approval(doc,case.project,path,expected)
    assert not group.import_approval(doc,case.project,path,expected)
    serialized=json.loads(json.dumps(doc,ensure_ascii=False))
    assert group.validate(serialized,case.project)['route']['approval']['decision_id']=='IMPORTED-ROUTE-1'
    vector=group.status_vector(serialized,case.project)
    assert vector['authorization']['route_approved'] and vector['authorization']['state']=='partial'


def test_imported_approval_rejects_wrong_checkpoint_or_artifact_binding(case):
    doc=group.initial('evaluation_run'); r=receipt(case,'route')
    for gate in ['G1','G2']: case.prepare_route(gate)
    group.check(doc,case.project,'route',r)
    checkpoint=group.state(doc)['route']['checkpoint']
    base_record={
        'schema_version':'1.0','decision_id':'IMPORTED-BAD-1','decision':'approved','phase':'route',
        'checkpoint_event_hash':checkpoint['checkpoint_event_hash'],
        'checkpoint_artifacts_sha256':'0'*64,
        'approval_evidence':'用户批准的是另一份产物。','source_event_id':'conversation-event-bad',
        'source_recorded_at':'2026-09-08T00:00:00+00:00',
    }
    path=Path(write(case.project/'compliance/approval-bad.json',base_record))
    with pytest.raises(ValueError,match='artifacts'):
        group.import_approval(doc,case.project,path)
    base_record['checkpoint_artifacts_sha256']=group.checkpoint_artifacts_digest(checkpoint)
    base_record['checkpoint_event_hash']='0'*64
    write(path,base_record)
    with pytest.raises(ValueError,match='displayed'):
        group.import_approval(doc,case.project,path)


def test_training_does_not_create_human_gate():
    with pytest.raises(ValueError): group.initial('training_run')


def test_routing_plan_keeps_frozen_baseline_and_does_not_apply_settings(case):
    result=group.routing_plan(case.snapshot)
    assert result['execution']['reasoning_effort']=='high'
    assert result['delivery']['requested_effort']=='ultra'
    assert result['settings_applied'] is False


def test_delivery_input_cannot_bind_a_different_paper(case):
    doc=execution_checked(case); r=receipt(case,'delivery'); prepare_final_routes(case,r)
    p=Path(r['artifacts']['final_review_input'])
    content=json.loads(p.read_text(encoding='utf-8')); content['artifacts']['paper_docx']['sha256']='0'*64
    write(p,content)
    with pytest.raises(ValueError,match='actual delivery'):
        group.check(doc,case.project,'delivery',r)


def test_g5_failure_cannot_be_hidden_by_a_pass_receipt(case):
    doc=execution_checked(case); r=receipt(case,'delivery'); prepare_final_routes(case,r)
    p=Path(r['artifacts']['g5_decision']); d=json.loads(p.read_text(encoding='utf-8'))
    d['recommended_action']='local_fix'; write(p,d)
    with pytest.raises(ValueError,match='accepted G5'):
        group.check(doc,case.project,'delivery',r)
