#!/usr/bin/env python3
"""Three technical phases, two human approvals. Legacy G1-G6 approvals remain v2."""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import sys

from jsonschema import Draft202012Validator


def sibling(name):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def routing_plan(snapshot_path):
    """Advice only; actual settings still require runtime receipts."""
    router = base.load_router()
    snapshot = router.validate_snapshot(snapshot_path)
    baseline = snapshot['current']
    model = next(m for m in snapshot['models'] if m['model_id'] == baseline['model_id'])
    available = model['supported_reasoning_efforts']
    higher = [e for e in available if router.EFFORTS.index(e) >= router.EFFORTS.index('high') and e!='ultra']
    high = max(higher or (['ultra'] if 'ultra' in available else []),
               key=router.EFFORTS.index, default=None)
    return {'baseline_source':'frozen capability snapshot current setting',
            'route':{'model_id':baseline['model_id'], 'requested_effort':high, 'status':'ready' if high else 'unavailable'},
            'execution':{**baseline, 'topology':'single'},
            'delivery':{'model_id':baseline['model_id'], 'requested_effort':'ultra',
                        'G5_topology':'dual_review','G6_topology':'ensemble',
                        'status':'ready' if 'ultra' in available and {'dual_review','ensemble'} <= set(snapshot['supported_topologies']) else 'unavailable'},
            'settings_applied':False}


base = sibling('human_gate')
PHASES = {'route': ['G1', 'G2'], 'execution': ['G3', 'G4'], 'delivery': ['G5', 'G6']}
APPROVAL_PHASES = {'route', 'delivery'}
APPROVAL_IMPORT_SCHEMA = json.loads((Path(__file__).resolve().parents[1] / 'harness/schemas/approval_import.schema.json').read_text(encoding='utf-8'))
HEADINGS = {
    'route': ['题目拆解', '关键假设与歧义', '候选路线比较', '推荐方案与算法解释', '工具与复现步骤', '预算与自动执行边界', '请你决定'],
    'execution': ['实际运行与复现', '关键结果与题目结论', '已完成排查', '遗留问题与影响', '下一阶段审查重点'],
    'delivery': ['结构完整性评审', '争奖潜力评审', '分歧与修复复验', '结论与不确定性', '交付清单', '请你决定'],
}
REQUIRED_ARTIFACTS = {
    'route': {'problem_freeze', 'route_selection', 'execution_contract'},
    'execution': {'model_contract', 'results', 'validation_report', 'issue_register'},
    'delivery': {'evidence_package', 'failure_review', 'ceiling_review', 'solver_response',
                 'independent_validation', 'g5_decision', 'paper_docx', 'paper_pdf',
                 'final_manifest', 'ai_log', 'ai_statement', 'supporting_materials', 'final_check_report',
                 'final_review_input', 'structure_review', 'prize_review'},
}


def empty_state():
    return {phase: {'checkpoint': None, 'approval': None} for phase in PHASES}


def initial(mode):
    if mode not in {'evaluation_run', 'live_competition', 'release_candidate'}:
        raise ValueError('grouped human gates apply only to formal modes')
    document = {'schema_version': '3.0', 'approval_protocol': 'two_approvals',
                'mode': mode, 'audit_chain': []}
    base.append_event(document, 'SYSTEM', 'initialized', {'mode': mode, 'approval_protocol': 'two_approvals'})
    return document


