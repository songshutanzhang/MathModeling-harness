#!/usr/bin/env python3
"""Validate component ownership, disposition and rollback completeness."""

from __future__ import annotations

import argparse
import json
import importlib.util
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator


LAYERS = {"kernel", "conditional", "contest_safeguard", "experimental"}
DISPOSITIONS = {"CORE", "GUARD", "LAZY", "MERGE", "EXPERIMENTAL", "DELETE"}
REQUIRED = {
    "id", "layer", "owner_stage", "primary_responsibility", "trigger",
    "inputs", "outputs", "dependencies", "observed_invocation_count",
    "observed_contribution", "worst_failure_prevented", "capability_ledger",
    "complexity_ledger", "disposition", "replacement", "migration",
    "rollback_trigger", "rollback_steps",
    "trigger_owner", "active_profiles", "active_stages", "owner", "recurring_cost",
}


def validate(path: Path, policy_path: Path | None = None) -> dict[str, int]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("schema_version") != "1.0":
        raise ValueError("invalid component registry")
    components = data.get("components")
    schema_path = Path(__file__).resolve().parents[1] / 'schemas/component_registry.schema.json'
    Draft202012Validator(json.loads(schema_path.read_text(encoding='utf-8'))).validate(data)
    if not isinstance(components, list) or not components:
        raise ValueError("component registry is empty")
    ids: set[str] = set()
    responsibilities: set[str] = set()
    output_owners: dict[str, str] = {}
    dispositions = {name: 0 for name in DISPOSITIONS}
    for component in components:
        missing = REQUIRED - set(component)
        if missing:
            raise ValueError(f"{component.get('id', '<unknown>')} missing fields: {sorted(missing)}")
        component_id = str(component["id"])
        if component_id in ids:
            raise ValueError(f"duplicate component id: {component_id}")
        ids.add(component_id)
        responsibility = " ".join(str(component["primary_responsibility"]).split()).casefold()
        if responsibility in responsibilities:
            raise ValueError(f"duplicate primary responsibility: {component_id}")
        responsibilities.add(responsibility)
        for output in component["outputs"]:
            output_key = " ".join(str(output).split()).casefold()
            if output_key in output_owners:
                raise ValueError(
                    f"output responsibility is duplicated: {output} owned by "
                    f"{output_owners[output_key]} and {component_id}"
                )
            output_owners[output_key] = component_id
        if component["layer"] not in LAYERS:
            raise ValueError(f"invalid layer: {component_id}")
        disposition = component["disposition"]
        if disposition not in DISPOSITIONS:
            raise ValueError(f"invalid disposition: {component_id}")
        dispositions[disposition] += 1
        if disposition in {"MERGE", "DELETE"} and not component.get("replacement"):
            raise ValueError(f"{disposition} requires a replacement: {component_id}")
        if disposition == "DELETE" and component.get("observed_invocation_count") is None and not data.get("public_distribution"):
            raise ValueError(f"DELETE requires measured invocation evidence: {component_id}")
        if component_id in component["dependencies"]:
            raise ValueError(f"self dependency: {component_id}")
    for component in components:
        unknown = set(component["dependencies"]) - ids
        if unknown:
            raise ValueError(f"unknown dependencies for {component['id']}: {sorted(unknown)}")
    if policy_path is None:
        policy_path = path.parent / "harness_profile_policy.yaml"
    policy = yaml.safe_load(policy_path.read_text(encoding="utf-8"))
    policy_components = {item["id"]: item for item in policy.get("modules", [])}
    registry_by_id = {item["id"]: item for item in components}
    missing_registry = set(policy_components) - set(registry_by_id)
    if missing_registry:
        raise ValueError(f"profile modules missing from registry: {sorted(missing_registry)}")
    for component_id, module in policy_components.items():
        registered = registry_by_id[component_id]
        if registered["disposition"] in {"MERGE", "DELETE"}:
            raise ValueError(f"inactive disposition remains in profile policy: {component_id}")
        if registered["owner_stage"] != module["owner_stage"]:
            raise ValueError(f"owner mismatch between registry and profile: {component_id}")
        stages = [s for s, ids in policy['stage_modules'].items() if component_id in ids]
        if registered['active_stages'] != stages or not stages:
            raise ValueError(f'unreachable or stale stage ownership: {component_id}')
        for condition in module.get('conditions', []):
            owner = policy['condition_owners'].get(condition)
            if owner not in policy_components or registered['trigger_owner'] != owner or owner == component_id:
                raise ValueError(f'invalid condition trigger owner: {component_id}')
    extra = {c['id'] for c in components if c['disposition'] not in {'MERGE', 'DELETE'}} - set(policy_components)
    if extra:
        raise ValueError(f'active registry components missing from policy: {sorted(extra)}')
    visiting, visited = set(), set()
    def visit(cid):
        if cid in visiting:
            raise ValueError(f'component dependency cycle: {cid}')
        if cid in visited:
            return
        visiting.add(cid)
        for dep in registry_by_id[cid]['dependencies']:
            visit(dep)
        visiting.remove(cid)
        visited.add(cid)
    for cid in ids:
        visit(cid)
    spec = importlib.util.spec_from_file_location('registry_profile_resolver', Path(__file__).with_name('resolve_harness_profile.py'))
    resolver = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(resolver)
    observed_profiles = {cid: set() for cid in ids}
    for mode, tiers in policy['legal_tiers_by_mode'].items():
        conditions = [c for c in policy['allowed_conditions'] if mode not in policy.get('condition_forbidden_modes', {}).get(c, [])]
        for tier in tiers:
            profile = resolver.resolve(mode=mode, tier=tier, conditions=conditions, policy=policy)
            active = {m['id'] for m in profile['active_modules']}
            for cid in active:
                observed_profiles[cid].add(profile['profile'])
                if not set(registry_by_id[cid]['dependencies']) <= active:
                    raise ValueError(f'active profile omitted dependencies: {cid}')
    for cid, component in registry_by_id.items():
        if set(component['active_profiles']) != observed_profiles[cid]:
            raise ValueError(f'stale active_profiles in component registry: {cid}')
    return {"components": len(components), **{key.lower(): value for key, value in sorted(dispositions.items())}}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--registry", type=Path, default=Path(__file__).resolve().parents[1] / "component_registry.yaml")
    parser.add_argument("--policy", type=Path)
    args = parser.parse_args()
    result = validate(args.registry.resolve(), args.policy.resolve() if args.policy else None)
    print("PASS: " + json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
