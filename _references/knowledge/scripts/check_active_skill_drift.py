#!/usr/bin/env python3
"""Fail closed when the active Codex math-model skills drift from the repository."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import tempfile


DEFAULT_SKILLS = [
    "1start-mathmodel", "2analysis-modeling", "3coding-visual",
    "4drawio", "5writing", "6verity",
]
REQUIRED_TOKENS = {
    "1start-mathmodel": [
        "reference_case_ingestion",
        "training_run",
        "evaluation_run",
        "live_competition",
        "不创建 `HUMAN_GATES.json`",
        "MODEL_REASONING_ROUTER.md",
        "MODEL_CAPABILITY_SNAPSHOT.json",
        "REASONING_ROUTE_LEDGER.jsonl",
        "reasoning_route.py",
        "ARTIFACT_GOVERNANCE.md",
        "G2 候选",
        "G5 决策",
        "dependency_preflight.py",
        "run_orchestrator.py",
        "contest_rules.py",
    ],
    "2analysis-modeling": [
        "reference_case_ingestion",
        "training_run",
        "evaluation_run",
        "live_competition",
        "不运行人工门禁",
        "MODEL_REASONING_ROUTER.md",
        "MODEL_CAPABILITY_SNAPSHOT.json",
        "reasoning_route.py",
        "ROUTING_BINDING.json",
        "G2_TOURNAMENT_SPEC.md",
        "g2_tournament.py",
        "Competition Upside",
        "candidate_registry.py",
        "math_search_tools.py",
    ],
    "3coding-visual": [
        "training_run", "G5_BLIND_REVIEW_SPEC.md", "Failure Hunter",
        "Ceiling Reviewer", "validate_g5_bundle.py", "LIGHTWEIGHT_MANIFEST.yaml",
        "MODEL_CAPABILITY_SNAPSHOT.json", "ROUTING_BINDING.json",
        "run_orchestrator.py", "candidate_registry.py", "g5_disposition.py",
    ],
    "4drawio": ["artifact tier", "training_run", "G5 双审", "reasoning_route.py"],
    "5writing": ["Tier 1", "Semantic Writer", "paper/paper.md", "validate_lightweight_manifest.py", "route task", "CONTEST_RULES.json"],
    "6verity": ["Tier 1", "Tier 2", "Tier 3", "g5-reliability-gate", "TRAINING_VERIFY_REPORT.md", "topology receipt", "final_review_reserve_seconds", "CONTEST_RULES.json"],
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        mode="wb", delete=False, dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
    )
    temporary = Path(handle.name)
    try:
        with handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def inspect(repo_root: Path, active_root: Path, skills: list[str]) -> dict:
    records = []
    for name in skills:
        repository = (repo_root / name / "SKILL.md").resolve()
        active = (active_root / name / "SKILL.md").resolve()
        if not repository.is_file():
            raise FileNotFoundError(f"repository skill missing: {repository}")
        if not active.is_file():
            raise FileNotFoundError(f"active skill missing: {active}")
        repository_hash = sha256_file(repository)
        active_hash = sha256_file(active)
        active_text = active.read_text(encoding="utf-8")
        # A matching entrypoint cannot certify stale/missing condition references or executable resources.
        resources = []
        for source in sorted(repository.parent.rglob('*')):
            relative = source.relative_to(repository.parent)
            if not source.is_file() or source == repository or any(part in {'__pycache__','.pytest_cache','tests','.git'} for part in relative.parts):
                continue
            target = active.parent / relative
            resources.append({'path': relative.as_posix(), 'pass': target.is_file() and sha256_file(source) == sha256_file(target)})
        missing_tokens = [
            token for token in REQUIRED_TOKENS.get(name, []) if token not in active_text
        ]
        records.append(
            {
                "name": name,
                "repository_sha256": repository_hash,
                "active_sha256": active_hash,
                "exact_match": repository_hash == active_hash,
                "missing_policy_tokens": missing_tokens,
                "resources": resources,
                "pass": repository_hash == active_hash and not missing_tokens and all(r['pass'] for r in resources),
            }
        )
    shared = []
    shared_root = repo_root / '_references'
    candidates = list(shared_root.glob('*.md'))
    for folder in ('scripts','harness/scripts','harness/schemas','harness/rules','knowledge/scripts','knowledge/schemas'):
        candidates.extend(p for p in (shared_root/folder).glob('*') if p.is_file())
    candidates.extend((shared_root/'harness').glob('*.yaml'))
    candidates.extend((shared_root/'harness').glob('*.md'))
    for source in sorted(candidates):
        relative = source.relative_to(repo_root)
        target = active_root / relative
        shared.append({'path':relative.as_posix(), 'pass':target.is_file() and sha256_file(source)==sha256_file(target)})
    return {
        "schema_version": "1.0",
        "policy": "active_skills_must_exactly_match_repository",
        "skills": records,
        "shared_resources": shared,
        "pass": all(record["pass"] for record in records) and all(r['pass'] for r in shared),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", required=True)
    parser.add_argument("--active-root", required=True)
    parser.add_argument("--skill", action="append")
    parser.add_argument("--json-output")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = inspect(
        Path(args.repo_root).resolve(),
        Path(args.active_root).resolve(),
        args.skill or DEFAULT_SKILLS,
    )
    payload = (json.dumps(result, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    if args.json_output:
        atomic_write(Path(args.json_output).resolve(), payload)
    print(payload.decode("utf-8"), end="")
    return 0 if result["pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