def state(document):
    if document.get('schema_version') != '3.0' or document.get('approval_protocol') != 'two_approvals':
        raise ValueError('grouped gate requires schema 3.0; do not migrate approvals implicitly')
    base.fail_if_errors(base.validate_chain(document))
    events = document['audit_chain']
    if events[0]['event_type'] != 'initialized' or events[0]['payload'] != {
        'mode': document['mode'], 'approval_protocol': 'two_approvals'
    } or document['mode'] not in {'evaluation_run','live_competition','release_candidate'}:
        raise ValueError('grouped initialization mismatch')
    current = empty_state()
    decisions = set()
    for event in events[1:]:
        phase, kind, payload = event['gate_id'], event['event_type'], event['payload']
        if phase not in PHASES:
            raise ValueError('unknown grouped phase')
        if kind == 'checked':
            if phase != 'route' and current['route']['approval'] is None:
                raise ValueError('route must be explicitly approved before execution')
            if phase == 'delivery' and current['execution']['checkpoint'] is None:
                raise ValueError('execution check must pass before delivery review')
            current[phase] = {'checkpoint': payload, 'approval': None}
        elif kind == 'approved':
            if phase not in APPROVAL_PHASES or current[phase]['checkpoint'] is None:
                raise ValueError('only route and delivery accept human approvals after checks')
            if payload['checkpoint_event_hash'] != current[phase]['checkpoint']['checkpoint_event_hash']:
                raise ValueError('approval does not bind the displayed checkpoint')
            if payload['decision_id'] in decisions:
                raise ValueError('decision id already used')
            decisions.add(payload['decision_id'])
            current[phase]['approval'] = payload
        elif kind == 'invalidated':
            current[phase] = {'checkpoint': None, 'approval': None}
        else:
            raise ValueError('unknown grouped gate event')
        if kind in {'checked', 'invalidated'}:
            for downstream in list(PHASES)[list(PHASES).index(phase)+1:]:
                current[downstream] = {'checkpoint': None, 'approval': None}
    return current


def report_check(root, phase, report):
    path, _ = base.resolve_scoped(root, report)
    if path.suffix.lower() != '.md':
        raise ValueError('phase report must be readable Markdown')
    text = path.read_text(encoding='utf-8')
    missing = [h for h in HEADINGS[phase] if '## '+h not in text]
    if missing or base.PLACEHOLDER_RE.search(text):
        raise ValueError(f'phase report incomplete: {missing}')
    return base.artifact_record(root, report)


