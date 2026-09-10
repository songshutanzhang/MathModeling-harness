from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[1]


def load(name):
    path = ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"acceptance_{name}", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    return module


def write_json(path: Path, value: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    return path


def test_preflight_fails_before_compute_for_missing_active_dependency_and_route_capability(tmp_path):
    module = load("dependency_preflight")
    route = load("reasoning_route")
    repo, active = tmp_path / "repo", tmp_path / "active"
    for root in (repo, active):
        (root / "1start-mathmodel").mkdir(parents=True)
        (root / "1start-mathmodel/SKILL.md").write_text(
            "[required](../_references/harness/RUNTIME_CONTRACT.md)", encoding="utf-8")
    (repo / "_references/harness").mkdir(parents=True)
    (repo / "_references/harness/RUNTIME_CONTRACT.md").write_text("contract", encoding="utf-8")
    source = {
        "schema_version": "1.0", "captured_at": "2026-09-08T00:00:00+00:00",
        "runtime_id": "limited", "current": {"model_id": "m", "reasoning_effort": "medium"},
        "models": [{"model_id": "m", "supported_reasoning_efforts": ["medium"],
                    "supports_task_override": False, "supports_mid_conversation_update": False}],
        "supports_effective_setting_receipt": False, "supported_topologies": ["single"],
        "topology_effort_requirements": {},
        "quota_policy": {"mode": "hard_budget", "hard_budget_present": True},
    }
    snapshot = write_json(repo / "snapshot.json", route.seal_snapshot(source))
    result = module.inspect(repo, active, entries=["1start-mathmodel/SKILL.md"],
                            capability_snapshot=snapshot,
                            route_requirements=[{"stage": "G5", "reasoning_effort": "ultra",
                                                 "topology": "dual_review", "receipt_required": True}])
    assert result["status"] == "blocked"
    assert any("RUNTIME_CONTRACT.md" in reason for reason in result["failures"])
    assert result["routes"][0]["status"] == "blocked"
    assert {"effort unavailable: ultra", "topology unavailable: dual_review",
            "effective-setting receipt interface unavailable"} <= set(result["routes"][0]["reasons"])


def make_plan(project: Path, source: Path, data: Path, *, include_long=False) -> Path:
    code = (
        "import os,pathlib; root=pathlib.Path(os.environ['HARNESS_PROJECT_ROOT']); "
        "out=pathlib.Path(os.environ['HARNESS_OUTPUT_DIR'])/'results/value.txt'; "
        "out.parent.mkdir(parents=True,exist_ok=True); "
        "out.write_text((root/'src/core.py').read_text()+(root/'data/input.txt').read_text(),encoding='utf-8')"
    )
    tasks = [{
        "task_id": "numeric", "stage": "coding", "kind": "compute",
        "command": [sys.executable, "-c", code], "dependencies": [],
        "inputs": [data.relative_to(project).as_posix()],
        "sources": [source.parent.relative_to(project).as_posix()],
        "outputs": ["results/value.txt"], "packages": [], "configuration": {"precision": 1},
        "max_attempts": 3, "estimated_seconds": 0.01,
    }]
    if include_long:
        tasks.append({
            "task_id": "long", "stage": "coding", "kind": "compute",
            "command": [sys.executable, "-c", "raise SystemExit(99)"], "dependencies": [],
            "inputs": [data.relative_to(project).as_posix()], "sources": [source.parent.relative_to(project).as_posix()],
            "outputs": ["results/long.txt"], "packages": [], "configuration": {}, "max_attempts": 3,
        })
    return write_json(project / "run/plan.json", {
        "schema_version": "1.0", "run_id": "run-1", "experiment_id": "experiment-1",
        "problem_identity": "problem-v1", "objective_identity": "objective-v1",
        "case_id": "synthetic", "dataset_role": "development", "budget_seconds": 30,
        "final_review_reserve_seconds": 5, "tasks": tasks,
    })


def test_runner_recovers_partial_output_and_reuses_only_exact_transitive_identity(tmp_path):
    runner = load("run_orchestrator")
    project = tmp_path / "case"; project.mkdir()
    source = project / "src/core.py"; source.parent.mkdir(); source.write_text("v1-", encoding="utf-8")
    data = project / "data/input.txt"; data.parent.mkdir(); data.write_text("data", encoding="utf-8")
    paper = project / "paper/paper.md"; paper.parent.mkdir(); paper.write_text("draft", encoding="utf-8")
    approval = project / "compliance/approval.json"; approval.parent.mkdir(); approval.write_text("approved", encoding="utf-8")
    approval_hash = hashlib.sha256(approval.read_bytes()).hexdigest()
    plan = make_plan(project, source, data, include_long=True)
    preflight = write_json(project / "run/preflight.json", {"status": "executable", "failures": []})
    state = project / ".runtime"
    runner.initialize(project, state, plan, preflight)
    first = runner.run_task(project, state, "numeric")
    assert first["status"] == "completed"
    paper.write_text("wording changed", encoding="utf-8")
    assert runner.run_task(project, state, "numeric")["status"] == "reused"
    source.write_text("v2-", encoding="utf-8")
    changed = runner.run_task(project, state, "numeric")
    assert changed["status"] == "completed" and changed["attempt"] == 2
    assert (project / "results/value.txt").read_text(encoding="utf-8") == "v2-data"
    revised = json.loads(plan.read_text(encoding="utf-8")); revised["operator_note"] = "wording only"
    write_json(plan, revised)
    assert runner.initialize(project, state, plan, preflight)["revision"] == 2
    assert runner.run_task(project, state, "numeric")["status"] == "reused"
    revised["tasks"][0]["configuration"]["precision"] = 2
    write_json(plan, revised)
    assert runner.initialize(project, state, plan, preflight)["revision"] == 3
    assert runner.run_task(project, state, "numeric")["attempt"] == 3
    revised["objective_identity"] = "changed-objective"
    write_json(plan, revised)
    with pytest.raises(ValueError, match="objective_identity changed"):
        runner.initialize(project, state, plan, preflight)
    revised["objective_identity"] = "objective-v1"
    write_json(plan, revised)

    # Simulate a hard-killed attempt that left only a staging fragment and a running marker.
    staging = state / "staging/long/attempt-0001"; staging.mkdir(parents=True)
    (staging / "results").mkdir(); (staging / "results/long.txt").write_text("half", encoding="utf-8")
    marker = {"task_id": "long", "attempt": 1, "attempt_id": "run-1:long:1:dead",
              "task_identity": "D" * 64, "staging": str(staging), "started_at": "2026-09-08T00:00:00+00:00"}
    runner.atomic_json(state / "running/long.json", marker, immutable=True)
    runner.append_event(state, "task_started", {**marker, "revision": 1})
    assert runner.status(project, state)["tasks"]["long"]["state"] == "interrupted_or_running"
    recovered = runner.recover(project, state)
    assert recovered["interrupted_tasks"] == ["long"]
    assert not (project / "results/long.txt").exists()
    assert hashlib.sha256(approval.read_bytes()).hexdigest() == approval_hash
    telemetry = load("run_telemetry").events(state / "telemetry")
    assert telemetry and telemetry[0]["metrics"]["input_tokens"] == {"value": None, "evidence": "missing"}


@pytest.mark.skipif(os.name != "nt", reason="Windows process-tree interruption contract")
def test_real_killed_process_leaves_no_reusable_success(tmp_path):
    runner = load("run_orchestrator")
    project = tmp_path / "case"; project.mkdir()
    source = project / "src/core.py"; source.parent.mkdir(); source.write_text("source", encoding="utf-8")
    data = project / "data/input.txt"; data.parent.mkdir(); data.write_text("data", encoding="utf-8")
    command = (
        "import os,pathlib,time; p=pathlib.Path(os.environ['HARNESS_OUTPUT_DIR'])/'results/long.txt'; "
        "p.parent.mkdir(parents=True,exist_ok=True); p.write_text('half',encoding='utf-8'); time.sleep(60)"
    )
    plan = write_json(project / "run/plan.json", {
        "schema_version":"1.0", "run_id":"kill-run", "experiment_id":"kill-experiment",
        "problem_identity":"problem-v1", "objective_identity":"objective-v1",
        "tasks":[{"task_id":"long", "stage":"coding", "kind":"compute",
                  "command":[sys.executable,"-c",command], "dependencies":[],
                  "inputs":["data/input.txt"], "sources":["src"], "outputs":["results/long.txt"],
                  "configuration":{}, "max_attempts":2}],
    })
    preflight = write_json(project / "run/preflight.json", {"status":"executable", "failures":[]})
    state = project / ".runtime"; runner.initialize(project,state,plan,preflight)
    process = subprocess.Popen(
        [sys.executable, str(ROOT / "scripts/run_orchestrator.py"), "run",
         "--project-root", str(project), "--state-dir", str(state), "--task-id", "long"],
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    partial = state / "staging/long/attempt-0001/results/long.txt"
    deadline = time.monotonic() + 10
    while not partial.exists() and time.monotonic() < deadline:
        time.sleep(0.05)
    assert partial.exists()
    subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                   check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    process.wait(timeout=10)
    assert runner.status(project,state)["tasks"]["long"]["state"] == "interrupted_or_running"
    runner.recover(project,state)
    assert not (project / "results/long.txt").exists()
    assert runner.status(project,state)["tasks"]["long"]["state"] == "pending"


def make_g5_bundle(bundle: Path):
    validator = load("validate_g5_bundle")
    write_json(bundle / "EVIDENCE_PACKAGE.json", {
        "schema_version": "1.0", "problem_rule_hashes": ["A" * 64], "assumptions": [],
        "mathematical_model": "m", "results": "r", "figures": [], "baseline": "b", "validation": [],
    })
    evidence_hash = validator.sha(bundle / "EVIDENCE_PACKAGE.json")
    write_json(bundle / "FAILURE_HUNTER.yaml", {
        "review_id": "FH-1", "role": "failure_hunter", "visibility": "evidence_package_only",
        "other_review_seen": False, "evidence_package_sha256": evidence_hash,
        "reliability_score": 88,
        "hard_failures": [{"failure_id": "HF-1", "status": "open"}, {"failure_id": "HF-2", "status": "open"}],
    })
    write_json(bundle / "SOLVER_RESPONSE.yaml", {"review_ids_addressed": ["FH-1"], "repair": "implemented"})
    response_hash = validator.sha(bundle / "SOLVER_RESPONSE.yaml")
    write_json(bundle / "INDEPENDENT_VALIDATION.yaml", {
        "solver_response_sha256": response_hash, "status": "pass", "reviewer_role": "independent_validator",
        "reviewer_id": "IV-1", "verified_failure_ids": ["HF-1"],
    })
    evidence = bundle / "repair-proof.json"; write_json(evidence, {"check": "pass"})
    return validator, evidence


def test_g5_append_only_disposition_closes_only_authorized_current_response(tmp_path):
    bundle = tmp_path / "bundle"; bundle.mkdir()
    validator, evidence = make_g5_bundle(bundle)
    disposition = load("g5_disposition")
    hunter_hash = hashlib.sha256((bundle / "FAILURE_HUNTER.yaml").read_bytes()).hexdigest()
    event = disposition.append(bundle, bundle, event_id="DISP-1", finding_id="HF-1", action="closed",
                               reviewer_id="IV-1", verification_scope="recomputed the repaired invariant",
                               evidence_paths=[evidence.name])
    assert hashlib.sha256((bundle / "FAILURE_HUNTER.yaml").read_bytes()).hexdigest() == hunter_hash
    write_json(bundle / "G5_DECISION.yaml", {
        "schema_version": "1.0", "execution_mode": "training_run", "review_bundle_id": "G5-DISP",
        "hard_failures": ["HF-2"], "soft_failures": [], "validation_quality": 88,
        "reliability_score": 88, "recommended_action": "local_fix",
        "disposition_chain_head": event["event_hash"],
    })
    result = validator.validate(bundle, reliability_only=True)
    assert result["open_hard_failures"] == 1 and result["dispositions"]["statuses"]["HF-1"] == "closed"

    old_response = (bundle / "SOLVER_RESPONSE.yaml").read_bytes()
    (bundle / "SOLVER_RESPONSE.yaml").write_bytes(old_response + b" ")
    with pytest.raises(ValueError, match="solver response"):
        validator.validate(bundle, reliability_only=True)
    (bundle / "SOLVER_RESPONSE.yaml").write_bytes(old_response)
    independent = json.loads((bundle / "INDEPENDENT_VALIDATION.yaml").read_text(encoding="utf-8"))
    independent["reviewer_role"] = "solver"
    write_json(bundle / "INDEPENDENT_VALIDATION.yaml", independent)
    with pytest.raises(ValueError, match="old independent validation"):
        validator.validate(bundle, reliability_only=True)
    other = tmp_path / "solver-bundle"; other.mkdir()
    _validator, other_evidence = make_g5_bundle(other)
    invalid = json.loads((other / "INDEPENDENT_VALIDATION.yaml").read_text(encoding="utf-8"))
    invalid["reviewer_role"] = "solver"
    write_json(other / "INDEPENDENT_VALIDATION.yaml", invalid)
    with pytest.raises(ValueError, match="only a passing independent validator"):
        disposition.append(other, other, event_id="SOLVER-CLOSE", finding_id="HF-1", action="closed",
                           reviewer_id="IV-1", verification_scope="solver self-reported closure",
                           evidence_paths=[other_evidence.name])


def candidate(project: Path, candidate_id: str, level: str, role: str, value: float, *,
              eligible_for=None, budget=27, ablation_of=None) -> dict:
    artifact = project / f"artifacts/{candidate_id}.json"
    write_json(artifact, {"value": value})
    record = load("runtime_support").record(project, artifact.relative_to(project))
    value_record = {
        "schema_version": "1.0", "candidate_id": candidate_id, "problem_level": level,
        "family": candidate_id.split("-")[0], "role": role,
        "objective": {"name": "power_per_area", "direction": "maximize", "value": value},
        "feasible": True, "evaluator": {"id": "eval-1", "sha256": "A" * 64},
        "budget": {"evaluations": budget}, "precision": {"samples": 1024},
        "sample_group": "common-seed-1", "artifact": record,
    }
    if eligible_for: value_record["eligible_for"] = eligible_for
    if ablation_of: value_record["ablation_of"] = ablation_of
    return value_record


def test_candidate_promotion_is_fair_auditable_and_nested_nonregressing(tmp_path):
    registry = load("candidate_registry")
    project = tmp_path / "case"; project.mkdir(); directory = project / "candidates"
    values = [
        candidate(project, "base-q3", "q3", "strong_baseline", 0.50),
        candidate(project, "abl-q3", "q3", "ablation", 0.51, ablation_of="joint-q3"),
        candidate(project, "joint-q3", "q3", "candidate", 0.52),
        candidate(project, "inc-q2", "q2", "incumbent", 0.55, eligible_for=["q3"]),
        candidate(project, "unfair-q3", "q3", "candidate", 0.90, budget=2),
    ]
    for item in values:
        source = write_json(project / f"source/{item['candidate_id']}.json", item)
        registry.register(directory, project, source)
    result = registry.promote(directory, project, problem_level="q3", incumbent_id="inc-q2")
    assert result["selected_candidate_id"] == "inc-q2"
    assert result["nested_nonregression_pass"]
    assert any(item["candidate_id"] == "unfair-q3" and "comparison_protocol" in item["reasons"] for item in result["excluded"])
    assert "abl-q3" in result["ranked_candidate_ids"]


def test_contest_year_router_and_p2_development_evidence(tmp_path):
    rules = load("contest_rules")
    project = tmp_path / "case"; project.mkdir()
    official = project / "inputs/format2023.doc"; official.parent.mkdir(); official.write_bytes(b"official-2023-format")
    historical = rules.resolve(competition="cumcm", year=2023, mode="evaluation_run",
                               knowledge_state="exposed", project_root=project, official_format=official)
    assert historical["fixed_ai_wording"] == "not_applicable"
    assert historical["checker"] == "historical_format_and_delivery"
    assert historical["source"]["sha256"] == hashlib.sha256(official.read_bytes()).hexdigest().upper()
    current = rules.resolve(competition="cumcm", year=2026, mode="live_competition", knowledge_state="unexposed")
    assert current["fixed_ai_wording"] == "required" and current["source"]["sha256"]

    demo = load("run_p2_development_demo").run()
    assert all(demo["acceptance"].values())
    assert demo["dataset_role"] == "synthetic_development_not_2023_evaluation"
    assert demo["three_zone_joint_search"]["optimality_gap"] == 0
    assert demo["objective_gain"] > 0 and demo["complexity_decision"] == "retain"


def test_final_review_tail_budget_blocks_exploration_but_allows_frozen_review(tmp_path):
    runner = load("run_orchestrator")
    project = tmp_path / "case"; project.mkdir()
    frozen = project / "submission/frozen.txt"; frozen.parent.mkdir(); frozen.write_text("v1", encoding="utf-8")
    writer = (
        "import os,pathlib; p=pathlib.Path(os.environ['HARNESS_OUTPUT_DIR'])/'review/final.txt'; "
        "p.parent.mkdir(parents=True,exist_ok=True); p.write_text('checked',encoding='utf-8')"
    )
    plan = write_json(project / "run/plan.json", {
        "schema_version": "1.0", "run_id": "tail-run", "experiment_id": "tail-experiment",
        "problem_identity": "problem-v1", "objective_identity": "objective-v1",
        "budget_seconds": 10, "final_review_reserve_seconds": 5,
        "tasks": [
            {"task_id": "explore", "stage": "coding", "kind": "compute",
             "command": [sys.executable, "-c", writer], "dependencies": [], "inputs": ["submission/frozen.txt"],
             "sources": [], "outputs": ["review/explore.txt"], "configuration": {}, "estimated_seconds": 6},
            {"task_id": "final", "stage": "verification", "kind": "final_review",
             "command": [sys.executable, "-c", writer], "dependencies": [], "inputs": ["submission/frozen.txt"],
             "sources": [], "outputs": ["review/final.txt"], "configuration": {}, "estimated_seconds": 4},
        ],
    })
    preflight = write_json(project / "run/preflight.json", {"status": "executable", "failures": []})
    state = project / ".runtime"; runner.initialize(project, state, plan, preflight)
    with pytest.raises(ValueError, match="final-review reserve"):
        runner.run_task(project, state, "explore")
    first = runner.run_task(project, state, "final")
    assert first["status"] == "completed"
    frozen.write_text("v2", encoding="utf-8")
    assert runner.status(project, state)["tasks"]["final"]["state"] == "stale"
    second = runner.run_task(project, state, "final")
    assert second["status"] == "completed" and second["attempt"] == 2
