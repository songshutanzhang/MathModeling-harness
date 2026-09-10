#!/usr/bin/env python3
"""Append and verify a tamper-evident artifact lifecycle event stream."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


ZERO = "0" * 64
EVENTS = {"produced", "promoted", "frozen", "disposable", "deleted"}


def event_hash(event: dict) -> str:
    payload = {key: value for key, value in event.items() if key != "event_hash"}
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest().upper()


def read_events(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def verify(events: list[dict]) -> dict[str, str]:
    previous = ZERO
    state: dict[str, str] = {}
    durable: set[str] = set()
    for sequence, event in enumerate(events, start=1):
        if event.get("sequence") != sequence or event.get("previous_event_hash") != previous:
            raise ValueError(f"lifecycle chain broken at event {sequence}")
        if event.get("event_type") not in EVENTS or event.get("event_hash") != event_hash(event):
            raise ValueError(f"invalid lifecycle event {sequence}")
        artifact = event.get("artifact_id")
        if not isinstance(artifact, str) or not artifact:
            raise ValueError(f"artifact_id missing at event {sequence}")
        kind = event["event_type"]
        if kind in {"promoted", "frozen"}:
            durable.add(artifact)
        if kind == "disposable":
            replacement = event.get("durable_replacement_id")
            if replacement not in durable:
                raise ValueError(f"disposable artifact lacks prior durable replacement: {artifact}")
        if kind == "deleted" and state.get(artifact) != "disposable":
            raise ValueError(f"artifact deleted before disposable: {artifact}")
        state[artifact] = kind
        previous = event["event_hash"]
    return state


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser("verify")
    check.add_argument("--ledger", required=True, type=Path)
    record = sub.add_parser("record")
    record.add_argument("--ledger", required=True, type=Path)
    record.add_argument("--run-id", required=True)
    record.add_argument("--event", required=True, choices=sorted(EVENTS))
    record.add_argument("--artifact-id", required=True)
    record.add_argument("--path", required=True)
    record.add_argument("--sha256", required=True)
    record.add_argument("--timestamp", required=True)
    record.add_argument("--durable-replacement-id")
    args = parser.parse_args()
    events = read_events(args.ledger)
    state = verify(events)
    if args.command == "verify":
        print(f"PASS: events={len(events)} artifacts={len(state)}")
        return 0
    if args.event == "disposable" and not args.durable_replacement_id:
        parser.error("disposable requires --durable-replacement-id")
    event = {
        "sequence": len(events) + 1, "run_id": args.run_id, "event_type": args.event,
        "artifact_id": args.artifact_id, "path": args.path, "sha256": args.sha256.upper(),
        "timestamp": args.timestamp, "durable_replacement_id": args.durable_replacement_id,
        "previous_event_hash": events[-1]["event_hash"] if events else ZERO,
    }
    event["event_hash"] = event_hash(event)
    verify(events + [event])
    args.ledger.parent.mkdir(parents=True, exist_ok=True)
    with args.ledger.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
    print(f"PASS: sequence={event['sequence']} event_hash={event['event_hash']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