def checkpoint_payload(root, phase, receipt, mode):
    if receipt.get('phase') != phase or receipt.get('schema_version') != '1.0':
        raise ValueError('checkpoint receipt phase/schema mismatch')
    if receipt.get('checks') != {gate: 'pass' for gate in PHASES[phase]}:
        raise ValueError('all technical checks must pass; approval cannot override failure')
    issues = receipt.get('issues')
    if not isinstance(issues, list):
        raise ValueError('explicit issue register required')
    for issue in issues:
        if not all(isinstance(issue.get(k), str) and issue[k].strip() for k in ('id','impact','next_check')):
            raise ValueError('issue needs id, impact and next_check')
        if issue.get('status') not in {'open','closed'} or type(issue.get('blocking')) is not bool or type(issue.get('requires_user_decision')) is not bool:
            raise ValueError('invalid issue status')
        if issue['status'] == 'open' and (issue['blocking'] or issue['requires_user_decision']):
            raise ValueError('unresolved blocking issue or user decision; cannot advance')
    artifacts = receipt.get('artifacts', {})
    if not isinstance(artifacts, dict) or not REQUIRED_ARTIFACTS[phase] <= set(artifacts):
        raise ValueError('checkpoint missing required artifact roles')
    records = {role: base.artifact_record(root, value) for role, value in artifacts.items()}
    packet = report_check(root, phase, receipt['report'])
    if phase == 'route':
        contract_path, _ = base.resolve_scoped(root, artifacts['execution_contract'])
        contract = base.read_json(contract_path)
        if contract.get('continue_after_execution_report') is not True or not all(
            isinstance(contract.get(k), list) and contract[k] and all(isinstance(x,str) and x.strip() for x in contract[k])
            for k in ('fixed_assumptions','allowed_changes','reapproval_triggers')
        ):
            raise ValueError('route contract must explicitly authorize bounded continuous execution')
        for key in ('max_local_retries','max_wall_clock_seconds'):
            if type(contract.get(key)) is not int or contract[key] <= 0:
                raise ValueError('route contract needs positive retry and time bounds')
    if phase == 'execution':
        if receipt.get('within_approved_scope') is not True or receipt.get('within_approved_budget') is not True:
            raise ValueError('scope or budget changed: request a new route decision')
    if phase == 'delivery':
        for role, suffix in [('paper_docx','.docx'), ('paper_pdf','.pdf')]:
            if Path(records[role]['path']).suffix.lower() != suffix:
                raise ValueError(f'{role} has incorrect format')
        if Path(records['final_manifest']['path']).name != 'FINAL_DELIVERY.json':
            raise ValueError('final delivery manifest required')
        if type(receipt.get('ai_used')) is not bool:
            raise ValueError('explicit AI use disclosure required')
        if receipt['ai_used'] and 'ai_details_pdf' not in records:
            raise ValueError('AI usage details PDF required')
        if receipt['ai_used'] and Path(records['ai_details_pdf']['path']).suffix.lower() != '.pdf':
            raise ValueError('AI details must be PDF')
        if receipt.get('review_isolation') != 'distinct_contexts':
            raise ValueError('final review requires frozen input and distinct-context receipts')
        final_path, _ = base.resolve_scoped(root, artifacts['final_manifest'])
        final = base.read_json(final_path)
        for label, role in [('docx','paper_docx'), ('pdf','paper_pdf')]:
            expected = final.get(label, {})
            path, _ = base.resolve_scoped(root, expected.get('path',''))
            if base.artifact_record(root,path)['sha256'] != records[role]['sha256'] or expected.get('sha256','').lower() != records[role]['sha256']:
                raise ValueError('final manifest does not bind delivered paper')
        if final.get('visual_qa') != 'all pages passed' or final.get('docx',{}).get('editable') is not True or final.get('pdf',{}).get('derived_from_same_loop_docx') is not True:
            raise ValueError('final delivery hygiene/visual QA evidence is incomplete')
        review_input_path, _ = base.resolve_scoped(root, artifacts['final_review_input'])
        review_input = base.read_json(review_input_path)
        visible_roles = ['paper_docx','paper_pdf','final_manifest','ai_statement','ai_log','supporting_materials']
        if receipt['ai_used']: visible_roles.append('ai_details_pdf')
        for role in visible_roles:
            if review_input.get('artifacts',{}).get(role) != records[role]:
                raise ValueError('frozen final review input must bind the actual delivery artifacts')
        # Reuse the existing G5 hard gate rather than trusting checks={G5:pass} alone.
        g5_path = Path(__file__).resolve().parents[1] / 'harness/scripts/validate_g5_bundle.py'
        spec = importlib.util.spec_from_file_location('grouped_g5', g5_path)
        g5 = importlib.util.module_from_spec(spec); spec.loader.exec_module(g5)
        evidence_path, _ = base.resolve_scoped(root, artifacts['evidence_package'])
        bundle = evidence_path.parent
        required_files = {'failure_review':'FAILURE_HUNTER.yaml', 'ceiling_review':'CEILING_REVIEWER.yaml',
                          'solver_response':'SOLVER_RESPONSE.yaml','independent_validation':'INDEPENDENT_VALIDATION.yaml',
                          'g5_decision':'G5_DECISION.yaml'}
        for role, filename in required_files.items():
            if base.artifact_record(root,bundle/filename) != records[role]:
                raise ValueError('G5 roles must bind the same actual review bundle')
        route_args = {}
        if (bundle/'ROUTING_BINDING.json').exists():
            route_args = {'route_ledger':base.resolve_scoped(root,receipt['route_ledger'])[0],
                          'capability_snapshot':base.resolve_scoped(root,receipt['capability_snapshot'])[0], 'project_root':root}
        if g5.validate(bundle, **route_args)['action'] != 'accept':
            raise ValueError('final delivery requires an accepted G5 decision')
    if receipt.get('capability_exception'):
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'harness/scripts'))
        from workflow_state import authorization
        from runtime_support import verify_record, read_json
        exception_record = base.artifact_record(root, receipt['capability_exception'])
        exception = read_json(verify_record(root, exception_record))
        dimensions = authorization(root, exception, receipt['run_id'], 'gate:' + phase)
        if not exception.get('exception'):
            raise ValueError('gate capability exception must explicitly preserve uncertified fields')
        approved = {(r['path'], r['sha256'].lower()) for r in exception['artifacts']}
        if any((r['path'], r['sha256'].lower()) not in approved for r in [packet, *records.values()]):
            raise ValueError('capability exception does not bind every displayed phase artifact')
        payload = {'report': packet, 'artifacts': records, 'issues': issues,
                   'route_references': {}, 'capability_snapshot': None,
                   'qualification': 'not_certified', 'capability_exception': exception_record,
                   'checks': receipt['checks'], 'phase': phase, 'source_receipt': receipt}
        payload['checkpoint_event_hash'] = base.event_digest(payload)
        return payload
    router = base.load_router()
    ledger, _ = base.resolve_scoped(root, receipt['route_ledger'])
    snapshot, _ = base.resolve_scoped(root, receipt['capability_snapshot'])
    capability = router.validate_snapshot(snapshot)
    references = {}
    for gate in PHASES[phase]:
        reference = router.completed_gate_reference(ledger, snapshot, root, gate)
        events = router.read_ledger(ledger)
        completed = next(e for e in events if e['event_id'] == reference['event_id'])
        if completed['execution_mode'] != mode:
            raise ValueError('route execution mode differs from gate mode')
        if phase == 'route' and router.EFFORTS.index(completed['resolved']['reasoning_effort']) < router.EFFORTS.index('high'):
            raise ValueError('route decision requires verified high-or-higher reasoning effort')
        if phase == 'execution':
            actual = {key:completed['resolved'][key] for key in ('model_id','reasoning_effort')}
            if actual != capability['current']:
                exception = receipt.get('effort_exceptions',{}).get(gate)
                if not isinstance(exception,str) or len(exception.strip())<8:
                    raise ValueError('execution must use frozen baseline or record a concrete bounded diagnostic exception')
        if phase == 'delivery':
            if completed['resolved']['reasoning_effort'] != 'ultra' or completed['resolved']['topology'] not in {'dual_review','ensemble'} or not completed.get('topology_receipt'):
                raise ValueError('requested Ultra final review is not verified; do not silently downgrade')
            topology_path, _ = base.resolve_scoped(root, completed['topology_receipt']['path'])
            topology = router.validate_topology(topology_path, root)
            input_role = 'evidence_package' if gate == 'G5' else 'final_review_input'
            if topology['frozen_input_sha256'].lower() != records[input_role]['sha256']:
                raise ValueError('review topology does not bind the actual frozen input')
            roles = {'failure_hunter':'failure_review','ceiling_reviewer':'ceiling_review'} if gate=='G5' else {
                'structure_reviewer':'structure_review', 'prize_reviewer':'prize_review'}
            units = {u['role']:u for u in topology['execution_units']}
            for role, artifact_role in roles.items():
                if role not in units or units[role]['output']['sha256'].lower() != records[artifact_role]['sha256']:
                    raise ValueError('final review is missing a bound required perspective')
        references[gate] = reference
    payload = {'report': packet, 'artifacts': records, 'issues': issues,
               'route_references': references, 'capability_snapshot': base.artifact_record(root, snapshot),
               'checks': receipt['checks'], 'phase': phase,
               'source_receipt': receipt}
    # Hash the complete technical payload; human approvals bind exactly this checkpoint.
    payload['checkpoint_event_hash'] = base.event_digest(payload)
    return payload


