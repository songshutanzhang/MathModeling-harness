#!/usr/bin/env python3
"""Resolve active entry dependencies and formal runtime capabilities before compute."""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import re
import shutil
import sys

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from runtime_support import atomic_json, digest, file_hash, runtime_identity, scoped

DEFAULT_ENTRIES = [f"{i}{name}/SKILL.md" for i, name in enumerate(
    ("start-mathmodel", "analysis-modeling", "coding-visual", "drawio", "writing", "verity"), 1)]
LINK_RE = re.compile(r"\[[^\]]*\]\((?!https?://|mailto:|#)([^)]+)\)")
CODE_PATH_RE = re.compile(
    r"`((?:\.\.?/|_references/|harness/|knowledge/|scripts/|references/|assets/)[^`<>*?\n]+?\.(?:md|py|mjs|json|ya?ml|docx|typ|tex))`"
)
IGNORED_PARTS = {"__pycache__", ".pytest_cache", ".git", ".venv", "tests", "meta"}


def _resolve_reference(root: Path, source: Path, raw: str) -> Path | None:
    raw = raw.strip().split("#", 1)[0].strip("<>")
    if not raw or any(mark in raw for mark in ("<", ">", "*")):
        return None
    candidates = [source.parent / raw]
    if raw.startswith("_references/"):
        candidates.insert(0, root / raw)
    elif raw.startswith(("harness/", "knowledge/")):
        candidates.insert(0, root / "_references" / raw)
    elif raw.startswith(("scripts/", "references/")):
        candidates.append(source.parent / raw)
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
            resolved.relative_to(root.resolve())
        except ValueError:
            continue
        if resolved.exists():
            return resolved
    # Return the most authoritative in-root target so the caller reports it missing.
    candidate = candidates[0].resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError:
        return None
    return candidate


def reference_closure(root: Path, entries: list[str]) -> tuple[list[Path], list[str]]:
    root = root.resolve()
    queue = [scoped(root, entry) for entry in entries]
    visited: set[Path] = set()
    missing: list[str] = []
    while queue:
        path = queue.pop(0)
        if path in visited:
            continue
        if not path.is_file():
            missing.append(path.relative_to(root).as_posix())
            continue
        visited.add(path)
        if path.suffix.lower() != ".md":
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        references = [*LINK_RE.findall(text), *CODE_PATH_RE.findall(text)]
        for raw in references:
            target = _resolve_reference(root, path, raw)
            if target is not None and target not in visited:
                queue.append(target)
    return sorted(visited), sorted(set(missing))


def shipped_manifest(root: Path, entries: list[str]) -> dict[str, str]:
    """Conservative closure: entry skill trees plus shared executable policy resources."""
    root = root.resolve()
    files: set[Path] = set()
    for raw in entries:
        entry = scoped(root, raw)
        if entry.is_file():
            files.update(p for p in entry.parent.rglob("*") if p.is_file())
    shared = root / "_references"
    for folder in (shared, shared / "scripts", shared / "harness", shared / "harness" / "scripts", shared / "harness" / "schemas",
                   shared / "harness" / "rules", shared / "knowledge" / "scripts",
                   shared / "knowledge" / "schemas"):
        if folder.is_dir():
            files.update(p for p in folder.glob("*") if p.is_file())
    result = {}
    for path in sorted(files):
        relative = path.relative_to(root)
        if any(part in IGNORED_PARTS for part in relative.parts):
            continue
        result[relative.as_posix()] = file_hash(path)
    return result


