"""Synthetic direction/partition experiment with a shared finite-segment evaluator.

This is a development example, not a solver or new score for a previously exposed case.
Feasibility is checked on a declared grid; it is never labelled continuous coverage.
"""
from __future__ import annotations

import argparse
import itertools
import json
import math
from pathlib import Path
import time

import numpy as np
from scipy.optimize import linprog

from runtime_support import atomic_json, file_hash

WIDTH, HEIGHT, TAN_HALF = 20.0, 12.0, math.sqrt(3)


def depth(x, y):
    return 1.2 + .05 * x + .08 * y + .25 * np.sin(.4 * x)


def targets(nx=101, ny=61):
    x, y = np.meshgrid(np.linspace(0, WIDTH, nx), np.linspace(0, HEIGHT, ny))
    return np.column_stack([x.ravel(), y.ravel()])


def stripes(bounds, angle, overlap=.15, margin=0.):
    x0, x1, y0, y1 = bounds
    corners = np.array([[x0, y0], [x0, y1], [x1, y0], [x1, y1]])
    tangent = np.array([math.cos(angle), math.sin(angle)])
    normal = np.array([-tangent[1], tangent[0]])
    along, across = corners @ tangent, corners @ normal
    # Analytic safe lower depth envelope within this rectangular partition.
    shallow = 1.2 + .05 * x0 + .08 * y0 - .25 - margin
    if shallow <= 0:
        raise ValueError('nonpositive conservative depth')
    spacing = 2 * shallow * TAN_HALF * (1 - overlap)
    count = max(1, math.ceil((across.max() - across.min()) / spacing))
    offsets = np.linspace(across.min(), across.max(), count + 1)
    return [np.array([tangent * (along.min() - .1) + normal * a,
                      tangent * (along.max() + .1) + normal * a]) for a in offsets]


def contours(bounds, margin=0.):
    x0, x1, y0, y1 = bounds
    xs = np.linspace(x0 - .2, x1 + .2, 25)
    # D(x,y)=f(x)+.08*y, so these nodes are exact depth contours.
    f = 1.2 + .05 * xs + .25 * np.sin(.4 * xs)
    low = float(f.min() + .08 * y0)
    high = float(f.max() + .08 * y1)
    increment = 2 * max(.1, low - margin) * TAN_HALF * .08 * .8
    values = np.arange(low - increment, high + 2 * increment, increment)
    return [np.column_stack([xs, (c - f) / .08]) for c in values]


def route(family, partitions, seed, margin=0., cuts=None, families=None):
    rng = np.random.default_rng(seed)
    paths = []
    boundaries = [0., *(cuts if cuts is not None else [WIDTH * i / partitions for i in range(1, partitions)]), WIDTH]
    for i in range(partitions):
        x0, x1 = boundaries[i:i+2]
        bounds = (x0, x1, 0., HEIGHT)
        choice = families[i] if families else family
        if choice == 'axis':
            paths += stripes(bounds, math.pi / 2, margin=margin)
        elif choice == 'local_direction':
            gx = .05 + .1 * math.cos(.4 * (x0 + x1) / 2)
            angle = math.atan2(gx, -.08) + float(rng.uniform(-.035, .035))
            paths += stripes(bounds, angle, margin=margin)
        elif choice == 'contour_polyline':
            paths += contours(bounds, margin=margin)
        else:
            raise ValueError('unknown route family')
    return paths


def coverage_mask(paths, points, depth_shift=0.):
    radii = (depth(points[:, 0], points[:, 1]) + depth_shift) * TAN_HALF
    counts = np.zeros(len(points), dtype=int)
    # Count distinct survey paths, not each small segment of the same polyline.
    for path in paths:
        covered = np.zeros(len(points), dtype=bool)
        for a, b in zip(path, path[1:]):
            v = b - a; length = np.linalg.norm(v)
            if length <= 1e-12:
                continue
            u = v / length; delta = points - a
            along = delta @ u
            cross = np.abs(delta[:, 0] * u[1] - delta[:, 1] * u[0])
            covered |= (along >= -1e-10) & (along <= length + 1e-10) & (cross <= radii + 1e-10)
        counts += covered
    return counts


