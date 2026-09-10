"""Extract a pilot cost from a completed runner event; estimates are never observations."""
import argparse
import json
from pathlib import Path

from runtime_support import atomic_json, record, verify_record, read_json
from run_orchestrator import read_events


def extract(root: Path, state: Path, task_id: str, output: Path):
    matches = [e for e in read_events(state) if e['event_type'] == 'task_completed' and e['payload']['task_id'] == task_id]
    if not matches:
        raise ValueError('pilot has no completed measurement event')
    event = matches[-1]
    for item in event['payload']['outputs']:
        verify_record(root, item)
    seconds = event['payload'].get('wall_clock_seconds')
    if seconds is None:
        raise ValueError('pilot elapsed cost is missing')
    path = next(p for p in (state / 'events').glob('*.json') if read_json(p)['event_hash'] == event['event_hash'])
    result = {'schema_version': '1.0', 'task_id': task_id, 'observed_seconds': seconds,
              'measurement_receipt': record(root, path), 'task_identity': event['payload']['task_identity'],
              'outputs': event['payload']['outputs'], 'includes_llm_and_waiting': False}
    atomic_json(output, result, immutable=True)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project-root', required=True, type=Path)
    parser.add_argument('--state-dir', required=True, type=Path)
    parser.add_argument('--task-id', required=True)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(extract(args.project_root.resolve(), args.state_dir.resolve(), args.task_id, args.output), indent=2))
