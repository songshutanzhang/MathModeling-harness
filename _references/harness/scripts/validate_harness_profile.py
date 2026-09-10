#!/usr/bin/env python3
"""Validate one immutable Harness profile against governance and its predecessor."""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent


def load_resolver():
    path = SCRIPT_DIR / "resolve_harness_profile.py"
    spec = importlib.util.spec_from_file_location("resolve_harness_profile", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    return module


def validate(profile_path: Path, governance_path: Path, *, required: list[str] | None = None,
             previous_path: Path | None = None, stage: str | None = None) -> dict[str, object]:
    resolver = load_resolver()
    profile_path = profile_path.resolve()
    governance_path = governance_path.resolve()
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    governance = json.loads(governance_path.read_text(encoding="utf-8"))
    mode = governance.get("mode") or governance.get("execution_mode")
    tier = governance.get("resolved_tier") or governance.get("artifact_tier")
    binding = profile.get("governance_binding") or {}
    if binding.get("sha256") != resolver.sha256(governance_path):
        raise ValueError("profile governance hash mismatch")
    if profile.get("mode") != mode or profile.get("artifact_tier") != tier:
        raise ValueError("profile mode/tier disagrees with governance")

    expected = resolver.resolve(
        mode=mode,
        tier=tier,
        conditions=profile.get("conditions", []),
        experimental=profile.get("experimental_opt_ins", []),
        governance_binding=binding,
        condition_scopes=profile.get('condition_scopes'),
        condition_binding=profile.get('condition_binding'),
        disable_upside_review=profile.get('disable_upside_review', False),
    )
    condition_binding = profile.get('condition_binding')
    if condition_binding:
        events_path = Path(condition_binding['path'])
        if resolver.sha256(events_path) != condition_binding['sha256']:
            raise ValueError('condition event hash mismatch')
        replay = resolver.resolve_from_governance(governance_path, condition_events_path=events_path,
                                                  disable_upside_review=profile.get('disable_upside_review', False))
        if replay['condition_scopes'] != profile['condition_scopes']:
            raise ValueError('condition event scope mismatch')
    for key in (
        "profile", "conditions", "experimental_opt_ins", "governance_binding",
        "active_modules", "inactive_modules", "stage_modules", "invariants",
        "schema_version", "policy_sha256", "condition_scopes", "condition_binding", "condition_source",
        "disable_upside_review",
    ):
        if profile.get(key) != expected.get(key):
            raise ValueError(f"profile field is stale or invalid: {key}")

    revision = profile.get("profile_revision")
    if not isinstance(revision, int) or revision < 1:
        raise ValueError("invalid profile revision")
    active_ids = {item["id"] for item in profile["active_modules"]}
    if stage is not None:
        if stage not in profile["stage_modules"]:
            raise ValueError(f"unknown stage: {stage}")
        available_ids = {item["id"] for item in profile["stage_modules"][stage]}
    else:
        available_ids = active_ids
    missing = sorted(set(required or []) - available_ids)
    if missing:
        raise ValueError(f"required modules are inactive: {missing}")

    if revision == 1:
        if profile.get("supersedes") is not None or previous_path is not None:
            raise ValueError("initial profile must not supersede another profile")
    else:
        if previous_path is None:
            raise ValueError("profile revision >1 requires --previous")
        previous_path = previous_path.resolve()
        previous = json.loads(previous_path.read_text(encoding="utf-8"))
        supersedes = profile.get("supersedes") or {}
        if supersedes.get("sha256") != resolver.sha256(previous_path):
            raise ValueError("profile predecessor hash mismatch")
        if supersedes.get("profile_revision") != previous.get("profile_revision"):
            raise ValueError("profile predecessor revision mismatch")
        if revision != int(previous.get("profile_revision", 0)) + 1:
            raise ValueError("profile revision is not consecutive")
        previous_ids = {item["id"] for item in previous.get("active_modules", [])}
        if not previous_ids <= active_ids:
            raise ValueError("profile upgrade removed active modules")
        if supersedes.get('path') != str(previous_path):
            raise ValueError('profile predecessor path mismatch')
        previous['_sha256'] = resolver.sha256(previous_path)
        previous['_path'] = str(previous_path)
        resolver.resolve(mode=mode, tier=tier, conditions=profile['conditions'],
                         experimental=profile['experimental_opt_ins'], supersedes=previous,
                         condition_scopes=profile['condition_scopes'],
                         disable_upside_review=profile.get('disable_upside_review', False))
        prior_binding = previous['governance_binding']
        if prior_binding['sha256'] != binding['sha256'] and governance.get('supersedes', {}).get('sha256') != prior_binding['sha256']:
            raise ValueError('governance predecessor hash mismatch')
        prior_path = (previous.get('supersedes') or {}).get('path')
        validate(previous_path, Path(prior_binding['path']),
                 previous_path=Path(prior_path) if prior_path else None)

    return {
        "profile": profile["profile"],
        "revision": revision,
        "active_modules": len(active_ids),
        "stage": stage,
        "stage_modules": len(available_ids),
        "required_modules": sorted(required or []),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", required=True, type=Path)
    parser.add_argument("--governance", required=True, type=Path)
    parser.add_argument("--require", action="append", default=[])
    parser.add_argument("--previous", type=Path)
    parser.add_argument("--stage", choices=("orchestration", "analysis", "coding", "drawing", "writing", "verification"))
    args = parser.parse_args()
    result = validate(
        args.profile, args.governance, required=args.require,
        previous_path=args.previous, stage=args.stage,
    )
    print("PASS: " + json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
