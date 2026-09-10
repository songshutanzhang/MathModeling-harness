import importlib.util
import json
from pathlib import Path
import pytest

SCRIPT = Path(__file__).resolve().parents[2] / '5writing/scripts/word_loop.py'
spec = importlib.util.spec_from_file_location('delta_word_loop', SCRIPT)
word = importlib.util.module_from_spec(spec)
spec.loader.exec_module(word)


def image_record(root, name, content):
    path = root / name
    path.write_bytes(content)
    return {'path': name, 'sha256': word.sha256_file(path)}


def test_delta_reuses_only_same_position_and_requires_all_changed_pages(tmp_path):
    a = image_record(tmp_path, 'old1.png', b'page A')
    b = image_record(tmp_path, 'old2.png', b'page B')
    c = image_record(tmp_path, 'new2.png', b'changed B')
    old = {'status': 'qa_passed', 'all_pages_reviewed': True, 'page_images': [a, b]}
    current = {'page_images': [a, c]}
    word.atomic_json(tmp_path / 'old.json', old)
    word.atomic_json(tmp_path / 'new.json', current)
    plan = word.delta_qa_plan(tmp_path, Path('old.json'), Path('new.json'))
    assert plan['reused_pages'] == [1] and plan['must_review_pages'] == [2]
    review = {**plan, 'previous_manifest': 'old.json', 'status': 'passed', 'reviewed_changed_pages': []}
    word.atomic_json(tmp_path / 'review.json', review)
    with pytest.raises(ValueError, match='changed pages'):
        word.verify_delta_qa(tmp_path, Path('review.json'), Path('new.json'))
    review['reviewed_changed_pages'] = [2]
    word.atomic_json(tmp_path / 'review.json', review)
    assert word.verify_delta_qa(tmp_path, Path('review.json'), Path('new.json'))['status'] == 'passed'
    word.atomic_json(tmp_path / 'new.json', {'page_images': [b, a]})
    assert word.delta_qa_plan(tmp_path, Path('old.json'), Path('new.json'))['reused_pages'] == []


def test_delta_refuses_drift_and_unreviewed_previous_loop(tmp_path):
    page = image_record(tmp_path, 'old.png', b'page')
    old = {'status': 'draft', 'all_pages_reviewed': False, 'page_images': [page]}
    word.atomic_json(tmp_path / 'old.json', old)
    word.atomic_json(tmp_path / 'new.json', {'page_images': [page]})
    with pytest.raises(ValueError, match='previously passed'):
        word.delta_qa_plan(tmp_path, Path('old.json'), Path('new.json'))
    old.update(status='qa_passed', all_pages_reviewed=True)
    word.atomic_json(tmp_path / 'old.json', old)
    (tmp_path / 'old.png').write_bytes(b'tampered')
    with pytest.raises(ValueError, match='image drift'):
        word.delta_qa_plan(tmp_path, Path('old.json'), Path('new.json'))
