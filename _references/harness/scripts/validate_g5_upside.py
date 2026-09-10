#!/usr/bin/env python3
"""An independently switchable artifact-isolated upside assessment; never a hard gate."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import yaml


def validate(bundle: Path) -> dict:
    spec = importlib.util.spec_from_file_location('g5_common', Path(__file__).with_name('validate_g5_bundle.py'))
    common = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(common)
    common.validate_evidence(bundle)
    evidence = bundle / 'EVIDENCE_PACKAGE.json'
    review = yaml.safe_load((bundle / 'CEILING_REVIEWER.yaml').read_text(encoding='utf-8'))
    if review.get('role') != 'ceiling_reviewer' or review.get('other_review_seen') is not False or review.get('visibility') != 'evidence_package_only':
        raise ValueError('upside review input isolation failed')
    if review.get('evidence_package_sha256', '').upper() != hashlib.sha256(evidence.read_bytes()).hexdigest().upper():
        raise ValueError('upside evidence hash mismatch')
    score = review.get('competition_upside_score')
    if type(score) not in (float, int) or not 0 <= score <= 100:
        raise ValueError('invalid upside score')
    return {'competition_upside_score': score, 'can_approve_results': False,
            'isolation_claim': 'artifact-isolated', 'runtime_independence': 'not_verified_here'}


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--bundle', type=Path, required=True)
    print(json.dumps(validate(p.parse_args().bundle), ensure_ascii=False))
