"""Executable interval-definition pressure examples; no definition is universally selected."""
from __future__ import annotations

import argparse
from pathlib import Path

from runtime_support import atomic_json, record


def overlap(a, b, definition, domain=None):
    if domain is not None:
        a = (max(a[0], domain[0]), min(a[1], domain[1]))
        b = (max(b[0], domain[0]), min(b[1], domain[1]))
    widths = [a[1] - a[0], b[1] - b[0]]
    if min(widths) <= 0:
        raise ValueError('positive clipped widths required')
    shared = max(0., min(a[1], b[1]) - max(a[0], b[0]))
    denominators = {'current': widths[1], 'narrower': min(widths), 'mean_width': sum(widths) / 2}
    return shared / denominators[definition]


def run(root: Path):
    root.mkdir(parents=True, exist_ok=True)
    examples = {'flat': ((0., 10.), (8.5, 18.5), None),
                'swap': ((0., 10.), (8.5, 14.5), None),
                'touch': ((0., 10.), (10., 17.), None),
                'nested': ((0., 10.), (3., 5.), None),
                'clip': ((-4., 6.), (4., 14.), (0., 10.))}
    definitions = ['current', 'narrower', 'mean_width']
    rows = []
    # A second physical layout shows whether choice of denominator changes ranking.
    comparator = ((0., 8.), (6.5, 14.5))
    for name, (a, b, domain) in examples.items():
        values = {d: overlap(a, b, d, domain) for d in definitions}
        feasible = {d: .1 <= v <= .2 for d, v in values.items()}
        comparator_values = {d: overlap(*comparator, d, domain) for d in definitions}
        ranking = {d: values[d] <= comparator_values[d] for d in definitions}
        path = root / (name + '.json')
        atomic_json(path, {'intervals': [a, b], 'domain': domain, 'values': values,
                          'swapped': {d: overlap(b, a, d, domain) for d in definitions},
                          'feasibility': feasible, 'comparator': comparator,
                          'comparator_values': comparator_values, 'ranking': ranking})
        rows.append({'case': name, 'definitions': values,
                     'feasibility_changed': len(set(feasible.values())) > 1,
                     'ranking_changed': len(set(ranking.values())) > 1,
                     'evidence': record(root, path)})
    result = {'schema_version': '1.0', 'cases': rows, 'selected_definition': 'mean_width',
              'selection_reason': 'Synthetic example uses a symmetric width normalization; select the actual problem definition before reuse.',
              'dataset_role': 'synthetic_development'}
    atomic_json(root / 'DEFINITION_PROBE.json', result)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', required=True, type=Path)
    run(parser.parse_args().output_dir.resolve())
