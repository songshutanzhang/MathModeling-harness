#!/usr/bin/env python3
"""Freeze, verify, and finalize Word-first writing loops."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET


SCHEMA_VERSION = "1.0"
LOOP_RE = re.compile(r"^loop-(\d{3})$")
PLACEHOLDER_RE = re.compile(r"\b(?:TODO|TBD)\b|待补充|待填写", re.I)
WORD_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
DC_NS = "http://purl.org/dc/elements/1.1/"
CP_NS = "http://schemas.openxmlformats.org/package/2006/metadata/core-properties"


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def resolve_scoped(root: Path, raw: str | Path) -> tuple[Path, str]:
    project_root = root.resolve()
    candidate = Path(raw)
    resolved = candidate.resolve() if candidate.is_absolute() else (project_root / candidate).resolve()
    try:
        relative = resolved.relative_to(project_root)
    except ValueError as exc:
        raise ValueError(f"path must stay inside project root: {resolved}") from exc
    return resolved, relative.as_posix()


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def read_registry(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"loop registry does not exist: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"loop registry is invalid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError("loop registry root must be an object")
    return value


def validate_docx(path: Path) -> list[str]:
    errors: list[str] = []
    if path.suffix.lower() != ".docx":
        return [f"Word artifact must use .docx: {path}"]
    try:
        with zipfile.ZipFile(path) as archive:
            names = set(archive.namelist())
            for required in ("[Content_Types].xml", "word/document.xml"):
                if required not in names:
                    errors.append(f"DOCX is missing {required}: {path}")
            if "word/document.xml" in names:
                try:
                    ET.fromstring(archive.read("word/document.xml"))
                except ET.ParseError:
                    errors.append(f"DOCX document.xml is invalid XML: {path}")
    except (zipfile.BadZipFile, OSError):
        errors.append(f"file is not a valid DOCX package: {path}")
    return errors


def validate_pdf(path: Path) -> list[str]:
    if path.suffix.lower() != ".pdf":
        return [f"render snapshot must use .pdf: {path}"]
    try:
        with path.open("rb") as stream:
            if stream.read(5) != b"%PDF-":
                return [f"file is not a valid PDF: {path}"]
    except OSError as exc:
        return [f"cannot read PDF {path}: {exc}"]
    return []


def final_docx_hygiene(path: Path) -> list[str]:
    errors = validate_docx(path)
    if errors:
        return errors
    with zipfile.ZipFile(path) as archive:
        names = set(archive.namelist())
        if "word/comments.xml" in names:
            errors.append("final DOCX still contains Word comments")
        if "docProps/custom.xml" in names:
            errors.append("final DOCX still contains custom properties")
        for name in names:
            if not name.startswith("word/") or not name.endswith(".xml"):
                continue
            data = archive.read(name)
            if re.search(rb"<w:(?:ins|del)(?:\s|>)", data):
                errors.append(f"final DOCX still contains tracked changes: {name}")
            if b"w:documentProtection" in data:
                errors.append("final DOCX must remain editable and cannot be protected")
            if re.search(rb"\bw:rsid[A-Za-z]*=", data):
                errors.append(f"final DOCX still contains revision session identifiers: {name}")
        if "docProps/core.xml" in names:
            try:
                core = ET.fromstring(archive.read("docProps/core.xml"))
                creator = core.find(f"{{{DC_NS}}}creator")
                modified_by = core.find(f"{{{CP_NS}}}lastModifiedBy")
                if creator is not None and (creator.text or "").strip():
                    errors.append("final DOCX creator metadata is not empty")
                if modified_by is not None and (modified_by.text or "").strip():
                    errors.append("final DOCX lastModifiedBy metadata is not empty")
            except ET.ParseError:
                errors.append("final DOCX core properties are invalid XML")
    return list(dict.fromkeys(errors))


def page_images(qa_dir: Path) -> list[Path]:
    candidates = [item for item in qa_dir.glob("page-*.png") if item.is_file()]

    def key(path: Path) -> tuple[int, str]:
        match = re.search(r"(\d+)$", path.stem)
        return (int(match.group(1)) if match else 10**9, path.name)

    return sorted(candidates, key=key)


def command_render(args: argparse.Namespace) -> None:
    docx_path, docx_relative = resolve_scoped(args.project_root, args.docx)
    output_dir, _ = resolve_scoped(args.project_root, args.output_dir)
    renderer = Path(args.renderer).resolve()
    fail(validate_docx(docx_path))
    if not renderer.is_file():
        fail([f"documents renderer does not exist: {renderer}"])
    if output_dir.exists() and any(output_dir.iterdir()):
        fail([f"render output directory must be empty: {output_dir}"])
    output_dir.mkdir(parents=True, exist_ok=True)
    before_hash = sha256_file(docx_path)
    result = subprocess.run(
        [
            sys.executable,
            str(renderer),
            str(docx_path),
            "--output_dir",
            str(output_dir),
            "--emit_pdf",
        ],
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        if result.stdout:
            print(result.stdout)
        if result.stderr:
            print(result.stderr)
        fail([f"DOCX renderer failed with exit code {result.returncode}"])
    after_hash = sha256_file(docx_path)
    if before_hash != after_hash:
        fail(["working DOCX changed while it was being rendered"])
    pdf_path = output_dir / f"{docx_path.stem}.pdf"
    images = page_images(output_dir)
    errors = validate_pdf(pdf_path)
    if not images:
        errors.append("renderer did not create any page PNG files")
    fail(errors)
    receipt = {
        "schema_version": SCHEMA_VERSION,
        "rendered_at": utc_now(),
        "renderer": str(renderer),
        "docx": {"path": docx_relative, "sha256": before_hash},
        "pdf": {
            "path": pdf_path.relative_to(args.project_root).as_posix(),
            "sha256": sha256_file(pdf_path),
        },
        "page_count": len(images),
        "page_images": [
            {
                "path": image.relative_to(args.project_root).as_posix(),
                "sha256": sha256_file(image),
            }
            for image in images
        ],
    }
    receipt_path = output_dir / "RENDER_RECEIPT.json"
    atomic_json(receipt_path, receipt)
    print(f"RESULT: PASS rendered {len(images)} page(s)")
    print(f"RECEIPT: {receipt_path}")


def validate_registry_shape(registry: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if registry.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"unsupported schema_version: {registry.get('schema_version')}")
    loops = registry.get("loops")
    if not isinstance(loops, list):
        return errors + ["registry loops must be a list"]
    seen: set[str] = set()
    expected = 1
    for entry in loops:
        if not isinstance(entry, dict):
            errors.append("registry loop entry must be an object")
            continue
        loop_id = entry.get("loop_id")
        match = LOOP_RE.match(loop_id or "")
        if not match:
            errors.append(f"invalid loop_id in registry: {loop_id}")
            continue
        if loop_id in seen:
            errors.append(f"duplicate loop_id: {loop_id}")
        seen.add(loop_id)
        number = int(match.group(1))
        if number != expected:
            errors.append(f"loop sequence is not continuous at {loop_id}; expected loop-{expected:03d}")
        expected += 1
    return errors


def fail(errors: list[str]) -> None:
    if not errors:
        return
    for error in errors:
        print(f"FAIL: {error}")
    raise SystemExit(1)


def command_init(args: argparse.Namespace) -> None:
    registry_path, source_relative = resolve_scoped(args.project_root, args.registry)
    if registry_path.exists():
        fail([f"refusing to overwrite existing loop registry: {registry_path}"])
    _, working_relative = resolve_scoped(args.project_root, args.working_docx)
    registry = {
        "schema_version": SCHEMA_VERSION,
        "created_at": utc_now(),
        "updated_at": utc_now(),
        "source_of_truth": working_relative,
        "registry_path": source_relative,
        "loops": [],
    }
    atomic_json(registry_path, registry)
    print(f"PASS: initialized {registry_path}")


def build_manifest(
    args: argparse.Namespace,
    docx_target: Path,
    pdf_target: Path,
    qa_targets: list[Path],
    strategy_target: Path,
    changes_target: Path,
    receipt_target: Path,
    page_count: int,
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "loop_id": args.loop_id,
        "frozen_at": utc_now(),
        "status": "qa_passed",
        "source_of_truth": "docx",
        "all_pages_reviewed": True,
        "page_count": page_count,
        "docx": {
            "path": docx_target.relative_to(args.project_root).as_posix(),
            "sha256": sha256_file(docx_target),
        },
        "pdf": {
            "path": pdf_target.relative_to(args.project_root).as_posix(),
            "sha256": sha256_file(pdf_target),
            "purpose": "derived visual QA snapshot",
        },
        "page_images": [
            {
                "path": image.relative_to(args.project_root).as_posix(),
                "sha256": sha256_file(image),
            }
            for image in qa_targets
        ],
        "strategy_context": {
            "path": strategy_target.relative_to(args.project_root).as_posix(),
            "sha256": sha256_file(strategy_target),
        },
        "changeset": {
            "path": changes_target.relative_to(args.project_root).as_posix(),
            "sha256": sha256_file(changes_target),
        },
        "render_receipt": {
            "path": receipt_target.relative_to(args.project_root).as_posix(),
            "sha256": sha256_file(receipt_target),
        },
    }


def delta_qa_plan(project_root: Path, previous_path: Path, receipt_path: Path) -> dict:
    previous_path, _ = resolve_scoped(project_root, previous_path)
    receipt_path, _ = resolve_scoped(project_root, receipt_path)
    previous = read_registry(previous_path)
    current = read_registry(receipt_path)
    if previous.get('status') != 'qa_passed' or previous.get('all_pages_reviewed') is not True:
        raise ValueError('delta QA can only reuse a previously passed frozen loop')
    old, new = previous['page_images'], current['page_images']
    for item in [*old, *new]:
        path, _ = resolve_scoped(project_root, item['path'])
        if sha256_file(path) != item['sha256']:
            raise ValueError('delta QA page image drift')
    reused = [i + 1 for i, item in enumerate(new) if i < len(old) and item['sha256'] == old[i]['sha256']]
    changed = [i + 1 for i in range(len(new)) if i + 1 not in reused]
    return {'schema_version': '1.0', 'previous_manifest_sha256': sha256_file(previous_path),
            'render_receipt_sha256': sha256_file(receipt_path), 'reused_pages': reused,
            'must_review_pages': changed, 'removed_pages': list(range(len(new) + 1, len(old) + 1)),
            'status': 'review_required', 'page_count': len(new)}


def verify_delta_qa(project_root: Path, delta_path: Path, receipt_path: Path) -> dict:
    delta_path, _ = resolve_scoped(project_root, delta_path)
    review = read_registry(delta_path)
    plan = delta_qa_plan(project_root, Path(review['previous_manifest']), receipt_path)
    for key in ('previous_manifest_sha256', 'render_receipt_sha256', 'reused_pages', 'must_review_pages'):
        if review.get(key) != plan[key]:
            raise ValueError(f'delta QA binding mismatch: {key}')
    if review.get('status') != 'passed' or sorted(review.get('reviewed_changed_pages', [])) != plan['must_review_pages']:
        raise ValueError('all changed pages require explicit completed visual review')
    if plan['removed_pages'] and review.get('removed_pages_checked') is not True:
        raise ValueError('removed pages need a content completeness check')
    return {**plan, 'status': 'passed', 'review_sha256': sha256_file(delta_path)}


def command_delta_plan(args: argparse.Namespace) -> None:
    result = delta_qa_plan(args.project_root, Path(args.previous_manifest), Path(args.render_receipt))
    result['previous_manifest'] = args.previous_manifest
    output, _ = resolve_scoped(args.project_root, args.output)
    atomic_json(output, result)
    print(json.dumps(result, ensure_ascii=False))


def command_snapshot(args: argparse.Namespace) -> None:
    registry_path, _ = resolve_scoped(args.project_root, args.registry)
    registry = read_registry(registry_path)
    fail(validate_registry_shape(registry))
    match = LOOP_RE.match(args.loop_id)
    if not match:
        fail([f"loop id must match loop-NNN: {args.loop_id}"])
    expected = len(registry["loops"]) + 1
    if int(match.group(1)) != expected:
        fail([f"next loop must be loop-{expected:03d}"])

    docx_source, docx_relative = resolve_scoped(args.project_root, args.docx)
    receipt_source, _ = resolve_scoped(args.project_root, args.render_receipt)
    strategy_source, _ = resolve_scoped(args.project_root, args.strategy_context)
    changes_source, _ = resolve_scoped(args.project_root, args.changeset)
    errors = validate_docx(docx_source)
    delta = None
    if getattr(args, 'delta_qa_receipt', None):
        delta = verify_delta_qa(args.project_root, Path(args.delta_qa_receipt), receipt_source)
    if not args.all_pages_reviewed and delta is None:
        errors.append("snapshot requires explicit --all-pages-reviewed confirmation")
    if not receipt_source.is_file():
        errors.append(f"render receipt does not exist: {receipt_source}")
        receipt: dict[str, Any] = {}
    else:
        try:
            receipt = json.loads(receipt_source.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            receipt = {}
            errors.append(f"render receipt is invalid JSON: {receipt_source}")
    if receipt.get("schema_version") != SCHEMA_VERSION:
        errors.append("render receipt schema version is invalid")
    receipt_docx = receipt.get("docx", {})
    if receipt_docx.get("path") != docx_relative:
        errors.append("render receipt does not refer to the current working DOCX")
    if docx_source.exists() and receipt_docx.get("sha256") != sha256_file(docx_source):
        errors.append("working DOCX changed after the recorded render")

    pdf_source, _ = resolve_scoped(args.project_root, receipt.get("pdf", {}).get("path", ""))
    errors.extend(validate_pdf(pdf_source) if pdf_source.exists() else [f"rendered PDF is missing: {pdf_source}"])
    if pdf_source.exists() and receipt.get("pdf", {}).get("sha256") != sha256_file(pdf_source):
        errors.append("rendered PDF hash does not match render receipt")
    images: list[Path] = []
    for record in receipt.get("page_images", []):
        image, _ = resolve_scoped(args.project_root, record.get("path", ""))
        if not image.is_file():
            errors.append(f"rendered page image is missing: {image}")
        elif image.suffix.lower() != ".png":
            errors.append(f"rendered page image must be PNG: {image}")
        elif record.get("sha256") != sha256_file(image):
            errors.append(f"rendered page image hash does not match receipt: {image}")
        else:
            images.append(image)
    page_count = receipt.get("page_count")
    if not isinstance(page_count, int) or page_count <= 0:
        errors.append("render receipt page_count must be positive")
    elif len(images) != page_count:
        errors.append(
            f"render receipt page image count {len(images)} does not match page_count {page_count}"
        )

    for label, path in (("strategy context", strategy_source), ("changeset", changes_source)):
        if not path.exists():
            errors.append(f"{label} does not exist: {path}")
        elif path.is_file() and label in {"strategy context", "changeset"}:
            text = path.read_text(encoding="utf-8", errors="replace")
            if PLACEHOLDER_RE.search(text):
                errors.append(f"{label} still contains placeholders: {path}")
    fail(errors)

    revision_dir = args.project_root / "paper" / "revisions" / args.loop_id
    qa_dir = args.project_root / "paper" / "qa" / args.loop_id
    if revision_dir.exists() or qa_dir.exists():
        fail([f"refusing to overwrite frozen loop: {args.loop_id}"])
    revision_dir.mkdir(parents=True)
    qa_dir.mkdir(parents=True)
    docx_target = revision_dir / f"论文_{args.loop_id}.docx"
    pdf_target = qa_dir / f"论文_{args.loop_id}.pdf"
    strategy_target = revision_dir / "STRATEGY_CONTEXT.md"
    changes_target = revision_dir / "CHANGESET.md"
    receipt_target = revision_dir / "RENDER_RECEIPT.json"
    shutil.copy2(docx_source, docx_target)
    shutil.copy2(pdf_source, pdf_target)
    shutil.copy2(strategy_source, strategy_target)
    shutil.copy2(changes_source, changes_target)
    shutil.copy2(receipt_source, receipt_target)
    qa_targets: list[Path] = []
    for image in images:
        target = qa_dir / image.name
        shutil.copy2(image, target)
        qa_targets.append(target)

    manifest = build_manifest(
        args,
        docx_target,
        pdf_target,
        qa_targets,
        strategy_target,
        changes_target,
        receipt_target,
        page_count,
    )
    if delta is not None:
        delta_source, _ = resolve_scoped(args.project_root, args.delta_qa_receipt)
        delta_target = revision_dir / 'DELTA_QA.json'
        shutil.copy2(delta_source, delta_target)
        manifest['delta_qa'] = {**delta, 'receipt': {
            'path': delta_target.relative_to(args.project_root).as_posix(), 'sha256': sha256_file(delta_target)}}
    manifest_path = revision_dir / "LOOP_MANIFEST.json"
    atomic_json(manifest_path, manifest)
    registry["loops"].append(
        {
            "loop_id": args.loop_id,
            "status": "qa_passed",
            "manifest": manifest_path.relative_to(args.project_root).as_posix(),
            "manifest_sha256": sha256_file(manifest_path),
        }
    )
    registry["updated_at"] = utc_now()
    atomic_json(registry_path, registry)
    print(f"PASS: froze {args.loop_id}")
    print(f"DOCX: {docx_target}")
    print(f"PDF_QA: {pdf_target}")


def resolve_loop_entry(registry: dict[str, Any], loop_id: str) -> dict[str, Any]:
    loops = registry.get("loops", [])
    if not loops:
        raise ValueError("no writing loops have been frozen")
    selected = loops[-1] if loop_id == "latest" else next(
        (entry for entry in loops if entry.get("loop_id") == loop_id), None
    )
    if selected is None:
        raise ValueError(f"loop not found: {loop_id}")
    return selected


def verify_loop(root: Path, entry: dict[str, Any], final_ready: bool) -> list[str]:
    errors: list[str] = []
    manifest_path, _ = resolve_scoped(root, entry.get("manifest", ""))
    if not manifest_path.is_file():
        return [f"loop manifest is missing: {manifest_path}"]
    if sha256_file(manifest_path) != entry.get("manifest_sha256"):
        errors.append(f"loop manifest hash changed: {manifest_path}")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return errors + [f"loop manifest is invalid JSON: {manifest_path}"]
    if manifest.get("status") != "qa_passed" or manifest.get("all_pages_reviewed") is not True:
        errors.append(f"loop did not pass full-page visual QA: {entry.get('loop_id')}")
    records: list[tuple[str, dict[str, Any]]] = [
        ("DOCX", manifest.get("docx", {})),
        ("PDF", manifest.get("pdf", {})),
        ("strategy context", manifest.get("strategy_context", {})),
        ("changeset", manifest.get("changeset", {})),
        ("render receipt", manifest.get("render_receipt", {})),
    ]
    if manifest.get('delta_qa'):
        records.append(('delta QA receipt', manifest['delta_qa']['receipt']))
    for label, record in records:
        path, _ = resolve_scoped(root, record.get("path", ""))
        if not path.is_file():
            errors.append(f"{label} is missing: {path}")
        elif sha256_file(path) != record.get("sha256"):
            errors.append(f"{label} hash changed: {path}")
    docx_path, _ = resolve_scoped(root, manifest.get("docx", {}).get("path", ""))
    pdf_path, _ = resolve_scoped(root, manifest.get("pdf", {}).get("path", ""))
    if docx_path.exists():
        errors.extend(final_docx_hygiene(docx_path) if final_ready else validate_docx(docx_path))
    if pdf_path.exists():
        errors.extend(validate_pdf(pdf_path))
    receipt_path, _ = resolve_scoped(
        root, manifest.get("render_receipt", {}).get("path", "")
    )
    if receipt_path.is_file():
        try:
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            if receipt.get("docx", {}).get("sha256") != manifest.get("docx", {}).get("sha256"):
                errors.append("render receipt DOCX hash does not match frozen loop DOCX")
            if receipt.get("pdf", {}).get("sha256") != manifest.get("pdf", {}).get("sha256"):
                errors.append("render receipt PDF hash does not match frozen loop PDF")
            if receipt.get("page_count") != manifest.get("page_count"):
                errors.append("render receipt page count does not match frozen loop")
        except json.JSONDecodeError:
            errors.append(f"render receipt is invalid JSON: {receipt_path}")
    image_records = manifest.get("page_images", [])
    if len(image_records) != manifest.get("page_count"):
        errors.append(f"page image manifest count mismatch: {entry.get('loop_id')}")
    for record in image_records:
        path, _ = resolve_scoped(root, record.get("path", ""))
        if not path.is_file():
            errors.append(f"QA page image is missing: {path}")
        elif sha256_file(path) != record.get("sha256"):
            errors.append(f"QA page image hash changed: {path}")
    return list(dict.fromkeys(errors))


def verify_final_delivery(
    root: Path, registry: dict[str, Any], raw_manifest: str | Path
) -> list[str]:
    errors: list[str] = []
    manifest_path, _ = resolve_scoped(root, raw_manifest)
    if not manifest_path.is_file():
        return [f"final delivery manifest is missing: {manifest_path}"]
    try:
        final_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return [f"final delivery manifest is invalid JSON: {manifest_path}"]
    source_loop = final_manifest.get("source_loop")
    try:
        entry = resolve_loop_entry(registry, source_loop)
    except ValueError as exc:
        return [str(exc)]
    source_manifest, _ = resolve_scoped(root, entry.get("manifest", ""))
    if not source_manifest.is_file():
        errors.append(f"source loop manifest is missing: {source_manifest}")
    elif final_manifest.get("source_manifest_sha256") != sha256_file(source_manifest):
        errors.append("final delivery source loop manifest hash does not match")
    for label, validator in (("docx", final_docx_hygiene), ("pdf", validate_pdf)):
        record = final_manifest.get(label, {})
        path, _ = resolve_scoped(root, record.get("path", ""))
        if not path.is_file():
            errors.append(f"final {label.upper()} is missing: {path}")
            continue
        if record.get("sha256") != sha256_file(path):
            errors.append(f"final {label.upper()} hash changed: {path}")
        errors.extend(validator(path))
    if final_manifest.get("docx", {}).get("editable") is not True:
        errors.append("final DOCX is not marked editable")
    if final_manifest.get("pdf", {}).get("derived_from_same_loop_docx") is not True:
        errors.append("final PDF is not recorded as derived from the same loop DOCX")
    if final_manifest.get("visual_qa") != "all pages passed":
        errors.append("final delivery does not record full-page visual QA")
    return list(dict.fromkeys(errors))


def command_verify(args: argparse.Namespace) -> None:
    registry_path, _ = resolve_scoped(args.project_root, args.registry)
    registry = read_registry(registry_path)
    errors = validate_registry_shape(registry)
    entries = registry.get("loops", []) if args.loop_id == "all" else [
        resolve_loop_entry(registry, args.loop_id)
    ]
    for entry in entries:
        errors.extend(verify_loop(args.project_root, entry, args.final_ready))
    if args.final_manifest:
        errors.extend(verify_final_delivery(args.project_root, registry, args.final_manifest))
    if errors:
        for error in errors:
            print(f"FAIL: {error}")
        print(f"RESULT: FAIL ({len(errors)} errors)")
        raise SystemExit(1)
    print(f"RESULT: PASS ({len(entries)} loop(s))")


def command_finalize(args: argparse.Namespace) -> None:
    registry_path, _ = resolve_scoped(args.project_root, args.registry)
    registry = read_registry(registry_path)
    fail(validate_registry_shape(registry))
    entry = resolve_loop_entry(registry, args.loop_id)
    fail(verify_loop(args.project_root, entry, True))
    manifest_path, _ = resolve_scoped(args.project_root, entry["manifest"])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    source_docx, _ = resolve_scoped(args.project_root, manifest["docx"]["path"])
    source_pdf, _ = resolve_scoped(args.project_root, manifest["pdf"]["path"])
    output_dir, _ = resolve_scoped(args.project_root, args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    target_docx = output_dir / args.docx_name
    target_pdf = output_dir / args.pdf_name
    for source, target in ((source_docx, target_docx), (source_pdf, target_pdf)):
        if target.exists() and sha256_file(target) != sha256_file(source):
            fail([f"refusing to overwrite a different final artifact: {target}"])
        if not target.exists():
            shutil.copy2(source, target)
    final_manifest = {
        "schema_version": SCHEMA_VERSION,
        "created_at": utc_now(),
        "source_loop": entry["loop_id"],
        "source_manifest_sha256": sha256_file(manifest_path),
        "page_count": manifest["page_count"],
        "visual_qa": "all pages passed",
        "docx": {
            "path": target_docx.relative_to(args.project_root).as_posix(),
            "sha256": sha256_file(target_docx),
            "editable": True,
        },
        "pdf": {
            "path": target_pdf.relative_to(args.project_root).as_posix(),
            "sha256": sha256_file(target_pdf),
            "derived_from_same_loop_docx": True,
        },
    }
    final_manifest_path = output_dir / "FINAL_DELIVERY.json"
    if final_manifest_path.exists():
        existing = json.loads(final_manifest_path.read_text(encoding="utf-8"))
        if existing.get("docx", {}).get("sha256") != final_manifest["docx"]["sha256"]:
            fail([f"refusing to overwrite a different final manifest: {final_manifest_path}"])
    else:
        atomic_json(final_manifest_path, final_manifest)
    print(f"RESULT: PASS finalized {entry['loop_id']}")
    print(f"DOCX: {target_docx}")
    print(f"PDF: {target_pdf}")


def add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--registry", required=True)
    parser.add_argument("--project-root", type=Path, required=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    init_parser = commands.add_parser("init")
    add_common(init_parser)
    init_parser.add_argument("--working-docx", required=True)
    init_parser.set_defaults(handler=command_init)

    render_parser = commands.add_parser("render")
    render_parser.add_argument("--project-root", type=Path, required=True)
    render_parser.add_argument("--docx", required=True)
    render_parser.add_argument("--output-dir", required=True)
    render_parser.add_argument("--renderer", required=True)
    render_parser.set_defaults(handler=command_render)

    snapshot_parser = commands.add_parser("snapshot")
    add_common(snapshot_parser)
    snapshot_parser.add_argument("--loop-id", required=True)
    snapshot_parser.add_argument("--docx", required=True)
    snapshot_parser.add_argument("--render-receipt", required=True)
    snapshot_parser.add_argument("--all-pages-reviewed", action="store_true")
    snapshot_parser.add_argument('--delta-qa-receipt')
    snapshot_parser.add_argument("--strategy-context", required=True)
    snapshot_parser.add_argument("--changeset", required=True)
    snapshot_parser.set_defaults(handler=command_snapshot)

    delta_parser = commands.add_parser('delta-plan')
    delta_parser.add_argument('--project-root', required=True, type=Path)
    delta_parser.add_argument('--previous-manifest', required=True)
    delta_parser.add_argument('--render-receipt', required=True)
    delta_parser.add_argument('--output', required=True)
    delta_parser.set_defaults(handler=command_delta_plan)

    verify_parser = commands.add_parser("verify")
    add_common(verify_parser)
    verify_parser.add_argument("--loop-id", default="latest")
    verify_parser.add_argument("--final-ready", action="store_true")
    verify_parser.add_argument("--final-manifest")
    verify_parser.set_defaults(handler=command_verify)

    finalize_parser = commands.add_parser("finalize")
    add_common(finalize_parser)
    finalize_parser.add_argument("--loop-id", default="latest")
    finalize_parser.add_argument("--output-dir", default="submission")
    finalize_parser.add_argument("--docx-name", default="论文.docx")
    finalize_parser.add_argument("--pdf-name", default="论文.pdf")
    finalize_parser.set_defaults(handler=command_finalize)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    args.project_root = args.project_root.resolve()
    try:
        args.handler(args)
    except (ValueError, OSError, zipfile.BadZipFile) as exc:
        print(f"FAIL: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