def checkpoint_artifacts_digest(checkpoint):
    return base.event_digest({'report': checkpoint['report'], 'artifacts': checkpoint['artifacts']})


def _validate_imported_approval(root, phase, checkpoint, payload):
    imported = payload.get('imported_from')
    if not isinstance(imported, dict):
        return
    base.fail_if_errors(base.check_artifact_record(root, imported, f'{phase} imported approval'))
    path, _ = base.resolve_scoped(root, imported['path'])
    record = base.read_json(path)
    errors = list(Draft202012Validator(APPROVAL_IMPORT_SCHEMA).iter_errors(record))
    if errors:
        raise ValueError(f'imported approval schema invalid: {errors[0].message}')
    expected = {
        'decision_id': record['decision_id'], 'approval_evidence': record['approval_evidence'],
        'source_event_id': record['source_event_id'], 'source_recorded_at': record['source_recorded_at'],
        'checkpoint_event_hash': record['checkpoint_event_hash'],
    }
    if any(payload.get(key) != value for key, value in expected.items()):
        raise ValueError('imported approval payload no longer matches its source record')
    if record['phase'] != phase or record['checkpoint_event_hash'] != checkpoint['checkpoint_event_hash']:
        raise ValueError('imported approval does not bind the current phase checkpoint')
    if record['checkpoint_artifacts_sha256'] != checkpoint_artifacts_digest(checkpoint):
        raise ValueError('imported approval artifact binding is incorrect')