def navigation(paths):
    remaining = [p.copy() for p in paths]
    position = np.array([0., 0.])
    distance, turns = 0., 0
    while remaining:
        options = [(float(np.linalg.norm(position - p[end])), i, end)
                   for i, p in enumerate(remaining) for end in (0, -1)]
        length, index, end = min(options)
        path = remaining.pop(index)
        if end == -1:
            path = path[::-1]
        distance += length; position = path[-1]
        vectors = np.diff(path, axis=0)
        turns += int(sum(abs(a[0] * b[1] - a[1] * b[0]) > 1e-9 for a, b in zip(vectors, vectors[1:])))
    distance += float(np.linalg.norm(position))
    return distance, turns + max(0, len(paths) - 1)


def evaluate(paths, points, partitions=1, depth_shift=0., cuts=None):
    counts = coverage_mask(paths, points, depth_shift)
    boundary = ((points[:, 0] == 0) | (points[:, 0] == WIDTH)
                | (points[:, 1] == 0) | (points[:, 1] == HEIGHT))
    seam = np.zeros(len(points), dtype=bool)
    for boundary_x in cuts if cuts is not None else [WIDTH * i / partitions for i in range(1, partitions)]:
        seam |= np.abs(points[:, 0] - boundary_x) <= WIDTH / 100
    transfer, turns = navigation(paths)
    length = float(sum(np.linalg.norm(np.diff(path, axis=0), axis=1).sum() for path in paths))
    return {'measurement_length': length, 'transfer_length': transfer,
            'total_length': length + transfer, 'turns': turns, 'path_count': len(paths),
            'segment_count': sum(len(p) - 1 for p in paths), 'endpoints': 2 * len(paths),
            'missed_fraction': float(np.mean(counts == 0)),
            'excess_multiplicity': float(np.maximum(counts - 1, 0).mean()),
            'boundary_missed_points': int(np.sum(counts[boundary] == 0)),
            'seam_missed_points': int(np.sum(counts[seam] == 0)),
            'feasible': bool(np.all(counts > 0)), 'coverage_scope': f'{len(points)} frozen sample points'}


def calibrated_margin(residuals, alpha):
    """One-sided split-conformal rank; positive residual means predicted depth is too deep."""
    if not 0 < alpha < 1 or not residuals or not all(math.isfinite(v) for v in residuals):
        raise ValueError('calibration requires finite residuals and alpha in (0,1)')
    rank = math.ceil((len(residuals) + 1) * (1 - alpha))
    if rank > len(residuals):
        return {'margin': None, 'rank': rank, 'guarantee': 'insufficient calibration size'}
    return {'margin': max(0., sorted(residuals)[rank - 1]), 'rank': rank,
            'guarantee': 'marginal one-point coverage conditional on exchangeability; not simultaneous spatial coverage'}


def restricted_cover_bound(path_library, points):
    matrix = np.column_stack([coverage_mask([p], points) > 0 for p in path_library]).astype(float)
    costs = np.array([np.linalg.norm(np.diff(p, axis=0), axis=1).sum() for p in path_library])
    result = linprog(costs, A_ub=-matrix, b_ub=-np.ones(len(points)), bounds=(0, 1), method='highs')
    if not result.success:
        raise ValueError('finite-library covering relaxation is infeasible')
    return {'lower_bound': float(result.fun), 'scope': 'fractional cover of frozen sample points by this finite path library',
            'path_library_size': len(path_library), 'is_unrestricted_geometric_bound': False}


