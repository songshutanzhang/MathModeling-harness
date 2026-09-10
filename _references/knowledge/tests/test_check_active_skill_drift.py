from __future__ import annotations

import importlib.util
from pathlib import Path
import tempfile
import unittest


SCRIPT = Path(__file__).parents[1] / "scripts" / "check_active_skill_drift.py"
SPEC = importlib.util.spec_from_file_location("check_active_skill_drift", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


class CheckActiveSkillDriftTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.repo = self.root / "repo"
        self.active = self.root / "active"
        text = (
            "reference_case_ingestion training_run evaluation_run live_competition "
            "不创建 `HUMAN_GATES.json` MODEL_REASONING_ROUTER.md "
            "MODEL_CAPABILITY_SNAPSHOT.json REASONING_ROUTE_LEDGER.jsonl reasoning_route.py "
            "ARTIFACT_GOVERNANCE.md G2 候选 G5 决策 "
            "dependency_preflight.py run_orchestrator.py contest_rules.py"
        )
        for base in (self.repo, self.active):
            path = base / "1start-mathmodel" / "SKILL.md"
            path.parent.mkdir(parents=True)
            path.write_text(text, encoding="utf-8")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_exact_match_passes(self) -> None:
        result = MODULE.inspect(self.repo, self.active, ["1start-mathmodel"])
        self.assertTrue(result["pass"])

    def test_hash_drift_fails(self) -> None:
        path = self.active / "1start-mathmodel" / "SKILL.md"
        path.write_text(path.read_text(encoding="utf-8") + "\ndrift", encoding="utf-8")
        result = MODULE.inspect(self.repo, self.active, ["1start-mathmodel"])
        self.assertFalse(result["pass"])
        self.assertFalse(result["skills"][0]["exact_match"])

    def test_missing_conditional_reference_fails_even_with_matching_entry(self) -> None:
        reference = self.repo / '1start-mathmodel' / 'references' / 'training.md'
        reference.parent.mkdir()
        reference.write_text('Actual conditional instructions', encoding='utf-8')
        result = MODULE.inspect(self.repo, self.active, ['1start-mathmodel'])
        self.assertFalse(result['pass'])
        self.assertTrue(result['skills'][0]['exact_match'])

    def test_shared_policy_drift_fails(self) -> None:
        for base, value in ((self.repo, 'vNext'), (self.active, 'legacy')):
            path = base / '_references' / 'harness' / 'policy.yaml'
            path.parent.mkdir(parents=True)
            path.write_text(value, encoding='utf-8')
        self.assertFalse(MODULE.inspect(self.repo, self.active, ['1start-mathmodel'])['pass'])

    def test_missing_policy_token_fails_even_if_copies_match(self) -> None:
        for base in (self.repo, self.active):
            (base / "1start-mathmodel" / "SKILL.md").write_text(
                "reference_case_ingestion", encoding="utf-8"
            )
        result = MODULE.inspect(self.repo, self.active, ["1start-mathmodel"])
        self.assertFalse(result["pass"])
        self.assertTrue(result["skills"][0]["exact_match"])
        self.assertIn("evaluation_run", result["skills"][0]["missing_policy_tokens"])

    def test_missing_reasoning_route_policy_fails_even_if_copies_match(self) -> None:
        text = (
            "reference_case_ingestion evaluation_run live_competition "
            "不创建 `HUMAN_GATES.json`"
        )
        for base in (self.repo, self.active):
            (base / "1start-mathmodel" / "SKILL.md").write_text(text, encoding="utf-8")
        result = MODULE.inspect(self.repo, self.active, ["1start-mathmodel"])
        self.assertFalse(result["pass"])
        self.assertIn("reasoning_route.py", result["skills"][0]["missing_policy_tokens"])


if __name__ == "__main__":
    unittest.main()