def _load_router():
    path = Path(__file__).with_name("reasoning_route.py")
    spec = importlib.util.spec_from_file_location("preflight_reasoning_route", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    return module


def inspect(repo_root: Path, active_root: Path, *, entries: list[str] | None = None,
            packages: list[str] | None = None, executables: list[str] | None = None,
            capability_snapshot: Path | None = None,
            route_requirements: list[dict] | None = None) -> dict:
    repo_root, active_root = repo_root.resolve(), active_root.resolve()
    entries = entries or DEFAULT_ENTRIES
    repo_closure, repo_missing = reference_closure(repo_root, entries)
    active_closure, active_missing = reference_closure(active_root, entries)
    manifest = shipped_manifest(repo_root, entries)
    manifest.update({path.relative_to(repo_root).as_posix(): file_hash(path) for path in repo_closure})
    manifest = dict(sorted(manifest.items()))
    drift = []
    for relative, expected in manifest.items():
        target = active_root / relative
        if not target.is_file():
            drift.append({"path": relative, "status": "missing"})
        elif file_hash(target) != expected:
            drift.append({"path": relative, "status": "drifted"})
    failures = [f"repository reference missing: {item}" for item in repo_missing]
    failures += [f"active reference missing: {item}" for item in active_missing]
    failures += [f"active dependency {item['status']}: {item['path']}" for item in drift]
    try:
        runtime = runtime_identity(packages or [])
    except ValueError as exc:
        runtime = {"error": str(exc)}
        failures.append(str(exc))
    executable_state = {}
    for name in executables or []:
        executable_state[name] = shutil.which(name)
        if executable_state[name] is None:
            failures.append(f"required executable unavailable: {name}")
    routes = []
    if route_requirements:
        if capability_snapshot is None:
            failures.append("route requirements need a capability snapshot")
        else:
            try:
                snapshot = _load_router().validate_snapshot(capability_snapshot)
                current = snapshot["current"]
                model = next(item for item in snapshot["models"] if item["model_id"] == current["model_id"])
                for requirement in route_requirements:
                    effort = requirement.get("reasoning_effort")
                    topology = requirement.get("topology", "single")
                    reasons = []
                    if effort not in model["supported_reasoning_efforts"]:
                        reasons.append(f"effort unavailable: {effort}")
                    if topology not in snapshot["supported_topologies"]:
                        reasons.append(f"topology unavailable: {topology}")
                    allowed_for_topology = snapshot.get("topology_effort_requirements", {}).get(topology)
                    if allowed_for_topology and effort not in allowed_for_topology:
                        reasons.append(f"effort {effort} is invalid for topology {topology}")
                    if requirement.get("receipt_required") and snapshot.get("supports_effective_setting_receipt") is not True:
                        reasons.append("effective-setting receipt interface unavailable")
                    item = {**requirement, "model_id": current["model_id"],
                            "status": "blocked" if reasons else "executable", "reasons": reasons}
                    routes.append(item)
                    failures.extend(f"route {requirement.get('stage', 'unknown')}: {reason}" for reason in reasons)
            except (ValueError, OSError, KeyError, StopIteration) as exc:
                failures.append(f"capability snapshot invalid: {exc}")
    return {
        "schema_version": "1.0",
        "status": "blocked" if failures else "executable",
        "entrypoints": entries,
        "repo_reference_files": [p.relative_to(repo_root).as_posix() for p in repo_closure],
        "active_reference_files": [p.relative_to(active_root).as_posix() for p in active_closure],
        "dependency_manifest_sha256": digest(manifest),
        "dependency_drift": drift,
        "runtime": runtime,
        "executables": executable_state,
        "routes": routes,
        "failures": failures,
    }


def accept_route_exception(result: dict, project_root: Path, run_id: str, receipt_path: Path) -> dict:
    from workflow_state import authorization
    from runtime_support import read_json, record
    receipt = read_json(receipt_path)
    dimensions = authorization(project_root, receipt, run_id, 'runtime_capability')
    if not receipt.get('exception'):
        raise ValueError('route exception receipt must explicitly mark exception')
    route_failures = [f for f in result['failures'] if f.startswith('route ')]
    if set(receipt.get('accepted_failures', [])) != set(route_failures):
        raise ValueError('accepted capability failures do not match current preflight')
    remaining = [f for f in result['failures'] if f not in route_failures]
    return {**result, 'status': 'blocked' if remaining else 'executable',
            'failures': remaining, 'accepted_route_failures': route_failures,
            'exception_receipt': record(project_root, receipt_path), 'run_id': run_id, **dimensions}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", required=True, type=Path)
    parser.add_argument("--active-root", required=True, type=Path)
    parser.add_argument("--entry", action="append")
    parser.add_argument("--package", action="append", default=[])
    parser.add_argument("--executable", action="append", default=[])
    parser.add_argument("--capability-snapshot", type=Path)
    parser.add_argument("--route-requirements", type=Path,
                        help="JSON array with stage/reasoning_effort/topology/receipt_required")
    parser.add_argument("--output", type=Path)
    parser.add_argument('--exception-receipt', type=Path)
    parser.add_argument('--project-root', type=Path)
    parser.add_argument('--run-id')
    args = parser.parse_args()
    requirements = json.loads(args.route_requirements.read_text(encoding="utf-8")) if args.route_requirements else None
    result = inspect(args.repo_root, args.active_root, entries=args.entry, packages=args.package,
                     executables=args.executable, capability_snapshot=args.capability_snapshot,
                     route_requirements=requirements)
    if args.exception_receipt:
        if not args.project_root or not args.run_id:
            parser.error('exception receipt requires --project-root and --run-id')
        result = accept_route_exception(result, args.project_root, args.run_id, args.exception_receipt)
    if args.output:
        atomic_json(args.output, result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "executable" else 2


if __name__ == "__main__":
    raise SystemExit(main())