def run(output: Path):
    output.mkdir(parents=True, exist_ok=True)
    grid = targets()
    rows, library = [], []
    for family, partitions, seed in itertools.product(
            ['axis', 'local_direction', 'contour_polyline'], [1, 2, 4], [7, 19, 41]):
        began = time.perf_counter()
        paths = route(family, partitions, seed)
        metrics = evaluate(paths, grid, partitions)
        rows.append({'family': family, 'partitions': partitions, 'seed': seed,
                     'observed_seconds': time.perf_counter() - began, **metrics})
        if seed == 7:
            library += paths
    feasible = [r for r in rows if r['feasible']]
    joint_rows = []
    for cuts, families, seed in itertools.product(
            [[WIDTH * .35], [WIDTH * .5], [WIDTH * .65]],
            itertools.product(['axis', 'local_direction', 'contour_polyline'], repeat=2), [7, 19, 41]):
        began = time.perf_counter()
        paths = route('joint', 2, seed, cuts=cuts, families=families)
        metrics = evaluate(paths, grid, 2, cuts=cuts)
        joint_rows.append({'family': 'joint', 'zone_families': list(families), 'partitions': 2,
            'cuts': cuts, 'seed': seed, 'observed_seconds': time.perf_counter() - began, **metrics})
        if seed == 7:
            library += paths
    feasible += [r for r in joint_rows if r['feasible']]
    selected = min(feasible, key=lambda r: r['total_length'])
    chosen = route(selected['family'], selected['partitions'], selected['seed'],
                   cuts=selected.get('cuts'), families=selected.get('zone_families'))
    residuals = np.random.default_rng(103).normal(.03, .045, 39).tolist()
    calibration = calibrated_margin(residuals, .1)
    robust_paths = route(selected['family'], selected['partitions'], selected['seed'], calibration['margin'],
                        cuts=selected.get('cuts'), families=selected.get('zone_families'))
    # For a finite segment the target condition is inside a rectangle of width <= 2*Dmax*tan(theta).
    upper_depth = 1.2 + .05 * WIDTH + .08 * HEIGHT + .25
    geometric_bound = WIDTH * HEIGHT / (2 * upper_depth * TAN_HALF)
    finite_bound = restricted_cover_bound(library, targets(21, 13))
    result = {'schema_version': '1.0', 'dataset_role': 'synthetic_development',
              'evaluator': {'path': str(Path(__file__).resolve()), 'sha256': file_hash(__file__)},
              'definition': {'denominator': 'all frozen target points', 'aggregation': 'distinct-path excess multiplicity'},
              'precision': {'nx': 101, 'ny': 61, 'endpoint_tolerance': 1e-10}, 'candidates': rows,
              'joint_partition_direction_candidates': joint_rows,
              'actual_budget': {'base_family_layouts': len(rows), 'joint_layouts': len(joint_rows),
                                'strict_equal_budget_ablation': False},
              'selected_by': 'total measurement and straight transfer length among sampled-feasible candidates',
              'selected': selected, 'unrestricted_rectangle_area_bound': geometric_bound,
              'restricted_library_bound': finite_bound,
              'calibration': {'source': 'synthetic residuals; no field calibration claim', 'n': len(residuals), **calibration},
              'simultaneous_grid_calibration': calibrated_margin(residuals, .1 / len(grid)),
              'robustness': [{'depth_shift': s, 'nominal': evaluate(chosen, grid, selected['partitions'], s, selected.get('cuts')),
                              'calibrated_margin_route': evaluate(robust_paths, grid, selected['partitions'], s, selected.get('cuts'))}
                             for s in [0., -.1, -.2]],
              'claim_limits': ['grid verification is not continuous coverage',
                               'navigation assumes straight unobstructed transfers',
                               'survey paths may extend outside the target rectangle; their full lengths are counted',
                               'joint search has a larger recorded budget and is not labelled a strict equal-budget ablation',
                               'LP bound applies only to the finite path library',
                               'calibration is marginal under exchangeability, not a whole-area probability guarantee']}
    atomic_json(output / 'TERRAIN_DEVELOPMENT.json', result)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, required=True)
    result = run(parser.parse_args().output_dir.resolve())
    print(json.dumps({'selected': result['selected'], 'bound': result['restricted_library_bound'],
                      'calibration': result['calibration']}, indent=2))
