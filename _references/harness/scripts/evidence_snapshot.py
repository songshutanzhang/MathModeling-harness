#!/usr/bin/env python3
"""Content-addressed local evidence inputs, with explicit retention and drift semantics."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


def under(root: Path, relative: str) -> Path:
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError('snapshot source escapes root')
    return path


def put(store: Path, content: bytes) -> str:
    key = sha(content)
    target = store / 'objects' / key
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        with target.open('xb') as f:
            f.write(content)
    except FileExistsError:
        if target.read_bytes() != content:
            raise ValueError('snapshot object corrupted')
    return key


def capture(root: Path, store: Path, sources: list[dict]) -> Path:
    entries, seen = [], set()
    for source in sources:
        path = under(root, source['path'])
        relative = path.relative_to(root.resolve()).as_posix()
        if relative.casefold() in seen:
            raise ValueError('duplicate snapshot source')
        seen.add(relative.casefold())
        content = path.read_bytes()
        retention = source.get('retention', 'full')
        if retention not in {'full','excerpt','hash_only'}:
            raise ValueError('unknown retention mode')
        payload = content
        if retention == 'excerpt':
            excerpt = source.get('excerpt')
            if not isinstance(excerpt, str) or not excerpt or excerpt.encode('utf-8') not in content:
                raise ValueError('excerpt must be an exact nonempty UTF-8 source fragment')
            payload = excerpt.encode('utf-8')
        entries.append({'path': relative, 'origin': source.get('origin', 'local:' + relative),
                        'accessed_at': datetime.now(timezone.utc).isoformat(),
                        'source_sha256': sha(content), 'retention': retention,
                        'reviewer_visible': source.get('reviewer_visible', True),
                        'object_sha256': None if retention == 'hash_only' else put(store, payload)})
    if not entries:
        raise ValueError('empty evidence snapshot')
    validator = Path(__file__).with_name('validate_g5_bundle.py')
    manifest = {'schema_version':'1.0', 'binding_schema_version':'1.0',
                'validator_sha256':sha(validator.read_bytes()), 'entries':entries,
                'replayable':all(e['object_sha256'] is not None for e in entries if e['reviewer_visible'])}
    data = (json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2)+'\n').encode('utf-8')
    directory = store / 'manifests'
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / (sha(data) + '.json')
    with target.open('xb') as f:
        f.write(data)
    return target


def verify(manifest_path: Path, current_root: Path | None = None, replay_to: Path | None = None) -> dict:
    raw = manifest_path.read_bytes()
    if manifest_path.stem != sha(raw):
        raise ValueError('snapshot manifest hash mismatch')
    manifest = json.loads(raw)
    if manifest.get('schema_version') != '1.0' or not manifest.get('entries'):
        raise ValueError('invalid snapshot manifest')
    store = manifest_path.parent.parent
    statuses, retained = [], []
    for entry in manifest['entries']:
        key = entry['object_sha256']
        content = None
        if key is not None:
            if not re.fullmatch('[A-F0-9]{64}', key):
                raise ValueError('invalid snapshot object key')
            content = (store / 'objects' / key).read_bytes()
            if sha(content) != key:
                raise ValueError('snapshot object hash mismatch')
            if entry['retention'] == 'full' and key != entry['source_sha256']:
                raise ValueError('snapshot source binding mismatch')
        if current_root:
            current = under(current_root, entry['path'])
            status = 'missing' if not current.is_file() else 'unchanged' if sha(current.read_bytes()) == entry['source_sha256'] else 'drifted'
        else:
            status = 'not_checked'
        statuses.append({'path':entry['path'], 'current_source':status})
        if entry['reviewer_visible'] and content is not None:
            retained.append((entry['path'], content))
    replayable = all(e['object_sha256'] is not None for e in manifest['entries'] if e['reviewer_visible'])
    if replayable != manifest.get('replayable'):
        raise ValueError('snapshot replayability mismatch')
    if replay_to:
        if not replayable:
            raise ValueError('hash-only visible evidence cannot be replayed')
        # Validate every destination before writing any material.
        destinations = [(under(replay_to, path), content) for path, content in retained]
        if any(path.exists() for path, _ in destinations):
            raise FileExistsError('replay destination already exists')
        for path, content in destinations:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open('xb') as f:
                f.write(content)
    return {'historical_snapshot':'valid', 'replayable':replayable, 'sources':statuses,
            'scope':'reviewer inputs only; historical validity does not approve current results'}


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('action', choices=['capture','verify'])
    p.add_argument('--root', type=Path)
    p.add_argument('--store', type=Path)
    p.add_argument('--sources', type=Path, help='JSON array of path/origin/retention/reviewer_visible entries')
    p.add_argument('--manifest', type=Path)
    p.add_argument('--replay-to', type=Path)
    a = p.parse_args()
    if a.action == 'capture':
        if not all((a.root, a.store, a.sources)):
            p.error('capture needs --root --store --sources')
        print(capture(a.root.resolve(), a.store, json.loads(a.sources.read_text(encoding='utf-8'))))
    else:
        if not a.manifest:
            p.error('verify needs --manifest')
        print(json.dumps(verify(a.manifest, a.root, a.replay_to), ensure_ascii=False))
