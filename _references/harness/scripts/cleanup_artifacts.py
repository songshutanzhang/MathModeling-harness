#!/usr/bin/env python3
"""Inventory and safely apply explicit, content-bound cleanup plans."""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
from pathlib import Path
import shutil

import yaml


ROOT = Path(__file__).resolve().parents[1]
POLICY = yaml.safe_load((ROOT / "artifact_lifecycle_policy.yaml").read_text(encoding="utf-8"))


def file_records(path: Path) -> list[dict]:
    if path.is_file():
        return [{"path": path.name, "bytes": path.stat().st_size, "sha256": hashlib.sha256(path.read_bytes()).hexdigest().upper()}]
    return [
        {"path": item.relative_to(path).as_posix(), "bytes": item.stat().st_size, "sha256": hashlib.sha256(item.read_bytes()).hexdigest().upper()}
        for item in sorted(p for p in path.rglob("*") if p.is_file())
    ]


def tree_hash(path: Path) -> str:
    payload = json.dumps(file_records(path), sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest().upper()


def matches(path: str, patterns: list[str]) -> bool:
    normalized = path.replace("\\", "/")
    return any(fnmatch.fnmatch(normalized, pattern) for pattern in patterns)


def validate_plan(project: Path, plan: dict) -> list[Path]:
    if plan.get("schema_version") != "1.0" or not isinstance(plan.get("targets"), list) or not plan["targets"]:
        raise ValueError("cleanup plan is incomplete")
    targets = []
    for record in plan["targets"]:
        raw = Path(record["path"])
        if raw.is_absolute() or raw.as_posix() in {".", ""}:
            raise ValueError("cleanup target must be explicit and relative")
        relative = raw.as_posix()
        if matches(relative, POLICY["protected_patterns"]):
            raise ValueError(f"protected cleanup target: {relative}")
        if not matches(relative, POLICY["allowed_ephemeral_patterns"]):
            raise ValueError(f"target is outside ephemeral policy: {relative}")
        target = (project / raw).resolve()
        target.relative_to(project)
        if target.is_symlink():
            raise ValueError(f"symlink cleanup target refused: {relative}")
        if not target.exists():
            raise FileNotFoundError(target)
        if tree_hash(target) != str(record["expected_tree_sha256"]).upper():
            raise ValueError(f"cleanup target changed: {relative}")
        if not record.get("durable_replacement_id") or not record.get("lifecycle_disposable_event_hash"):
            raise ValueError(f"cleanup target lacks promotion/disposable evidence: {relative}")
        targets.append(target)
    return targets


def inventory(project: Path) -> dict:
    rows = []
    for name in ("tmp", ".tmp", ".pytest_cache"):
        path = project / name
        if path.exists():
            records = file_records(path)
            rows.append({"path": name, "files": len(records), "bytes": sum(item["bytes"] for item in records), "tree_sha256": tree_hash(path), "action": "inventory_only_until_lifecycle_evidence"})
    cache_dirs = [path for path in project.rglob("__pycache__") if path.is_dir()]
    rows.append({"path_class": "**/__pycache__", "directories": len(cache_dirs), "action": "recomputable_but_not_auto_deleted"})
    return {"schema_version": "1.0", "project": project.name, "inventory": rows}


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    inv = sub.add_parser("inventory")
    inv.add_argument("--project-root", required=True, type=Path)
    check = sub.add_parser("validate-plan")
    check.add_argument("--project-root", required=True, type=Path)
    check.add_argument("--plan", required=True, type=Path)
    apply = sub.add_parser("apply")
    apply.add_argument("--project-root", required=True, type=Path)
    apply.add_argument("--plan", required=True, type=Path)
    apply.add_argument("--confirm-plan-sha256", required=True)
    args = parser.parse_args()
    project = args.project_root.resolve()
    if args.command == "inventory":
        print(json.dumps(inventory(project), ensure_ascii=False, indent=2))
        return 0
    plan_bytes = args.plan.read_bytes()
    plan = json.loads(plan_bytes)
    targets = validate_plan(project, plan)
    plan_hash = hashlib.sha256(plan_bytes).hexdigest().upper()
    if args.command == "validate-plan":
        print(f"PASS: targets={len(targets)} plan_sha256={plan_hash}")
        return 0
    if args.confirm_plan_sha256.upper() != plan_hash:
        raise ValueError("cleanup confirmation hash mismatch")
    removed = []
    for target in targets:
        relative = target.relative_to(project).as_posix()
        if target.is_dir():
            shutil.rmtree(target)
        else:
            target.unlink()
        removed.append(relative)
    print(json.dumps({"status": "PASS", "plan_sha256": plan_hash, "removed": removed}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