def validate(document, root):
    current = state(document)
    for phase, item in current.items():
        checkpoint = item['checkpoint']
        if not checkpoint:
            continue
        if checkpoint['checkpoint_event_hash'] != base.event_digest({k:v for k,v in checkpoint.items() if k!='checkpoint_event_hash'}):
            raise ValueError('checkpoint payload drift')
        if checkpoint_payload(root, phase, checkpoint['source_receipt'], document['mode']) != checkpoint:
            raise ValueError('checkpoint evidence no longer validates')
        for record in [checkpoint['report'], *checkpoint['artifacts'].values()]:
            base.fail_if_errors(base.check_artifact_record(root, record, phase))
        for gate, reference in checkpoint['route_references'].items():
            base.fail_if_errors(base.check_route_reference(root, gate, reference, checkpoint['capability_snapshot']))
        if item['approval'] is not None:
            _validate_imported_approval(root, phase, checkpoint, item['approval'])
    return current


def check(document, root, phase, receipt):
    validate(document, root)
    current = state(document)
    if phase != 'route' and current['route']['approval'] is None:
        raise ValueError('route approval required')
    if phase == 'delivery' and current['execution']['checkpoint'] is None:
        raise ValueError('execution check required')
    payload = checkpoint_payload(root, phase, receipt, document['mode'])
    base.append_event(document, phase, 'checked', payload)
    state(document)


def approve(document, root, phase, decision_id, evidence, checkpoint_hash):
    if phase not in APPROVAL_PHASES:
        raise ValueError('execution is a technical checkpoint, not a human approval')
    current = validate(document, root)
    cp = current[phase]['checkpoint']
    if not cp or cp['checkpoint_event_hash'] != checkpoint_hash:
        raise ValueError('approve only the displayed current checkpoint hash')
    if len(evidence.strip()) < 4 or not decision_id.strip() or base.PLACEHOLDER_RE.search(evidence):
        raise ValueError('explicit user approval evidence required')
    if base.IDENTITY_RE.search(evidence):
        raise ValueError('keep approval records anonymous')
    if any(e['event_type']=='approved' and e['payload']['decision_id']==decision_id for e in document['audit_chain']):
        raise ValueError('decision id already used')
    base.append_event(document, phase, 'approved', {'decision_id':decision_id,
        'approval_evidence':evidence, 'actor_role':base.ACTOR_ROLE, 'checkpoint_event_hash':checkpoint_hash})


