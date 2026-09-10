#!/usr/bin/env python3
"""Select competition rules by competition year, execution mode, and knowledge state."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from runtime_support import atomic_json, file_hash, scoped

ROOT = Path(__file__).resolve().parents[3]
REGISTRY = Path(__file__).resolve().parents[1] / "rules" / "contest-rules.yaml"


def resolve(*, competition: str, year: int | None, mode: str, knowledge_state: str,
            project_root: Path | None = None, official_format: Path | None = None,
            registry_path: Path = REGISTRY) -> dict:
    registry = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
    candidates = []
    for rule in registry.get("rules", []):
        if rule["competition"] not in {competition, "generic"}:
            continue
        if rule["year"] is not None and rule["year"] != year:
            continue
        if mode not in rule["modes"] or knowledge_state not in rule["knowledge_states"]:
            continue
        candidates.append(rule)
    exact = [r for r in candidates if r["competition"] == competition and r["year"] == year]
    selected = exact[0] if len(exact) == 1 else (candidates[0] if len(candidates) == 1 else None)
    if selected is None:
        raise ValueError("exactly one applicable contest rule is required")
    source = selected["source"]
    if source == "case:official_format":
        if official_format is None or project_root is None:
            raise ValueError("historical CUMCM rules require --official-format inside --project-root")
        source_path = scoped(project_root, official_format)
        source_origin = "case:official_format"
    else:
        source_path = scoped(ROOT, source)
        source_origin = source
    if not source_path.is_file():
        raise ValueError(f"rule source is missing: {source_path}")
    if selected["checker"] == "6verity/scripts/check_cumcm_2026.py" and year != 2026:
        raise ValueError("the CUMCM 2026 fixed-wording checker cannot apply to another year")
    return {
        "schema_version": "1.0", "competition": competition, "competition_year": year,
        "mode": mode, "knowledge_state": knowledge_state, "rule_id": selected["rule_id"],
        "checker": selected["checker"], "fixed_ai_wording": selected["fixed_ai_wording"],
        "body_page_limit": selected["body_page_limit"],
        "rule_registry": {"path": str(registry_path.resolve()), "sha256": file_hash(registry_path)},
        "source": {"origin": source_origin, "path": str(source_path.resolve()), "sha256": file_hash(source_path)},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--competition", required=True)
    parser.add_argument("--competition-year", type=int)
    parser.add_argument("--mode", required=True,
                        choices=["training_run", "reference_case_ingestion", "evaluation_run", "live_competition", "release_candidate"])
    parser.add_argument("--knowledge-state", choices=["unexposed", "exposed"], required=True)
    parser.add_argument("--project-root", type=Path)
    parser.add_argument("--official-format", type=Path)
    parser.add_argument("--registry", type=Path, default=REGISTRY)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = resolve(competition=args.competition, year=args.competition_year, mode=args.mode,
                     knowledge_state=args.knowledge_state, project_root=args.project_root,
                     official_format=args.official_format, registry_path=args.registry)
    if args.output:
        atomic_json(args.output, result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
