"""Seal a reproducible skill release and launch its runner with a pinned interpreter."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys

from runtime_support import atomic_json, file_hash, read_json, scoped, command_runtime, digest
from dependency_preflight import shipped_manifest, reference_closure, DEFAULT_ENTRIES
from workflow_state import state_path


def seal(source: Path, output: Path, python: Path, packages: list[str]) -> dict:
    source, output, python = source.resolve(), output.resolve(), python.resolve()
    if output.exists():
        raise ValueError('release directory already exists; sealed releases are not overwritten')
    runtime = command_runtime([str(python)], packages)
    if not runtime.get('python'):
        raise ValueError('release requires an available Python interpreter')
    manifest = shipped_manifest(source, DEFAULT_ENTRIES)
    closure, missing = reference_closure(source, DEFAULT_ENTRIES)
    if missing:
        raise ValueError(f'missing release references: {missing}')
    manifest.update({p.relative_to(source).as_posix(): file_hash(p) for p in closure})
    for relative, expected in manifest.items():
        target = scoped(output, relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(scoped(source, relative), target)
        if file_hash(target) != expected:
            raise ValueError('source changed during release copy')
    lock = {'schema_version': '1.0', 'release_id': output.name, 'manifest': manifest,
            'manifest_sha256': digest(manifest), 'python': str(python), 'packages': packages,
            'runtime': runtime, 'scope': 'skill code and pinned numerical runtime; external services not bundled'}
    atomic_json(output / 'RELEASE_LOCK.json', lock, immutable=True)
    return verify(output)


def verify(release: Path) -> dict:
    release = release.resolve()
    lock = read_json(release / 'RELEASE_LOCK.json')
    if digest(lock['manifest']) != lock['manifest_sha256']:
        raise ValueError('release manifest identity mismatch')
    drift = [p for p, expected in lock['manifest'].items()
             if not scoped(release, p).is_file() or file_hash(scoped(release, p)) != expected]
    if drift:
        raise ValueError(f'sealed release drift: {drift}')
    if command_runtime([lock['python']], lock['packages']) != lock['runtime']:
        raise ValueError('pinned runtime drift; restore the recorded environment before running')
    return {'status': 'verified', 'release_id': lock['release_id'], 'files': len(lock['manifest']),
            'manifest_sha256': lock['manifest_sha256'], 'python': lock['python']}


def launch(release: Path, arguments: list[str]) -> int:
    checked = verify(release)
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument('--project-root', required=True, type=Path)
    parser.add_argument('--state-dir', type=Path, default=Path('.runtime'))
    options, remaining = parser.parse_known_args(arguments)
    root = options.project_root.resolve()
    if root.is_relative_to(release.resolve()):
        raise ValueError('case workspace must be outside the sealed release')
    state = state_path(root, options.state_dir)
    runner = release.resolve() / '_references/harness/scripts/run_orchestrator.py'
    print(json.dumps({**checked, 'project_root': str(root), 'state_dir': str(state)}, ensure_ascii=False), flush=True)
    return subprocess.run([checked['python'], str(runner), *remaining,
                           '--project-root', str(root), '--state-dir', str(state)], check=False).returncode


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    make = sub.add_parser('seal')
    make.add_argument('--source-root', required=True, type=Path)
    make.add_argument('--output-dir', required=True, type=Path)
    make.add_argument('--python', type=Path, default=Path(sys.executable))
    make.add_argument('--package', action='append', default=[])
    check = sub.add_parser('check'); check.add_argument('--release', required=True, type=Path)
    run = sub.add_parser('run'); run.add_argument('--release', required=True, type=Path)
    run.add_argument('arguments', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if args.action == 'seal':
        result = seal(args.source_root, args.output_dir, args.python, args.package)
    elif args.action == 'check':
        result = verify(args.release)
    else:
        return launch(args.release, args.arguments[1:] if args.arguments[:1] == ['--'] else args.arguments)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
