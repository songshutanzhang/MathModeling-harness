#!/usr/bin/env python3
"""Validate a Tier-1 semantic artifact manifest and its bound files."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator, FormatChecker


ROOT = Path(__file__).resolve().parents[1]
SCHEMA = json.loads((ROOT / "schemas" / "lightweight_manifest.schema.json").read_text(encoding="utf-8"))


def tree_hash(path: Path) -> str:
    if path.is_file():
        return hashlib.sha256(path.read_bytes()).hexdigest().upper()
    records = []
    for item in sorted(p for p in path.rglob("*") if p.is_file()):
        records.append({"path": item.relative_to(path).as_posix(), "sha256": hashlib.sha256(item.read_bytes()).hexdigest().upper()})
    return hashlib.sha256(json.dumps(records, sort_keys=True, separators=(",", ":")).encode()).hexdigest().upper()


def validate(manifest_path: Path, project_root: Path) -> dict:
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    errors = list(Draft202012Validator(SCHEMA, format_checker=FormatChecker()).iter_errors(manifest))
    if errors:
        raise ValueError(errors[0].message)
    project = project_root.resolve()
    bound_artifacts = ["result", "paper", "figures"]
    if "harness_profile" in manifest:
        bound_artifacts.append("harness_profile")
    for name in bound_artifacts:
        record = manifest[name]
        raw = Path(record["path"])
        if raw.is_absolute():
            raise ValueError(f"absolute artifact path forbidden: {name}")
        target = (project / raw).resolve()
        target.relative_to(project)
        if not target.exists():
            raise FileNotFoundError(target)
        if tree_hash(target) != record["sha256"].upper():
            raise ValueError(f"artifact hash mismatch: {name}")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--project-root", required=True, type=Path)
    args = parser.parse_args()
    manifest = validate(args.manifest, args.project_root)
    print(f"PASS: {manifest['run_id']} tier1 semantic artifacts are bound")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
