#!/usr/bin/env python3
"""Reuse a successful math check only while all case inputs and validator resources are unchanged.

The cache must live outside the case. Page QA/final independent rendering is never cached here.
"""
from __future__ import annotations
import argparse
import hashlib
import importlib.util
import importlib.metadata
import json
from pathlib import Path
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
from runtime_support import digest as canonical_digest, input_manifest

ROOT = Path(__file__).resolve().parents[1]
OWNERS = {'results':'results-contract','g2':'g2-tournament','g5':'g5-reliability-gate'}


def tree_hash(root: Path) -> str:
    digest=hashlib.sha256()
    for path in sorted(root.rglob('*')):
        if not path.is_file() or any(p in {'__pycache__','.pytest_cache','.git'} for p in path.relative_to(root).parts):
            continue
        if not path.resolve().is_relative_to(root.resolve()):
            raise ValueError('check input symlink escapes its root')
        digest.update(path.relative_to(root).as_posix().encode('utf-8'))
        digest.update(b'\0')
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest().upper()


def execute(check: str, project_root: Path, cache_root: Path, *, bundle: Path | None = None,
            reliability_only=False, final=False, route_ledger: Path | None = None,
            capability_snapshot: Path | None = None, reuse=True,
            input_paths: list[str] | None = None, source_paths: list[str] | None = None) -> dict:
    if check not in OWNERS:
        raise ValueError('unknown check owner')
    project_root=project_root.resolve(); cache_root=cache_root.resolve()
    if cache_root.is_relative_to(project_root):
        raise ValueError('check cache must be outside the case input tree')
    if check=='results':
        command=[sys.executable,str(ROOT.parent/'knowledge/scripts/validate_results.py'),
                 str(project_root/'results/results.json'),'--project-root',str(project_root),'--check-artifacts']
        if final: command.append('--final')
    else:
        if bundle is None or not bundle.resolve().is_relative_to(project_root):
            raise ValueError('bundle must be inside the case')
        if check == 'g5':
            spec=importlib.util.spec_from_file_location('g5_cache_bounds',ROOT/'scripts/validate_g5_bundle.py')
            g5=importlib.util.module_from_spec(spec); spec.loader.exec_module(g5)
            evidence=json.loads((bundle/'EVIDENCE_PACKAGE.json').read_text(encoding='utf-8'))
            bindings=g5._bound_artifacts(evidence)
            if bindings and not g5._infer_case_root(bundle,evidence,bindings).is_relative_to(project_root):
                raise ValueError('external evidence is outside the cache input boundary; use the uncached legacy validator')
        command=[sys.executable,str(ROOT/'scripts'/('g2_tournament.py' if check=='g2' else 'validate_g5_bundle.py'))]
        if check=='g2': command.append('validate')
        command += ['--bundle',str(bundle.resolve())]
        if check=='g5' and reliability_only: command.append('--reliability-only')
        if route_ledger or capability_snapshot:
            if not route_ledger or not capability_snapshot:
                raise ValueError('routing requires both ledger and capability snapshot')
            for path in (route_ledger,capability_snapshot):
                if not path.resolve().is_relative_to(project_root):
                    raise ValueError('routing inputs must be inside the case')
            command += ['--route-ledger',str(route_ledger.resolve()),'--capability-snapshot',str(capability_snapshot.resolve()),'--project-root',str(project_root)]
    scoped_manifest = None
    if input_paths is not None or source_paths is not None:
        scoped_manifest = input_manifest(project_root, [*(input_paths or []), *(source_paths or [])])
        input_hash = canonical_digest(scoped_manifest)
    else:
        input_hash=tree_hash(project_root)
    validator_hash=hashlib.sha256(''.join(tree_hash(ROOT.parent/p) for p in
        ['harness/scripts','harness/schemas','knowledge/scripts','knowledge/schemas','knowledge/cards']).encode()).hexdigest().upper()
    # The command binds check mode, path authority, interpreter and final/reliability flags.
    runtime=[sys.version,importlib.metadata.version('jsonschema'),importlib.metadata.version('PyYAML')]
    key=hashlib.sha256(json.dumps([command,input_hash,validator_hash,runtime]).encode()).hexdigest().upper()
    receipt_path=cache_root/(key+'.json')
    if reuse and receipt_path.is_file():
        receipt=json.loads(receipt_path.read_text(encoding='utf-8'))
        if receipt.get('key')!=key or receipt.get('returncode')!=0 or hashlib.sha256(receipt['output'].encode()).hexdigest()!=receipt.get('output_sha256'):
            raise ValueError('cached check receipt corrupted')
        return {**receipt,'reused':True,'validator_calls':0}
    started=time.perf_counter()
    process=subprocess.run(command,capture_output=True,text=True,encoding='utf-8',errors='replace')
    output=process.stdout+process.stderr
    receipt={'schema_version':'1.0','key':key,'owner':OWNERS[check],'input_sha256':input_hash,
             'input_scope':'declared_transitive_closure' if scoped_manifest is not None else 'legacy_whole_case',
             'input_manifest':scoped_manifest,
             'validator_sha256':validator_hash,'returncode':process.returncode,'output':output,
             'output_sha256':hashlib.sha256(output.encode()).hexdigest(),
             'validator_wall_clock_seconds':time.perf_counter()-started}
    post_hash = canonical_digest(input_manifest(project_root, [*(input_paths or []), *(source_paths or [])])) if scoped_manifest is not None else tree_hash(project_root)
    if post_hash!=input_hash:
        raise ValueError('case changed during validation; receipt cannot be reused')
    if process.returncode==0:
        cache_root.mkdir(parents=True,exist_ok=True)
        try:
            with receipt_path.open('x',encoding='utf-8') as f:
                json.dump(receipt,f,ensure_ascii=False,indent=2)
        except FileExistsError:
            # Another successful identical check already published its receipt.
            pass
    return {**receipt,'reused':False,'validator_calls':1}


if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--check',choices=OWNERS,required=True)
    p.add_argument('--project-root',type=Path,required=True)
    p.add_argument('--cache-root',type=Path,required=True)
    p.add_argument('--bundle',type=Path)
    p.add_argument('--reliability-only',action='store_true')
    p.add_argument('--final',action='store_true')
    p.add_argument('--route-ledger',type=Path)
    p.add_argument('--capability-snapshot',type=Path)
    p.add_argument('--no-reuse',action='store_true')
    p.add_argument('--input', action='append', dest='input_paths')
    p.add_argument('--source', action='append', dest='source_paths')
    a=p.parse_args()
    result=execute(a.check,a.project_root,a.cache_root,bundle=a.bundle,reliability_only=a.reliability_only,
                   final=a.final,route_ledger=a.route_ledger,capability_snapshot=a.capability_snapshot,reuse=not a.no_reuse,
                   input_paths=a.input_paths,source_paths=a.source_paths)
    print(json.dumps(result,ensure_ascii=False,indent=2))
    raise SystemExit(result['returncode'])