def import_approval(document, root, approval_record, expected_sha256=None):
    """Append an existing explicit approval without asking the user to repeat it."""
    current = validate(document, root)
    path, _ = base.resolve_scoped(root, approval_record)
    artifact = base.artifact_record(root, path)
    if expected_sha256 and artifact['sha256'].lower() != expected_sha256.lower():
        raise ValueError('approval record hash differs from the expected source hash')
    record = base.read_json(path)
    errors = list(Draft202012Validator(APPROVAL_IMPORT_SCHEMA).iter_errors(record))
    if errors:
        raise ValueError(f'imported approval schema invalid: {errors[0].message}')
    phase = record['phase']
    checkpoint = current[phase]['checkpoint']
    if checkpoint is None or record['checkpoint_event_hash'] != checkpoint['checkpoint_event_hash']:
        raise ValueError('imported approval does not bind the displayed current checkpoint')
    if record['checkpoint_artifacts_sha256'] != checkpoint_artifacts_digest(checkpoint):
        raise ValueError('imported approval does not bind the current checkpoint artifacts')
    evidence = record['approval_evidence']
    if base.PLACEHOLDER_RE.search(evidence) or base.IDENTITY_RE.search(evidence):
        raise ValueError('imported approval evidence is placeholder or contains identity data')
    duplicates = [event for event in document['audit_chain'] if event['event_type'] == 'approved'
                  and event['payload'].get('decision_id') == record['decision_id']]
    if duplicates:
        existing = duplicates[0]['payload']
        if existing.get('imported_from') == artifact and existing.get('checkpoint_event_hash') == record['checkpoint_event_hash']:
            return False
        raise ValueError('decision id already used by different approval evidence')
    payload = {
        'decision_id': record['decision_id'], 'approval_evidence': evidence,
        'actor_role': base.ACTOR_ROLE, 'checkpoint_event_hash': record['checkpoint_event_hash'],
        'source_event_id': record['source_event_id'], 'source_recorded_at': record['source_recorded_at'],
        'imported_from': artifact,
    }
    base.append_event(document, phase, 'approved', payload)
    _validate_imported_approval(root, phase, checkpoint, payload)
    return True


def status_vector(document, root, preflight=None):
    current = validate(document, root)
    qualification = {'state': 'unknown', 'reasons': ['no preflight receipt supplied']}
    if preflight is not None:
        path, _ = base.resolve_scoped(root, preflight)
        item = base.read_json(path)
        if item.get('status') not in {'executable', 'blocked'}:
            raise ValueError('preflight receipt has invalid status')
        declared = item.get('qualification')
        if isinstance(declared, dict):
            declared = declared.get('state')
        qualification_state = 'blocked' if item['status'] == 'blocked' else ('not_certified' if declared == 'not_certified' or item.get('exception_receipt') else 'pass')
        if item.get('exception_receipt'):
            sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'harness/scripts'))
            from workflow_state import authorization
            from runtime_support import verify_record, read_json
            exception = read_json(verify_record(root, item['exception_receipt']))
            authorization(root, exception, item['run_id'], 'runtime_capability')
        qualification = {'state': qualification_state,
                         'reasons': item.get('failures', []), 'receipt': base.artifact_record(root, path)}
    route_approved = current['route']['approval'] is not None
    exception_phases = [phase for phase, item in current.items()
                        if item['checkpoint'] and item['checkpoint'].get('qualification') == 'not_certified']
    if exception_phases:
        qualification = {**qualification, 'state': 'not_certified', 'exception_phases': exception_phases}
    final_approved = current['delivery']['approval'] is not None
    mathematics = 'pass' if current['execution']['checkpoint'] is not None else 'pending'
    delivery = 'pass' if current['delivery']['checkpoint'] is not None else 'pending'
    return {
        'qualification': qualification,
        'mathematics': {'state': mathematics},
        'delivery': {'state': delivery},
        'authorization': {
            'state': 'complete' if route_approved and final_approved else 'partial' if route_approved else 'missing',
            'route_approved': route_approved, 'final_delivery_approved': final_approved,
        },
        'submission_ready': qualification['state'] == 'pass' and mathematics == 'pass' and delivery == 'pass' and final_approved,
        'accepted_exception_delivery_ready': qualification['state'] == 'not_certified' and mathematics == 'pass' and delivery == 'pass' and final_approved,
    }


