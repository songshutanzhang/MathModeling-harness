#!/usr/bin/env python3
"""Resolve the smallest auditable Harness module set for one run.

The resolver is deliberately declarative: it chooses modules but does not run
the solver, mutate a case, or weaken artifact governance.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "harness_profile_policy.yaml"
LAYERS = {"kernel", "conditional", "contest_safeguard", "experimental"}
# Enabling a YAML flag is not an implementation. Register executable, validated
# adapters here only after the corresponding experiment contract is implemented.
EXECUTABLE_EXPERIMENTS: dict[str, Any] = {}


def load_policy(path: Path = POLICY_PATH) -> dict[str, Any]:
    policy = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(policy, dict) or policy.get("schema_version") != "1.0":
        raise ValueError("invalid harness profile policy")
    return policy


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def policy_hash(policy: dict) -> str:
    return hashlib.sha256(json.dumps(policy, sort_keys=True, ensure_ascii=False).encode()).hexdigest().upper()


def _module_active(module: dict[str, Any], *, profile: str, mode: str,
                   conditions: set[str], experimental: set[str]) -> tuple[bool, str]:
    module_id = str(module["id"])
    if module.get("experimental"):
        active = module_id in experimental
        return active, "explicit experimental opt-in" if active else "experimental opt-in absent"
    if "modes" in module:
        active = mode in set(module["modes"])
        return active, f"mode {'matched' if active else 'did not match'}: {mode}"
    if "conditions" in module:
        matched = sorted(set(module["conditions"]) & conditions)
        return bool(matched), "condition matched: " + ", ".join(matched) if matched else "trigger condition absent"
    profiles = set(module.get("profiles", []))
    active = profile in profiles
    return active, f"profile {'matched' if active else 'did not match'}: {profile}"


def resolve(*, mode: str, tier: str, conditions: list[str] | None = None,
            experimental: list[str] | None = None,
            policy: dict[str, Any] | None = None,
            governance_binding: dict[str, str] | None = None,
            supersedes: dict[str, Any] | None = None,
            condition_scopes: dict[str, list[str]] | None = None,
            condition_binding: dict | None = None,
            disable_upside_review: bool = False) -> dict[str, Any]:
    policy = policy or load_policy()
    if mode not in set(policy["allowed_modes"]):
        raise ValueError(f"unsupported execution mode: {mode}")
    if tier not in policy["tier_to_profile"]:
        raise ValueError(f"unsupported artifact tier: {tier}")
    if tier not in policy["legal_tiers_by_mode"][mode]:
        raise ValueError(f"illegal mode/tier combination: {mode}/{tier}")
    profile = policy.get("mode_profile_overrides", {}).get(mode, policy["tier_to_profile"][tier])
    condition_set = set(conditions or [])
    # Preserve baseline review behavior during architecture work; disabling it is an explicit ablation.
    if profile != 'reference' and not disable_upside_review:
        condition_set.add('upside_review_required')
    elif disable_upside_review and 'upside_review_required' in condition_set:
        raise ValueError('upside review cannot be required and disabled simultaneously')
    experimental_set = set(experimental or [])
    unknown_conditions = sorted(condition_set - set(policy["allowed_conditions"]))
    if unknown_conditions:
        raise ValueError(f"unknown profile conditions: {unknown_conditions}")
    for condition in condition_set:
        if mode in policy.get("condition_forbidden_modes", {}).get(condition, []):
            raise ValueError(f"condition forbidden in {mode}: {condition}")
    scopes = dict(condition_scopes) if condition_scopes is not None else {
        c: policy["condition_stages"][c] for c in sorted(condition_set)
    }
    if profile != 'reference' and not disable_upside_review:
        scopes.setdefault('upside_review_required', policy['condition_stages']['upside_review_required'])
    if set(scopes) != condition_set:
        raise ValueError("condition scopes must cover exactly the active conditions")
    for condition, stages in scopes.items():
        if not stages or len(stages) != len(set(stages)) or not set(stages) <= set(policy["condition_stages"][condition]):
            raise ValueError(f"invalid condition stage scope: {condition}")
    formal_modes = set(policy["formal_modes"])
    if mode in formal_modes and tier != "tier3":
        raise ValueError(f"formal mode requires tier3: {mode}")

    modules = policy.get("modules", [])
    ids = [str(item.get("id", "")) for item in modules]
    if not all(ids) or len(ids) != len(set(ids)):
        raise ValueError("module ids must be present and unique")
    experimental_ids = {str(item["id"]) for item in modules if item.get("experimental")}
    unknown_experimental = sorted(experimental_set - experimental_ids)
    if unknown_experimental:
        raise ValueError(f"unknown experimental modules: {unknown_experimental}")
    non_executable = sorted(
        experimental_set - (set(policy.get("executable_experimental_modules", [])) & set(EXECUTABLE_EXPERIMENTS))
    )
    if non_executable:
        raise ValueError(
            "experimental modules lack a registered executable contract: "
            f"{non_executable}"
        )

    active: list[dict[str, str]] = []
    inactive: list[dict[str, str]] = []
    for module in modules:
        layer = str(module.get("layer", ""))
        if layer not in LAYERS:
            raise ValueError(f"invalid layer for {module['id']}: {layer}")
        enabled, reason = _module_active(
            module, profile=profile, mode=mode, conditions=condition_set,
            experimental=experimental_set,
        )
        record = {
            "id": str(module["id"]), "layer": layer,
            "owner_stage": str(module["owner_stage"]), "reason": reason,
        }
        (active if enabled else inactive).append(record)

    active_ids = {item["id"] for item in active}
    stage_modules: dict[str, list[dict[str, str]]] = {}
    policy_ids = set(ids)
    for stage, stage_ids in policy.get("stage_modules", {}).items():
        unknown_stage_ids = set(stage_ids) - policy_ids
        if unknown_stage_ids:
            raise ValueError(f"stage {stage} references unknown modules: {sorted(unknown_stage_ids)}")
        conditional = {m['id']: m.get('conditions', []) for m in modules}
        stage_modules[stage] = [item for item in active if item["id"] in set(stage_ids)
                                and (not conditional[item['id']] or any(
                                    stage in scopes.get(c, []) for c in conditional[item['id']]))]
    covered = {m['id'] for values in stage_modules.values() for m in values}
    if covered != active_ids:
        raise ValueError(f"stage union does not equal active modules: {sorted(active_ids - covered)}")
    required_modules = set(policy["required_modules_by_profile"][profile])
    if not required_modules <= active_ids:
        raise ValueError(f"profile omitted required modules: {sorted(required_modules - active_ids)}")
    if mode in formal_modes and "human-gates" not in active_ids:
        raise ValueError("formal mode omitted human gates")
    if mode not in formal_modes and "human-gates" in active_ids:
        raise ValueError("non-formal mode must not activate human gates")
    if profile == "contest" and "contest-compliance" not in active_ids:
        raise ValueError("contest profile omitted contest compliance")

    if supersedes:
        order = {"tier1": 1, "tier2": 2, "tier3": 3}
        if supersedes.get("mode") != mode or order.get(supersedes.get("artifact_tier"), 99) > order[tier]:
            raise ValueError("superseded profile mode/tier mismatch")
        if supersedes.get('policy_sha256') != policy_hash(policy):
            raise ValueError('superseded profile policy drift; start a new candidate run')
        previous_ids = {item["id"] for item in supersedes.get("active_modules", [])}
        if not previous_ids <= active_ids:
            raise ValueError("profile upgrades must be additive within a run")
        for c, stages in supersedes.get('condition_scopes', {}).items():
            if not set(stages) <= set(scopes.get(c, [])):
                raise ValueError('profile upgrade removed frozen condition stage scope')
        revision = int(supersedes.get("profile_revision", 1)) + 1
    else:
        revision = 1

    return {
        "schema_version": "1.1",
        "policy_sha256": policy_hash(policy),
        "profile_revision": revision,
        "mode": mode,
        "artifact_tier": tier,
        "profile": profile,
        "conditions": sorted(condition_set),
        "condition_scopes": scopes,
        "disable_upside_review": disable_upside_review,
        "condition_binding": condition_binding,
        "condition_source": "bound_events" if condition_binding else "explicit_caller_input",
        "experimental_opt_ins": sorted(experimental_set),
        "governance_binding": governance_binding,
        "supersedes": (
            {"profile_revision": supersedes.get("profile_revision", 1), "sha256": supersedes["_sha256"],
             "path": supersedes.get('_path')}
            if supersedes else None
        ),
        "active_modules": active,
        "inactive_modules": inactive,
        "stage_modules": stage_modules,
        "invariants": {
            "required_modules_complete": True,
            "formal_human_gates": mode in formal_modes,
            "contest_compliance": profile == "contest",
            "profile_is_additive": True,
        },
    }


def resolve_from_governance(governance_path: Path, *, conditions: list[str] | None = None,
                            experimental: list[str] | None = None,
                            supersedes_path: Path | None = None,
                            condition_events_path: Path | None = None,
                            disable_upside_review: bool = False) -> dict[str, Any]:
    governance_path = governance_path.resolve()
    governance = json.loads(governance_path.read_text(encoding="utf-8"))
    mode = governance.get("mode") or governance.get("execution_mode")
    tier = governance.get("resolved_tier") or governance.get("artifact_tier")
    if not isinstance(mode, str) or not isinstance(tier, str):
        raise ValueError("governance decision lacks mode or resolved tier")
    previous = None
    if supersedes_path:
        supersedes_path = supersedes_path.resolve()
        previous = json.loads(supersedes_path.read_text(encoding="utf-8"))
        previous["_sha256"] = sha256(supersedes_path)
        previous['_path'] = str(supersedes_path)
        previous_binding = previous.get("governance_binding") or {}
        if previous_binding.get("sha256") != sha256(governance_path) and (
            governance.get('supersedes', {}).get('sha256') != previous_binding.get('sha256')
        ):
            raise ValueError("superseded profile governance binding mismatch")
    scopes, condition_binding = None, None
    if condition_events_path:
        import importlib.util
        spec = importlib.util.spec_from_file_location('condition_events', Path(__file__).with_name('condition_detectors.py'))
        detector = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(detector)
        events = detector.validate(condition_events_path, mode)
        if conditions:
            raise ValueError('use condition events or explicit conditions, not both')
        scopes = events['condition_scopes']
        conditions = list(scopes)
        condition_binding = {'path': str(condition_events_path.resolve()), 'sha256': sha256(condition_events_path)}
    return resolve(
        mode=mode, tier=tier, conditions=conditions, experimental=experimental,
        governance_binding={"path": str(governance_path), "sha256": sha256(governance_path)},
        supersedes=previous,
        condition_scopes=scopes, condition_binding=condition_binding,
        disable_upside_review=disable_upside_review,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--governance", required=True, type=Path)
    parser.add_argument("--condition", action="append", default=[])
    parser.add_argument("--experimental", action="append", default=[])
    parser.add_argument("--supersedes", type=Path)
    parser.add_argument("--condition-events", type=Path)
    parser.add_argument('--disable-upside-review', action='store_true', help='Explicit single-variable ablation; default preserves the baseline reviewer')
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = resolve_from_governance(
        args.governance, conditions=args.condition,
        experimental=args.experimental, supersedes_path=args.supersedes,
        condition_events_path=args.condition_events,
        disable_upside_review=args.disable_upside_review,
    )
    payload = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        if args.output.exists():
            raise FileExistsError(f"profile decision is immutable: {args.output}")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
