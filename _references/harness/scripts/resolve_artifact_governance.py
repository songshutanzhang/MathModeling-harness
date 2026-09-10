#!/usr/bin/env python3
"""Resolve the minimum artifact tier without allowing formal-mode downgrade."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "artifact_governance_policy.yaml"
ORDER = {"tier1": 1, "tier2": 2, "tier3": 3}


def resolve(mode: str, events: list[str], completed: int, requested: str | None) -> dict:
    policy = yaml.safe_load(POLICY_PATH.read_text(encoding="utf-8"))
    if mode not in policy["defaults"]:
        raise ValueError(f"unsupported mode: {mode}")
    tier = policy["defaults"][mode]
    reasons = [f"mode default: {mode}→{tier}"]
    unknown = sorted(set(events) - set(policy["upgrade_events"]))
    if unknown:
        raise ValueError(f"unknown upgrade events: {unknown}")
    if events and mode != 'reference_case_ingestion' and ORDER[tier] < ORDER["tier2"]:
        tier = "tier2"
        reasons.append("risk event triggered milestone audit: " + ", ".join(sorted(set(events))))
    frequency = int(policy["tier2_frequency"]["full_training_cases"])
    if mode == "training_run" and completed >= frequency and ORDER[tier] < ORDER["tier2"]:
        tier = "tier2"
        reasons.append(f"{completed} full training cases since last Tier 2 (threshold {frequency})")
    if requested:
        if requested not in ORDER:
            raise ValueError(f'unknown tier: {requested}')
        if mode == "training_run" and requested == "tier3":
            raise ValueError("training_run may upgrade to tier2; use release_candidate for tier3")
        if mode == "reference_case_ingestion" and requested != "tier1":
            raise ValueError("reference ingestion cannot become a delivery run; change execution mode")
        if ORDER[requested] < ORDER[tier]:
            raise ValueError(f"requested {requested} would downgrade required {tier}")
        tier = requested
        reasons.append(f"explicit upward request: {requested}")
    if mode in policy["never_downgrade_modes"] and tier != "tier3":
        raise ValueError(f"formal mode must remain tier3: {mode}")
    return {
        "schema_version": "1.0", "mode": mode, "resolved_tier": tier,
        "reasons": reasons,
        "requirements": policy.get("mode_requirements", {}).get(mode, policy["requirements"][tier]),
        "downgrade_allowed_within_run": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", required=True)
    parser.add_argument("--event", action="append", default=[])
    parser.add_argument("--completed-since-tier2", type=int, default=0)
    parser.add_argument("--requested-tier", choices=ORDER)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--supersedes", type=Path)
    args = parser.parse_args()
    if args.completed_since_tier2 < 0:
        parser.error("--completed-since-tier2 must be non-negative")
    result = resolve(args.mode, args.event, args.completed_since_tier2, args.requested_tier)
    if args.supersedes:
        import hashlib
        previous = json.loads(args.supersedes.read_text(encoding='utf-8'))
        if previous['mode'] != result['mode'] or ORDER[previous['resolved_tier']] > ORDER[result['resolved_tier']]:
            raise ValueError('governance supersedes must preserve mode and minimum tier')
        result['supersedes'] = {'path': args.supersedes.name, 'sha256': hashlib.sha256(args.supersedes.read_bytes()).hexdigest().upper()}
    payload = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        if args.output.exists():
            raise FileExistsError(f"governance decision is immutable: {args.output}")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