def verify_required(document, root, required):
    current = validate(document, root)
    for gate in required:
        if gate not in base.GATE_ORDER:
            raise ValueError('unknown technical gate')
        phase = next(p for p,gates in PHASES.items() if gate in gates)
        if current[phase]['checkpoint'] is None:
            raise ValueError(f'{gate} technical check is not passed')
        if current['route']['approval'] is None:
            raise ValueError('route not approved')
        if gate == 'G6' and current['delivery']['approval'] is None:
            raise ValueError('delivery not approved; PENDING_FINAL_APPROVAL')
    return current


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('action', choices=['init','check','approve','import-approval','invalidate','verify','status','route-plan'])
    p.add_argument('--file', type=Path, required=True)
    p.add_argument('--project-root', type=Path, required=True)
    p.add_argument('--mode', choices=['evaluation_run','live_competition','release_candidate'])
    p.add_argument('--phase', choices=PHASES)
    p.add_argument('--receipt', type=Path)
    p.add_argument('--decision-id')
    p.add_argument('--approval-evidence')
    p.add_argument('--checkpoint-hash')
    p.add_argument('--approval-record', type=Path)
    p.add_argument('--expected-approval-sha256')
    p.add_argument('--preflight', type=Path)
    p.add_argument('--reason')
    p.add_argument('--snapshot',type=Path)
    p.add_argument('--require', nargs='*', choices=base.GATE_ORDER, default=[])
    a = p.parse_args()
    root = a.project_root.resolve(); path, relative = base.resolve_scoped(root, a.file)
    try:
        if a.action == 'route-plan':
            if not a.snapshot: raise ValueError('--snapshot required')
            snapshot, _ = base.resolve_scoped(root,a.snapshot)
            print(json.dumps(routing_plan(snapshot),ensure_ascii=False,indent=2))
            return 0
        if a.action == 'init':
            if path.exists(): raise ValueError('gate file exists; never overwrite or infer migration approval')
            document = initial(a.mode)
        else:
            document = base.read_json(path)
        if a.action == 'check':
            if a.phase is None or a.receipt is None: raise ValueError('--phase and --receipt required')
            receipt_path, _ = base.resolve_scoped(root, a.receipt)
            receipt = base.read_json(receipt_path)
            for raw in [receipt['report'], *receipt['artifacts'].values()]:
                target, _ = base.resolve_scoped(root, raw)
                if target == path or path.is_relative_to(target):
                    raise ValueError('gate ledger cannot bind itself or its containing directory')
            check(document, root, a.phase, receipt)
        elif a.action == 'approve':
            if not all([a.phase,a.decision_id,a.approval_evidence,a.checkpoint_hash]):
                raise ValueError('phase, decision id, approval evidence and checkpoint hash required')
            approve(document, root, a.phase, a.decision_id, a.approval_evidence, a.checkpoint_hash)
        elif a.action == 'import-approval':
            if a.approval_record is None: raise ValueError('--approval-record required')
            import_approval(document, root, a.approval_record, a.expected_approval_sha256)
        elif a.action == 'invalidate':
            state(document)  # Permit invalidation even when an input has already drifted.
            if not a.phase or not a.reason or len(a.reason.strip())<4: raise ValueError('phase and concrete reason required')
            base.append_event(document, a.phase, 'invalidated', {'reason':a.reason})
        elif a.action == 'verify':
            verify_required(document, root, a.require)
        elif a.action == 'status':
            vector = status_vector(document, root, a.preflight)
        if a.action in {'init','check','approve','import-approval','invalidate'}:
            base.write_json(path, document)
        output = {'phases': state(document), 'status_vector': vector} if a.action == 'status' else state(document)
        print(json.dumps(output, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, OSError, KeyError, TypeError) as exc:
        print(f'FAIL: {exc}'); return 1


if __name__ == '__main__':
    sys.exit(main())
