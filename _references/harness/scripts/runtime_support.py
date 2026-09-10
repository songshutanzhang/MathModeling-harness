"""Small shared primitives for immutable runtime artifacts and scoped identities."""
from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import tempfile
import subprocess
import sys
import shutil

IGNORED = {'__pycache__', '.pytest_cache', '.git', '.venv', 'node_modules'}


def _json_default(value):
    if type(value).__module__.split('.')[0] == 'numpy':
        if hasattr(value, 'tolist'):
            return value.tolist()
        if hasattr(value, 'item'):
            return value.item()
    raise TypeError(f'unsupported JSON value: {type(value).__name__}')


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'),
                      allow_nan=False, default=_json_default).encode('utf-8')


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest().upper()


def file_hash(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest().upper()


def scoped(root, raw):
    root = Path(root).resolve()
    path = Path(raw)
    path = path.resolve() if path.is_absolute() else (root / path).resolve()
    if not path.is_relative_to(root):
        raise ValueError(f'path escapes project root: {raw}')
    return path


def record(root, raw):
    path = scoped(root, raw)
    if not path.is_file():
        raise ValueError(f'missing artifact: {raw}')
    return {'path': path.relative_to(Path(root).resolve()).as_posix(), 'sha256': file_hash(path)}


def verify_record(root, value):
    actual = record(root, value['path'])
    if actual['sha256'] != str(value.get('sha256', '')).upper():
        raise ValueError(f'artifact hash mismatch: {value["path"]}')
    return scoped(root, value['path'])


def atomic_json(path, value, *, immutable=False):
    """Readers never observe partial JSON; immutable replay must have identical bytes."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = canonical(value) + b'\n'
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix='.' + path.name, suffix='.tmp', delete=False) as f:
        temporary = Path(f.name)
        f.write(payload)
        f.flush()
        os.fsync(f.fileno())
    try:
        if immutable:
            try:
                os.link(temporary, path)
            except FileExistsError:
                if path.read_bytes() != payload:
                    raise ValueError(f'immutable artifact already exists with different content: {path}')
        else:
            os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def input_manifest(root, paths):
    """Bind complete declared trees, including transitive local source files.

    Callers declare the whole source directory and dependency lock, rather than
    only the entrypoint. Outputs/state must use different directories.
    """
    records = {}
    for raw in paths:
        path = scoped(root, raw)
        if not path.exists():
            raise ValueError(f'missing input: {raw}')
        files = [path] if path.is_file() else sorted(path.rglob('*'))
        for file in files:
            if not file.is_file() or any(p in IGNORED for p in file.relative_to(root).parts):
                continue
            item = record(root, file)
            records[item['path']] = item['sha256']
    if not records:
        raise ValueError('input manifest cannot be empty')
    return dict(sorted(records.items()))


def runtime_identity(packages=()):
    versions = {}
    for package in sorted(set(packages)):
        try:
            versions[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            raise ValueError(f'required package unavailable: {package}') from None
    return {'python': platform.python_version(), 'implementation': platform.python_implementation(),
            'platform': platform.platform(), 'packages': versions}


def command_runtime(command, packages=()):
    if not command:
        return {'execution': 'external', 'effective_runtime': None}
    executable = shutil.which(command[0]) or command[0]
    path = Path(executable).resolve()
    if not path.is_file():
        return {'executable': command[0], 'available': False}
    identity = {'executable': str(path), 'sha256': file_hash(path)}
    if 'python' not in path.stem.lower():
        return {**identity, 'effective_runtime': 'non_python', 'packages': None}
    if path == Path(sys.executable).resolve():
        return {**identity, **runtime_identity(packages)}
    query = ('import json,sys,platform,importlib.metadata as m; '
             'print(json.dumps({"python":platform.python_version(),"prefix":sys.prefix,'
             '"packages":{p:m.version(p) for p in sys.argv[1:]}}))')
    result = subprocess.run([str(path), '-c', query, *packages], capture_output=True, text=True, timeout=30)
    if result.returncode:
        raise ValueError('task interpreter package preflight failed: ' + result.stderr[-1000:])
    return {**identity, **json.loads(result.stdout)}
