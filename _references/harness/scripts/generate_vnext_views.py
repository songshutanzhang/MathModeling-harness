#!/usr/bin/env python3
"""Generate registry ledgers and complete default/conditional profile matrices from machine facts."""
from __future__ import annotations
import argparse
import hashlib
import importlib.util
import itertools
import json
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT/'scripts'/f'{name}.py')
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def build_matrix() -> dict:
    resolver=load('resolve_harness_profile'); policy=resolver.load_policy()
    registry=yaml.safe_load((ROOT/'component_registry.yaml').read_text(encoding='utf-8'))
    dependencies={c['id']:c['dependencies'] for c in registry['components'] if c['disposition'] not in {'MERGE','DELETE'}}
    defaults, scenarios=[], []
    for mode, tiers in policy['legal_tiers_by_mode'].items():
        for tier in tiers:
            default=resolver.resolve(mode=mode,tier=tier)
            defaults.append(default)
            allowed=[c for c in policy['allowed_conditions'] if mode not in policy['condition_forbidden_modes'].get(c,[])]
            for bits in itertools.product((False,True),repeat=len(allowed)):
                selected=[c for c,flag in zip(allowed,bits) if flag]
                p=resolver.resolve(mode=mode,tier=tier,conditions=selected)
                active={m['id'] for m in p['active_modules']}
                for cid in active:
                    if not set(dependencies[cid]) <= active:
                        raise ValueError(f'missing active dependencies: {mode}/{tier}/{cid}')
                scenarios.append({'mode':mode,'tier':tier,'input_conditions':selected,
                                  'active_modules':sorted(active),'stage_modules':{
                                      stage:[m['id'] for m in modules] for stage,modules in p['stage_modules'].items()}})
    return {'schema_version':'1.0','policy_sha256':resolver.policy_hash(policy),
            'modules':[m['id'] for m in policy['modules']], 'defaults':defaults,'conditional_scenarios':scenarios}


def render_registry() -> str:
    path=ROOT/'component_registry.yaml'
    registry=yaml.safe_load(path.read_text(encoding='utf-8'))
    counts=load('validate_component_registry').validate(path)
    rows=['# Component Registry（机器生成）','',
          f"事实源 SHA-256：`{hashlib.sha256(path.read_bytes()).hexdigest().upper()}`。运行 generate_vnext_views.py 更新，不手工维护组件数。",'',
          f"{counts['components']} 项责任；{counts['components']-counts['merge']-counts['delete']} 可装配、{counts['merge']} 迁移记录、{counts['delete']} 删除。",'',
          '| 组件 | 分类 | 主要责任 | 触发者 | 阶段 |','| --- | --- | --- | --- | --- |']
    for c in registry['components']:
        rows.append(f"| {c['id']} | {c['disposition']} | {c['primary_responsibility']} | {c['trigger_owner']} | {', '.join(c['active_stages']) or '迁移记录'} |")
    rows += ['','## Capability / Complexity 双账本','',
             '| 组件 | floor / ceiling / confidence | context / state / coupling / maintenance | 观测证据 | 回滚 |',
             '| --- | --- | --- | --- | --- |']
    for c in registry['components']:
        cap=c['capability_ledger']; cost=c['complexity_ledger']
        rows.append('| '+ ' | '.join([c['id'],' / '.join(str(cap[k]) for k in ['floor','ceiling','evidence_confidence']),
                    ' / '.join(str(cost[k]) for k in ['context','state','coupling','maintenance']),
                    c['observed_contribution'],c['rollback_trigger']+' → '+c['rollback_steps']])+' |')
    rows += ['','成本账本的 high/medium/low 是复杂度判断（inference），实际 Token/延迟等 recurring_cost 仍为 missing；不是实测成本。']
    return '\n'.join(rows)+'\n'


def render_matrix(matrix: dict) -> str:
    rows=['# 完整 Profile 模块矩阵（机器生成）','',f"Policy `{matrix['policy_sha256']}`；{len(matrix['defaults'])} 个合法默认组合，{len(matrix['conditional_scenarios'])} 个条件组合通过活动依赖与阶段并集检查。完整条件阶段切片见 PROFILE_MODULE_MATRIX.json。",'']
    for p in matrix['defaults']:
        rows += [f"## {p['mode']} / {p['artifact_tier']} / {p['profile']}",'',
                 '| 模块 | 激活阶段（— 为未加载） |','| --- | --- |']
        for cid in matrix['modules']:
            stages=[s for s,items in p['stage_modules'].items() if cid in {i['id'] for i in items}]
            rows.append(f"| {cid} | {', '.join(stages) or '—'} |")
        rows.append('')
    rows += ['默认上限评审保留 Baseline 行为；只有显式 disable-upside-review 消融关闭。recovery/专项指南/非数据图只在指定条件及阶段激活。']
    return '\n'.join(rows)+'\n'


def main():
    p=argparse.ArgumentParser(); p.add_argument('--output-dir',type=Path,default=ROOT/'meta'); p.add_argument('--check',action='store_true'); a=p.parse_args()
    matrix=build_matrix()
    outputs={'PROFILE_MODULE_MATRIX.json':json.dumps(matrix,ensure_ascii=False,indent=2)+'\n',
             'PROFILE_MODULE_MATRIX.md':render_matrix(matrix),'COMPONENT_REGISTRY.md':render_registry()}
    for name,content in outputs.items():
        path=a.output_dir/name
        if a.check:
            if not path.is_file() or path.read_text(encoding='utf-8')!=content:
                raise ValueError(f'generated view is stale: {path}')
        else:
            path.parent.mkdir(parents=True,exist_ok=True); path.write_text(content,encoding='utf-8')
    print(json.dumps({'default_profiles':len(matrix['defaults']),'condition_combinations':len(matrix['conditional_scenarios'])}))


if __name__=='__main__':
    main()
