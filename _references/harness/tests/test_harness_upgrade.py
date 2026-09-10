from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[2]


def load_script(name: str):
    path = ROOT / "harness" / "scripts" / name
    spec = importlib.util.spec_from_file_location(name.replace(".py", ""), path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    return module


class HarnessUpgradeTests(unittest.TestCase):
    def _route_snapshot(self, module, root: Path, *, capable: bool) -> Path:
        efforts = ["high", "max", "ultra"] if capable else ["high"]
        topologies = ["single", "independent_candidates", "dual_review", "ensemble"] if capable else ["single"]
        requirements = {
            "independent_candidates": ["ultra"],
            "dual_review": ["ultra"],
            "ensemble": ["ultra"],
        } if capable else {}
        source = {
            "schema_version": "1.0",
            "captured_at": "2026-09-04T00:00:00+00:00",
            "runtime_id": "test-runtime",
            "current": {"model_id": "test-model", "reasoning_effort": "high"},
            "models": [{
                "model_id": "test-model",
                "supported_reasoning_efforts": efforts,
                "supports_task_override": capable,
                "supports_mid_conversation_update": capable,
            }],
            "supports_effective_setting_receipt": True,
            "supported_topologies": topologies,
            "topology_effort_requirements": requirements,
            "quota_policy": {"mode": "quality_first", "hard_budget_present": False},
        }
        snapshot = root / "run" / "MODEL_CAPABILITY_SNAPSHOT.json"
        snapshot.parent.mkdir(parents=True, exist_ok=True)
        snapshot.write_text(json.dumps(module.seal_snapshot(source)), encoding="utf-8")
        return snapshot

    def _model_receipt(self, root: Path, *, task_id: str, assessment_id: str,
                       effort: str, topology: str) -> Path:
        receipt = root / "run" / "route-receipts" / f"{task_id}-model.json"
        receipt.parent.mkdir(parents=True, exist_ok=True)
        receipt.write_text(json.dumps({
            "schema_version": "1.0", "receipt_id": f"MR-{task_id}",
            "captured_at": "2026-09-04T00:01:00+00:00",
            "source": "reasoning_effort_interface", "task_id": task_id,
            "assessment_event_id": assessment_id,
            "effective_model_id": "test-model",
            "effective_reasoning_effort": effort,
            "effective_topology": topology,
        }), encoding="utf-8")
        return receipt

    def _topology_receipt(
        self, module, root: Path, *, task_id: str, assessment_id: str,
        topology: str, frozen_hash: str, outputs: list[tuple[str, Path]],
    ) -> Path:
        receipt = root / "run" / "route-receipts" / f"{task_id}-topology.json"
        receipt.parent.mkdir(parents=True, exist_ok=True)
        units = [
            {
                "unit_id": f"unit-{index}", "role": role, "context_id": f"ctx-{index}",
                "visible_input_sha256": frozen_hash,
                "output": {"path": path.relative_to(root).as_posix(), "sha256": module.file_sha(path)},
            }
            for index, (role, path) in enumerate(outputs, start=1)
        ]
        receipt.write_text(json.dumps(module.seal_topology({
            "schema_version": "1.0", "receipt_id": f"TR-{task_id}",
            "captured_at": "2026-09-04T00:02:00+00:00", "task_id": task_id,
            "assessment_event_id": assessment_id, "topology": topology,
            "shared_context": False, "frozen_input_sha256": frozen_hash,
            "execution_units": units,
        })), encoding="utf-8")
        return receipt

    def test_training_route_without_gate_records_honest_degradation(self):
        module = load_script("reasoning_route.py")
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            snapshot = self._route_snapshot(module, root, capable=False)
            ledger = root / "run" / "REASONING_ROUTE_LEDGER.jsonl"
            assessed = module.assess(
                ledger, snapshot, mode="training_run", task_id="g2", stage="analysis",
                task_class="g2_candidate_generation",
            )
            self.assertIsNone(assessed["gate_id"])
            self.assertEqual(assessed["requested"]["topology"], "independent_candidates")
            receipt = self._model_receipt(
                root, task_id="g2", assessment_id=assessed["event_id"],
                effort="high", topology="single",
            )
            applied = module.apply(
                ledger, snapshot, receipt, task_id="g2", project_root=root,
                allow_degraded=True,
            )
            self.assertEqual(applied["status"], "degraded")
            self.assertEqual(applied["evidence_confidence"], "limited")
            output = root / "modeling" / "g2" / "ROUTE_SELECTION.yaml"
            output.parent.mkdir(parents=True)
            output.write_text("selected: baseline\n", encoding="utf-8")
            module.complete(ledger, task_id="g2", project_root=root, outputs=[str(output)])
            module.reassess(ledger, snapshot, task_id="g2")
            result = module.validate_ledger(ledger, snapshot, root, require_settled=True)
            self.assertEqual(result["states"], {"g2": "reassessed"})
            self.assertFalse((root / "compliance" / "HUMAN_GATES.json").exists())

    def test_formal_ultra_topology_requires_distinct_context_receipt(self):
        module = load_script("reasoning_route.py")
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            snapshot = self._route_snapshot(module, root, capable=True)
            ledger = root / "run" / "REASONING_ROUTE_LEDGER.jsonl"
            assessed = module.assess(
                ledger, snapshot, mode="evaluation_run", task_id="g2-formal",
                stage="analysis", task_class="g2_candidate_generation", gate_id="G2",
            )
            self.assertEqual(assessed["requested"]["reasoning_effort"], "ultra")
            freeze_hash = "A" * 64
            units = []
            for index in range(2):
                output = root / "modeling" / "g2" / f"candidate-{index}.yaml"
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_text(f"candidate: {index}\n", encoding="utf-8")
                units.append({
                    "unit_id": f"u{index}", "role": "candidate",
                    "context_id": f"ctx-{index}", "visible_input_sha256": freeze_hash,
                    "output": {"path": output.relative_to(root).as_posix(),
                               "sha256": module.file_sha(output)},
                })
            topology_path = root / "run" / "route-receipts" / "topology.json"
            topology_path.parent.mkdir(parents=True, exist_ok=True)
            topology_path.write_text(json.dumps(module.seal_topology({
                "schema_version": "1.0", "receipt_id": "TR-g2-formal",
                "captured_at": "2026-09-04T00:02:00+00:00", "task_id": "g2-formal",
                "assessment_event_id": assessed["event_id"],
                "topology": "independent_candidates", "shared_context": False,
                "frozen_input_sha256": freeze_hash, "execution_units": units,
            })), encoding="utf-8")
            receipt = self._model_receipt(
                root, task_id="g2-formal", assessment_id=assessed["event_id"],
                effort="ultra", topology="independent_candidates",
            )
            applied = module.apply(
                ledger, snapshot, receipt, task_id="g2-formal", project_root=root,
                topology_receipt_path=topology_path,
            )
            self.assertEqual(applied["status"], "applied")
            final = root / "modeling" / "g2" / "ROUTE_SELECTION.yaml"
            final.write_text("selected: u0\n", encoding="utf-8")
            completed = module.complete(
                ledger, task_id="g2-formal", project_root=root, outputs=[str(final)]
            )
            with self.assertRaisesRegex(ValueError, "not settled"):
                module.validate_ledger(ledger, snapshot, root, require_settled=True)
            module.reassess(ledger, snapshot, task_id="g2-formal")
            reference = module.completed_gate_reference(ledger, snapshot, root, "G2")
            self.assertEqual(reference["event_id"], completed["event_id"])

    def test_formal_route_selects_a_declared_model_that_supports_target_effort(self):
        module = load_script("reasoning_route.py")
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = {
                "schema_version": "1.0", "captured_at": "2026-09-04T00:00:00+00:00",
                "runtime_id": "two-model-runtime",
                "current": {"model_id": "base-model", "reasoning_effort": "high"},
                "models": [
                    {"model_id": "base-model", "supported_reasoning_efforts": ["high"],
                     "supports_task_override": True, "supports_mid_conversation_update": True},
                    {"model_id": "frontier-model", "supported_reasoning_efforts": ["high", "max", "ultra"],
                     "supports_task_override": True, "supports_mid_conversation_update": True},
                ],
                "supports_effective_setting_receipt": True,
                "supported_topologies": ["single", "independent_candidates"],
                "topology_effort_requirements": {"independent_candidates": ["ultra"]},
                "quota_policy": {"mode": "quality_first", "hard_budget_present": False},
            }
            snapshot = root / "snapshot.json"
            snapshot.write_text(json.dumps(module.seal_snapshot(source)), encoding="utf-8")
            event = module.assess(
                root / "ledger.jsonl", snapshot, mode="evaluation_run", task_id="g2",
                stage="analysis", task_class="g2_candidate_generation", gate_id="G2",
            )
            self.assertEqual(event["requested"]["model_id"], "frontier-model")
            self.assertEqual(event["requested"]["reasoning_effort"], "ultra")

    def test_non_single_topology_cannot_be_claimed_without_receipt(self):
        module = load_script("reasoning_route.py")
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            snapshot = self._route_snapshot(module, root, capable=True)
            ledger = root / "run" / "REASONING_ROUTE_LEDGER.jsonl"
            assessed = module.assess(
                ledger, snapshot, mode="evaluation_run", task_id="g5",
                stage="coding", task_class="g5_failure_review", gate_id="G5",
            )
            receipt = self._model_receipt(
                root, task_id="g5", assessment_id=assessed["event_id"],
                effort="ultra", topology="dual_review",
            )
            with self.assertRaisesRegex(ValueError, "requires an isolated execution receipt"):
                module.apply(ledger, snapshot, receipt, task_id="g5", project_root=root)

    def test_topology_receipt_rejects_duplicate_contexts(self):
        module = load_script("reasoning_route.py")
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            output = root / "candidate.yaml"
            output.write_text("candidate: one\n", encoding="utf-8")
            unit = {
                "role": "candidate", "context_id": "same-context",
                "visible_input_sha256": "A" * 64,
                "output": {"path": "candidate.yaml", "sha256": module.file_sha(output)},
            }
            receipt = module.seal_topology({
                "schema_version": "1.0", "receipt_id": "TR-duplicate",
                "captured_at": "2026-09-04T00:02:00+00:00", "task_id": "g2",
                "assessment_event_id": "RR-ASSESSMENT", "topology": "independent_candidates",
                "shared_context": False, "frozen_input_sha256": "A" * 64,
                "execution_units": [{"unit_id": "u1", **unit}, {"unit_id": "u2", **unit}],
            })
            with self.assertRaisesRegex(ValueError, "distinct contexts"):
                module.validate_topology_value(receipt, root)

    def test_topology_requires_effort_declared_by_capability_snapshot(self):
        module = load_script("reasoning_route.py")
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            snapshot = self._route_snapshot(module, root, capable=True)
            ledger = root / "run" / "REASONING_ROUTE_LEDGER.jsonl"
            assessed = module.assess(
                ledger, snapshot, mode="evaluation_run", task_id="g5-low",
                stage="coding", task_class="g5_failure_review", gate_id="G5",
            )
            units = []
            for index in range(2):
                output = root / f"review-{index}.json"
                output.write_text(f'{{"review": {index}}}\n', encoding="utf-8")
                units.append({
                    "unit_id": f"u{index}", "role": "reviewer", "context_id": f"ctx-{index}",
                    "visible_input_sha256": "B" * 64,
                    "output": {"path": output.name, "sha256": module.file_sha(output)},
                })
            topology = root / "topology.json"
            topology.write_text(json.dumps(module.seal_topology({
                "schema_version": "1.0", "receipt_id": "TR-g5-low",
                "captured_at": "2026-09-04T00:02:00+00:00", "task_id": "g5-low",
                "assessment_event_id": assessed["event_id"], "topology": "dual_review",
                "shared_context": False, "frozen_input_sha256": "B" * 64,
                "execution_units": units,
            })), encoding="utf-8")
            receipt = self._model_receipt(
                root, task_id="g5-low", assessment_id=assessed["event_id"],
                effort="high", topology="dual_review",
            )
            with self.assertRaisesRegex(ValueError, "does not establish"):
                module.apply(
                    ledger, snapshot, receipt, task_id="g5-low", project_root=root,
                    topology_receipt_path=topology, allow_degraded=True,
                )

    def test_route_application_requires_interface_receipt(self):
        module = load_script("reasoning_route.py")
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            snapshot = self._route_snapshot(module, root, capable=False)
            ledger = root / "run" / "REASONING_ROUTE_LEDGER.jsonl"
            assessed = module.assess(
                ledger, snapshot, mode="training_run", task_id="routine",
                stage="analysis", task_class="routine_analysis",
            )
            receipt = self._model_receipt(
                root, task_id="routine", assessment_id=assessed["event_id"],
                effort="high", topology="single",
            )
            data = json.loads(receipt.read_text(encoding="utf-8"))
            data["source"] = "user_claim"
            receipt.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "reasoning_effort_interface"):
                module.apply(ledger, snapshot, receipt, task_id="routine", project_root=root)

    def test_profile_resolver_keeps_kernel_and_separates_governance(self):
        module = load_script("resolve_harness_profile.py")
        draft = module.resolve(mode="training_run", tier="tier1")
        audit = module.resolve(mode="training_run", tier="tier2")
        contest = module.resolve(mode="evaluation_run", tier="tier3")
        draft_ids = {item["id"] for item in draft["active_modules"]}
        audit_ids = {item["id"] for item in audit["active_modules"]}
        contest_ids = {item["id"] for item in contest["active_modules"]}
        self.assertTrue(draft_ids < audit_ids)
        self.assertIn("word-delivery", audit_ids)
        self.assertNotIn("human-gates", draft_ids)
        self.assertNotIn("human-gates", audit_ids)
        self.assertIn("human-gates", contest_ids)
        self.assertIn("contest-compliance", contest_ids)
        with self.assertRaises(ValueError):
            module.resolve(mode="evaluation_run", tier="tier1")
        with self.assertRaises(ValueError):
            module.resolve(mode="invented", tier="tier1")

    def test_profile_resolver_rejects_experiment_without_execution_contract(self):
        module = load_script("resolve_harness_profile.py")
        default = module.resolve(mode="training_run", tier="tier1")
        self.assertNotIn("ceiling-rescue", {item["id"] for item in default["active_modules"]})
        with self.assertRaisesRegex(ValueError, "lack a registered executable contract"):
            module.resolve(
                mode="training_run", tier="tier1", experimental=["ceiling-rescue"]
            )
        with self.assertRaises(ValueError):
            module.resolve(mode="training_run", tier="tier1", conditions=["invented"])
        with self.assertRaises(ValueError):
            module.resolve(mode="training_run", tier="tier1", experimental=["g2-tournament"])

    def test_lightweight_manifest_v11_binds_harness_profile(self):
        module = load_script("validate_lightweight_manifest.py")
        with tempfile.TemporaryDirectory() as td:
            project = Path(td)
            artifacts = {}
            for name, relative, content in (
                ("result", "results/results.json", "{}\n"),
                ("paper", "paper/paper.md", "# Paper\n"),
                ("figures", "figures", None),
                ("harness_profile", "run/HARNESS_PROFILE.json", "{}\n"),
            ):
                target = project / relative
                if content is None:
                    target.mkdir(parents=True)
                    (target / "README.md").write_text("figures\n", encoding="utf-8")
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text(content, encoding="utf-8")
                artifacts[name] = {"path": relative, "sha256": module.tree_hash(target)}
            manifest = {
                "schema_version": "1.1", "run_id": "r", "problem_id": "p",
                "skill_version": "v", "model_version": "m", "mode": "training_run",
                "artifact_tier": "tier1", "source_exposure": "problem_only",
                **artifacts, "g2_route": "route", "g5_decision": "accept",
                "ai_usage": {"model": "m", "major_roles": [], "external_sources_used": []},
                "timestamp": "2026-09-02T00:00:00+08:00",
            }
            manifest_path = project / "run" / "LIGHTWEIGHT_MANIFEST.yaml"
            manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")
            self.assertEqual(module.validate(manifest_path, project)["schema_version"], "1.1")
            (project / "run" / "HARNESS_PROFILE.json").write_text('{"drift":true}\n', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "artifact hash mismatch: harness_profile"):
                module.validate(manifest_path, project)

    def test_profile_resolver_binds_governance_and_only_adds_modules(self):
        module = load_script("resolve_harness_profile.py")
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            governance = root / "ARTIFACT_GOVERNANCE.json"
            governance.write_text(
                json.dumps({"mode": "training_run", "resolved_tier": "tier2"}),
                encoding="utf-8",
            )
            initial = module.resolve_from_governance(governance)
            self.assertEqual(initial["artifact_tier"], "tier2")
            self.assertEqual(initial["profile_revision"], 1)
            first = root / "HARNESS_PROFILE.json"
            first.write_text(json.dumps(initial), encoding="utf-8")
            upgraded = module.resolve_from_governance(
                governance, conditions=["recovery_required"], supersedes_path=first
            )
            self.assertEqual(upgraded["profile_revision"], 2)
            self.assertIn("recovery-controller", {item["id"] for item in upgraded["active_modules"]})
            second = root / "HARNESS_PROFILE.v2.json"
            second.write_text(json.dumps(upgraded), encoding="utf-8")
            with self.assertRaises(ValueError):
                module.resolve_from_governance(
                    governance, conditions=[], supersedes_path=second
                )

    def test_reference_ingestion_does_not_activate_full_solver_chain(self):
        governance = load_script("resolve_artifact_governance.py")
        profile = load_script("resolve_harness_profile.py")
        decision = governance.resolve("reference_case_ingestion", [], 0, None)
        self.assertNotIn("results/results.json", decision["requirements"])
        resolved = profile.resolve(mode="reference_case_ingestion", tier="tier1")
        active = {item["id"] for item in resolved["active_modules"]}
        self.assertEqual(resolved["profile"], "reference")
        self.assertNotIn("solver-execution", active)
        self.assertNotIn("g5-blind-review", active)

    def test_profile_validator_checks_governance_and_required_modules(self):
        resolver = load_script("resolve_harness_profile.py")
        validator = load_script("validate_harness_profile.py")
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            governance = root / "ARTIFACT_GOVERNANCE.json"
            governance.write_text(
                json.dumps({"mode": "training_run", "resolved_tier": "tier1"}),
                encoding="utf-8",
            )
            profile_path = root / "HARNESS_PROFILE.json"
            profile_path.write_text(
                json.dumps(resolver.resolve_from_governance(governance)), encoding="utf-8"
            )
            result = validator.validate(
                profile_path, governance, required=["solver-execution", "results-contract"], stage="coding"
            )
            self.assertEqual(result["profile"], "draft")
            with self.assertRaises(ValueError):
                validator.validate(profile_path, governance, required=["word-delivery"], stage="writing")
            with self.assertRaises(ValueError):
                validator.validate(profile_path, governance, required=["solver-execution"], stage="writing")

    def test_run_record_collector_preserves_missing_cost_telemetry(self):
        module = load_script("collect_run_records.py")
        with tempfile.TemporaryDirectory() as td:
            runs = Path(td)
            case = runs / "case-a"
            (case / "compliance").mkdir(parents=True)
            (case / "compliance" / "CASE_MODE.yaml").write_text(
                "mode: training_run\n", encoding="utf-8"
            )
            (case / "compliance" / "ARTIFACT_GOVERNANCE.json").write_text(
                '{"resolved_tier":"tier1"}\n', encoding="utf-8"
            )
            record = module.collect(runs)[0]
            self.assertEqual(record["status"], "partial")
            self.assertIsNone(record["cost"]["token_usage"]["value"])
            self.assertEqual(record["cost"]["token_usage"]["evidence"], "missing")
            self.assertEqual(record["route"]["g5_integrity"]["value"], "missing")
            self.assertEqual(record["reasoning_routes"]["integrity"]["value"], "missing")

    def test_run_record_collector_uses_latest_g5_version(self):
        module = load_script("collect_run_records.py")
        with tempfile.TemporaryDirectory() as td:
            run = Path(td) / "case-a"
            for version, score in (("v1", 10), ("v2", 90)):
                bundle = run / "review" / "g5" / version
                bundle.mkdir(parents=True)
                (bundle / "G5_DECISION.yaml").write_text(
                    yaml.safe_dump({"reliability_score": score, "recommended_action": "accept"}),
                    encoding="utf-8",
                )
            record = module.collect_run(run)
            self.assertEqual(record["route"]["g5_bundle_path"]["value"], "review/g5/v2")
            self.assertEqual(record["route"]["g5_integrity"]["value"], "fail")
            self.assertIsNone(record["quality"]["reliability_score"]["value"])
            self.assertEqual(record["quality"]["reliability_score"]["evidence"], "integrity_failed")

    def test_reasoning_route_ablation_does_not_invent_quality_or_cost(self):
        module = load_script("ablate_reasoning_routes.py")
        records = [
            {"status": "artifact_complete_integrity_valid"},
            {"status": "artifact_complete_integrity_failed"},
            {"status": "partial"},
        ]
        result = module.ablate(records)
        self.assertEqual(result["artifact_complete_runs_eligible"], 2)
        self.assertEqual(result["bounded_task_opportunities"], 4)
        fixed = next(item for item in result["scenarios"] if item["scenario"] == "vnext_fixed_high_single_runtime")
        isolated = next(item for item in result["scenarios"] if item["scenario"] == "vnext_ultra_isolated_runtime")
        self.assertEqual(fixed["explicit_degraded_tasks"], 4)
        self.assertEqual(isolated["topology_verified_tasks"], 4)
        self.assertIsNone(result["quality_effect"]["value"])
        self.assertIsNone(result["cost_effect"]["value"])

    def test_component_registry_has_unique_ownership_and_safe_dispositions(self):
        module = load_script("validate_component_registry.py")
        result = module.validate(ROOT / "harness" / "component_registry.yaml")
        self.assertGreater(result["components"], 0)
        self.assertEqual(result["delete"], 0)
        self.assertGreater(result["lazy"], 0)
        self.assertGreater(result["guard"], 0)

    def test_governance_never_downgrades_formal_modes(self):
        module = load_script("resolve_artifact_governance.py")
        self.assertEqual(module.resolve("training_run", [], 0, None)["resolved_tier"], "tier1")
        self.assertEqual(module.resolve("training_run", [], 4, None)["resolved_tier"], "tier2")
        self.assertEqual(module.resolve("evaluation_run", [], 0, None)["resolved_tier"], "tier3")
        with self.assertRaises(ValueError):
            module.resolve("live_competition", [], 0, "tier2")
        with self.assertRaises(ValueError):
            module.resolve("training_run", [], 0, "tier3")
        with self.assertRaises(ValueError):
            module.resolve("reference_case_ingestion", [], 0, "tier2")

    def test_reliability_gate_blocks_upside_override(self):
        module = load_script("compare_harness_runs.py")
        base = {
            "run_id": "b", "benchmark_id": "x", "cases_evaluated": 3,
            "hard_failure_rate": 0.0, "reliability_score": 90,
            "competition_upside_score": 60, "token_usage": 100,
            "wall_clock_seconds": 100, "tool_calls": 10, "route_diversity": 0.3,
            "model_family_diversity": 0.3, "blind_paper_score": 70,
            "artifact_tier": "tier3",
        }
        candidate = dict(base, run_id="c", hard_failure_rate=1 / 3,
                         reliability_score=85, competition_upside_score=99)
        result = module.compare(base, candidate, 0.0)
        self.assertEqual(result["reliability_gate"], "FAIL")
        self.assertEqual(result["decision"], "reject_reliability_regression")

    def test_g2_blind_package_and_selection(self):
        module = load_script("g2_tournament.py")
        route = load_script("reasoning_route.py")
        with tempfile.TemporaryDirectory() as td:
            bundle = Path(td)
            (bundle / "candidates").mkdir()
            freeze = bundle / "PROBLEM_FREEZE.json"
            freeze.write_text('{"problem":"frozen"}\n', encoding="utf-8")
            freeze_hash = hashlib.sha256(freeze.read_bytes()).hexdigest().upper()
            for index, family in enumerate(("mechanistic", "optimization"), start=1):
                candidate = {
                    "schema_version": "1.0", "candidate_id": f"CAND-{index}",
                    "isolation": {"visibility": "problem_freeze_only", "other_candidate_ids_seen": [], "solver_advocacy_seen": False},
                    "problem_freeze_sha256": freeze_hash, "model_family": family,
                    "core_idea": "Use a genuinely distinct mathematical structure.",
                    "problem_structure_used": ["structure"], "assumptions": ["testable"],
                    "variables": ["x"], "mathematical_form": "minimize f(x) under explicit constraints",
                    "required_data": ["d"], "baseline": "transparent baseline",
                    "expected_advantage": ["better structure use"], "failure_modes": ["assumption fails"],
                    "validation_plan": ["held-out test"], "computational_cost": "medium",
                    "novelty_source": "problem-specific structure", "risk_level": "medium",
                }
                (bundle / "candidates" / f"c{index}.yaml").write_text(yaml.safe_dump(candidate, sort_keys=False), encoding="utf-8")
            module.build_blind(bundle)
            labels = [item["blind_label"] for item in json.loads((bundle / module.BLIND_FILE).read_text(encoding="utf-8"))["routes"]]
            critic = {"visibility": "blind_critic_input_only", "solver_advocacy_seen": False,
                      "reviews": [{"blind_label": label, "reliability_gate": "PASS", "structure_score": 80, "validation_score": 75, "upside_score": 70} for label in labels]}
            (bundle / "CRITIC_REVIEW.yaml").write_text(yaml.safe_dump(critic), encoding="utf-8")
            (bundle / "PROTOTYPE_RESULTS.yaml").write_text(yaml.safe_dump({"prototypes": [{"prototype_id": f"P-{index}", "blind_label": label, "status": "pass"} for index, label in enumerate(labels, start=1)]}), encoding="utf-8")
            selection = {
                "schema_version": "1.0", "selected_blind_label": labels[0],
                "reliability_gate": "PASS", "reliability_score": 75,
                "competition_upside_score": 70,
                "baseline_comparison": ["wins one observable"],
                "failure_conditions": ["holdout regression"],
                "selection_reason": "Best verified reliability and useful upside.",
                "prototype_ids": ["P-1"],
            }
            (bundle / "ROUTE_SELECTION.yaml").write_text(yaml.safe_dump(selection), encoding="utf-8")
            snapshot = self._route_snapshot(route, bundle, capable=True)
            ledger = bundle / "run" / "REASONING_ROUTE_LEDGER.jsonl"
            assessed = route.assess(
                ledger, snapshot, mode="evaluation_run", task_id="g2-bound",
                stage="analysis", task_class="g2_candidate_generation", gate_id="G2",
            )
            topology = self._topology_receipt(
                route, bundle, task_id="g2-bound", assessment_id=assessed["event_id"],
                topology="independent_candidates", frozen_hash=freeze_hash,
                outputs=[("candidate", path) for path in sorted((bundle / "candidates").glob("*.yaml"))],
            )
            receipt = self._model_receipt(
                bundle, task_id="g2-bound", assessment_id=assessed["event_id"],
                effort="ultra", topology="independent_candidates",
            )
            route.apply(
                ledger, snapshot, receipt, task_id="g2-bound", project_root=bundle,
                topology_receipt_path=topology,
            )
            binding = route.create_bundle_binding(
                ledger, snapshot, bundle, task_id="g2-bound", bundle_kind="g2",
                frozen_input_sha256=freeze_hash,
            )
            (bundle / module.BINDING_FILE).write_text(json.dumps(binding), encoding="utf-8")
            result = module.validate(
                bundle, route_ledger=ledger, capability_snapshot=snapshot, project_root=bundle,
            )
            self.assertEqual(result["candidates"], 2)
            self.assertEqual(result["route"]["topology"], "independent_candidates")

    def test_g5_reviews_are_bound_and_separate(self):
        module = load_script("validate_g5_bundle.py")
        route = load_script("reasoning_route.py")
        with tempfile.TemporaryDirectory() as td:
            bundle = Path(td)
            evidence = {"schema_version": "1.0", "problem_rule_hashes": ["A" * 64], "assumptions": ["a"], "mathematical_model": "m", "results": "r", "figures": [], "baseline": "b", "validation": "v"}
            evidence_path = bundle / "EVIDENCE_PACKAGE.json"
            evidence_path.write_text(json.dumps(evidence), encoding="utf-8")
            evidence_hash = hashlib.sha256(evidence_path.read_bytes()).hexdigest().upper()
            hunter = {"review_id": "FH-1", "role": "failure_hunter", "visibility": "evidence_package_only", "other_review_seen": False, "evidence_package_sha256": evidence_hash, "reliability_score": 92, "hard_failures": []}
            ceiling = {"review_id": "CR-1", "role": "ceiling_reviewer", "visibility": "evidence_package_only", "other_review_seen": False, "evidence_package_sha256": evidence_hash, "competition_upside_score": 78, "ceiling_bottlenecks": []}
            (bundle / "FAILURE_HUNTER.yaml").write_text(yaml.safe_dump(hunter), encoding="utf-8")
            (bundle / "CEILING_REVIEWER.yaml").write_text(yaml.safe_dump(ceiling), encoding="utf-8")
            response_path = bundle / "SOLVER_RESPONSE.yaml"
            response_path.write_text(yaml.safe_dump({"review_ids_addressed": ["FH-1", "CR-1"], "actions": []}), encoding="utf-8")
            response_hash = hashlib.sha256(response_path.read_bytes()).hexdigest().upper()
            (bundle / "INDEPENDENT_VALIDATION.yaml").write_text(yaml.safe_dump({"solver_response_sha256": response_hash, "status": "pass"}), encoding="utf-8")
            decision = {
                "schema_version": "1.0", "execution_mode": "training_run",
                "review_bundle_id": "G5-SMOKE-1", "hard_failures": [],
                "soft_failures": [], "baseline_quality": 75,
                "validation_quality": 92, "innovation_quality": 78,
                "ceiling_bottlenecks": [], "alternative_routes": [],
                "reliability_score": 92, "competition_upside_score": 78,
                "recommended_action": "accept",
            }
            (bundle / "G5_DECISION.yaml").write_text(yaml.safe_dump(decision), encoding="utf-8")
            snapshot = self._route_snapshot(route, bundle, capable=True)
            ledger = bundle / "run" / "REASONING_ROUTE_LEDGER.jsonl"
            assessed = route.assess(
                ledger, snapshot, mode="evaluation_run", task_id="g5-bound",
                stage="coding", task_class="g5_failure_review", gate_id="G5",
            )
            topology = self._topology_receipt(
                route, bundle, task_id="g5-bound", assessment_id=assessed["event_id"],
                topology="dual_review", frozen_hash=evidence_hash,
                outputs=[("failure_hunter", bundle / "FAILURE_HUNTER.yaml"),
                         ("ceiling_reviewer", bundle / "CEILING_REVIEWER.yaml")],
            )
            receipt = self._model_receipt(
                bundle, task_id="g5-bound", assessment_id=assessed["event_id"],
                effort="ultra", topology="dual_review",
            )
            route.apply(
                ledger, snapshot, receipt, task_id="g5-bound", project_root=bundle,
                topology_receipt_path=topology,
            )
            binding = route.create_bundle_binding(
                ledger, snapshot, bundle, task_id="g5-bound", bundle_kind="g5",
                frozen_input_sha256=evidence_hash,
            )
            (bundle / module.BINDING_FILE).write_text(json.dumps(binding), encoding="utf-8")
            result = module.validate(
                bundle, route_ledger=ledger, capability_snapshot=snapshot, project_root=bundle,
            )
            self.assertEqual(result["action"], "accept")
            self.assertEqual(result["route"]["topology"], "dual_review")

    def test_g5_open_hard_failure_blocks_accept(self):
        module = load_script("validate_g5_bundle.py")
        with tempfile.TemporaryDirectory() as td:
            bundle = Path(td)
            evidence = {"schema_version": "1.0", "problem_rule_hashes": ["A" * 64], "assumptions": ["a"], "mathematical_model": "m", "results": "r", "figures": [], "baseline": "b", "validation": "v"}
            evidence_path = bundle / "EVIDENCE_PACKAGE.json"
            evidence_path.write_text(json.dumps(evidence), encoding="utf-8")
            evidence_hash = hashlib.sha256(evidence_path.read_bytes()).hexdigest().upper()
            hunter = {"review_id": "FH-2", "role": "failure_hunter", "visibility": "evidence_package_only", "other_review_seen": False, "evidence_package_sha256": evidence_hash, "reliability_score": 40, "hard_failures": [{"failure_id": "HF-1", "status": "open"}]}
            ceiling = {"review_id": "CR-2", "role": "ceiling_reviewer", "visibility": "evidence_package_only", "other_review_seen": False, "evidence_package_sha256": evidence_hash, "competition_upside_score": 99, "ceiling_bottlenecks": []}
            (bundle / "FAILURE_HUNTER.yaml").write_text(yaml.safe_dump(hunter), encoding="utf-8")
            (bundle / "CEILING_REVIEWER.yaml").write_text(yaml.safe_dump(ceiling), encoding="utf-8")
            response_path = bundle / "SOLVER_RESPONSE.yaml"
            response_path.write_text(yaml.safe_dump({"review_ids_addressed": ["FH-2", "CR-2"], "actions": []}), encoding="utf-8")
            response_hash = hashlib.sha256(response_path.read_bytes()).hexdigest().upper()
            (bundle / "INDEPENDENT_VALIDATION.yaml").write_text(yaml.safe_dump({"solver_response_sha256": response_hash, "status": "pass"}), encoding="utf-8")
            decision = {
                "schema_version": "1.0", "execution_mode": "training_run",
                "review_bundle_id": "G5-SMOKE-FAIL", "hard_failures": ["HF-1"],
                "soft_failures": [], "baseline_quality": 85,
                "validation_quality": 40, "innovation_quality": 99,
                "ceiling_bottlenecks": [], "alternative_routes": [],
                "reliability_score": 40, "competition_upside_score": 99,
                "recommended_action": "accept",
            }
            (bundle / "G5_DECISION.yaml").write_text(yaml.safe_dump(decision), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "open hard failures"):
                module.validate(bundle)

    def test_g5_rejects_drifted_external_artifact(self):
        module = load_script("validate_g5_bundle.py")
        with tempfile.TemporaryDirectory() as td:
            case = Path(td)
            bundle = case / "review" / "g5" / "v1"
            bundle.mkdir(parents=True)
            result = case / "results" / "candidate.json"
            result.parent.mkdir()
            result.write_text('{"metric": 1}\n', encoding="utf-8")
            result_hash = hashlib.sha256(result.read_bytes()).hexdigest().upper()
            evidence = {
                "schema_version": "1.0",
                "problem_rule_hashes": ["A" * 64],
                "assumptions": ["a"],
                "mathematical_model": "m",
                "results": {"path": "results/candidate.json", "sha256": result_hash},
                "figures": [], "baseline": "b", "validation": [],
            }
            evidence_path = bundle / "EVIDENCE_PACKAGE.json"
            evidence_path.write_text(json.dumps(evidence), encoding="utf-8")
            evidence_hash = hashlib.sha256(evidence_path.read_bytes()).hexdigest().upper()
            hunter = {"review_id": "FH-3", "role": "failure_hunter", "visibility": "evidence_package_only", "other_review_seen": False, "evidence_package_sha256": evidence_hash, "reliability_score": 92, "hard_failures": []}
            ceiling = {"review_id": "CR-3", "role": "ceiling_reviewer", "visibility": "evidence_package_only", "other_review_seen": False, "evidence_package_sha256": evidence_hash, "competition_upside_score": 78, "ceiling_bottlenecks": []}
            (bundle / "FAILURE_HUNTER.yaml").write_text(yaml.safe_dump(hunter), encoding="utf-8")
            (bundle / "CEILING_REVIEWER.yaml").write_text(yaml.safe_dump(ceiling), encoding="utf-8")
            response_path = bundle / "SOLVER_RESPONSE.yaml"
            response_path.write_text(yaml.safe_dump({"review_ids_addressed": ["FH-3", "CR-3"], "actions": []}), encoding="utf-8")
            response_hash = hashlib.sha256(response_path.read_bytes()).hexdigest().upper()
            (bundle / "INDEPENDENT_VALIDATION.yaml").write_text(yaml.safe_dump({"solver_response_sha256": response_hash, "status": "pass"}), encoding="utf-8")
            decision = {
                "schema_version": "1.0", "execution_mode": "training_run",
                "review_bundle_id": "G5-SMOKE-DRIFT", "hard_failures": [],
                "soft_failures": [], "baseline_quality": 75,
                "validation_quality": 92, "innovation_quality": 78,
                "ceiling_bottlenecks": [], "alternative_routes": [],
                "reliability_score": 92, "competition_upside_score": 78,
                "recommended_action": "accept",
            }
            (bundle / "G5_DECISION.yaml").write_text(yaml.safe_dump(decision), encoding="utf-8")
            self.assertEqual(module.validate(bundle)["artifact_bindings_checked"], 1)
            result.write_text('{"metric": 2}\n', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "artifact hash mismatch"):
                module.validate(bundle)

    def test_cleanup_requires_exact_plan_hash_and_explicit_target(self):
        module = load_script("cleanup_artifacts.py")
        with tempfile.TemporaryDirectory() as td:
            project = Path(td)
            target = project / "tmp" / "run" / "scratch"
            target.mkdir(parents=True)
            (target / "x.txt").write_text("temporary", encoding="utf-8")
            plan = {"schema_version": "1.0", "targets": [{
                "path": "tmp/run/scratch", "expected_tree_sha256": module.tree_hash(target),
                "durable_replacement_id": "ART-DURABLE", "lifecycle_disposable_event_hash": "B" * 64,
            }]}
            self.assertEqual(module.validate_plan(project, plan), [target.resolve()])
            alias = project / ".." / project.name
            self.assertEqual(module.validate_plan(alias, plan), [target.resolve()])
            plan["targets"][0]["path"] = "."
            with self.assertRaises(ValueError):
                module.validate_plan(project, plan)

    def test_artifact_lifecycle_requires_promotion_before_disposal(self):
        module = load_script("artifact_lifecycle.py")
        def make(seq, kind, artifact, previous, replacement=None):
            event = {"sequence": seq, "run_id": "r", "event_type": kind, "artifact_id": artifact,
                     "path": artifact, "sha256": "A" * 64, "timestamp": "2026-08-31T00:00:00+08:00",
                     "durable_replacement_id": replacement, "previous_event_hash": previous}
            event["event_hash"] = module.event_hash(event)
            return event
        e1 = make(1, "produced", "scratch", module.ZERO)
        e2 = make(2, "promoted", "durable", e1["event_hash"])
        e3 = make(3, "disposable", "scratch", e2["event_hash"], "durable")
        self.assertEqual(module.verify([e1, e2, e3])["scratch"], "disposable")
        bad = make(2, "disposable", "scratch", e1["event_hash"], "missing")
        with self.assertRaises(ValueError):
            module.verify([e1, bad])


if __name__ == "__main__":
    unittest.main()
