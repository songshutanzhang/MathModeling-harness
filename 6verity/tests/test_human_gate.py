from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "_references" / "scripts" / "human_gate.py"
ROUTER = ROOT / "_references" / "harness" / "scripts" / "reasoning_route.py"


def load_router():
    spec = importlib.util.spec_from_file_location("reasoning_route", ROUTER)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    return module


def packet_text(gate: str) -> str:
    return f"""# {gate} 人工审批包

## 决策范围

审批当前关键决策。

## 输入及版本

problem.txt 当前测试版本。

## 候选方案与备选方案

比较透明基线和复杂模型。

## 推荐方案与依据

先验证基线，再依据证据升级。

## 关键假设与风险

输入完整，评价指标有效。

## 验证计划

比较误差、约束和敏感性。

## 回拨点

使用审批前快照。

## 推理强度路由（独立于审批）

引用独立路由账本的已完成事件。

## AI 合规分类

AI 辅助整理，参赛队作出决定。
"""


class HumanGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.project = Path(self.temp.name)
        self.gate_file = self.project / "compliance" / "HUMAN_GATES.json"
        self.source = self.project / "problem.txt"
        self.source.write_text("original problem", encoding="utf-8")
        self.router = load_router()
        source = {
            "schema_version": "1.0", "captured_at": "2026-09-04T00:00:00+00:00",
            "runtime_id": "test", "current": {"model_id": "model", "reasoning_effort": "high"},
            "models": [{
                "model_id": "model", "supported_reasoning_efforts": ["high", "max", "ultra"],
                "supports_task_override": True, "supports_mid_conversation_update": True,
            }],
            "supports_effective_setting_receipt": True,
            "supported_topologies": ["single", "independent_candidates", "dual_review", "ensemble"],
            "topology_effort_requirements": {
                "independent_candidates": ["ultra"], "dual_review": ["ultra"], "ensemble": ["ultra"],
            },
            "quota_policy": {"mode": "quality_first", "hard_budget_present": False},
        }
        self.snapshot = self.project / "run" / "MODEL_CAPABILITY_SNAPSHOT.json"
        self.snapshot.parent.mkdir(parents=True)
        self.snapshot.write_text(json.dumps(self.router.seal_snapshot(source)), encoding="utf-8")
        self.ledger = self.project / "run" / "REASONING_ROUTE_LEDGER.jsonl"
        result = self.run_gate(
            "init", "--file", str(self.gate_file.relative_to(self.project)),
            "--project-root", str(self.project),
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def run_gate(self, *args: str) -> subprocess.CompletedProcess[str]:
        environment = os.environ.copy()
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        return subprocess.run(
            [sys.executable, str(SCRIPT), *args], text=True, encoding="utf-8",
            errors="replace", capture_output=True, check=False, env=environment,
        )

    def prepare_gate(self, gate: str, suffix: str = "001") -> tuple[Path, Path]:
        packet = self.project / "compliance" / "gates" / f"{gate}-{suffix}.md"
        checkpoint = self.project / "compliance" / "checkpoints" / f"{gate}-{suffix}"
        packet.parent.mkdir(parents=True, exist_ok=True)
        checkpoint.mkdir(parents=True, exist_ok=True)
        packet.write_text(packet_text(gate), encoding="utf-8")
        (checkpoint / "snapshot.txt").write_text(f"checkpoint {gate}", encoding="utf-8")
        return packet, checkpoint

    def prepare_route(self, gate: str, suffix: str = "001") -> None:
        task_id = f"{gate.lower()}-{suffix}"
        assessed = self.router.assess(
            self.ledger, self.snapshot, mode="evaluation_run", task_id=task_id,
            stage="analysis" if gate in {"G1", "G2", "G3"} else "verification",
            task_class="g1_interpretation" if gate == "G1" else "routine_analysis",
            gate_id=gate, requested_effort="high", requested_topology="single",
        )
        receipt = self.project / "run" / "route-receipts" / f"{task_id}.json"
        receipt.parent.mkdir(parents=True, exist_ok=True)
        receipt.write_text(json.dumps({
            "schema_version": "1.0", "receipt_id": f"MR-{task_id}",
            "captured_at": "2026-09-04T00:01:00+00:00",
            "source": "reasoning_effort_interface", "task_id": task_id,
            "assessment_event_id": assessed["event_id"], "effective_model_id": "model",
            "effective_reasoning_effort": "high", "effective_topology": "single",
        }), encoding="utf-8")
        self.router.apply(
            self.ledger, self.snapshot, receipt, task_id=task_id, project_root=self.project,
        )
        output = self.project / "run" / "route-outputs" / f"{task_id}.json"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text('{"status":"done"}\n', encoding="utf-8")
        self.router.complete(
            self.ledger, task_id=task_id, project_root=self.project, outputs=[str(output)]
        )
        self.router.reassess(self.ledger, self.snapshot, task_id=task_id)

    def approve(
        self, gate: str, suffix: str = "001",
        artifact: Path | list[Path] | None = None, prepare_route: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        if prepare_route:
            self.prepare_route(gate, suffix)
        packet, checkpoint = self.prepare_gate(gate, suffix)
        approval_artifacts = artifact if isinstance(artifact, list) else [artifact or self.source]
        arguments = [
            "approve", "--file", str(self.gate_file.relative_to(self.project)),
            "--project-root", str(self.project), "--gate", gate,
            "--decision-id", f"D-{gate}-{suffix}", "--packet", str(packet.relative_to(self.project)),
            "--selected-option", "采用基线方案", "--rationale", "以透明基线验证约束并保留回拨点",
            "--verification", "执行基线比较、约束检查和敏感性分析",
            "--rollback-checkpoint", str(checkpoint.relative_to(self.project)),
            "--approval-evidence", f"当前任务中用户明确批准 {gate} 的方案",
            "--ai-involvement", "yes", "--ai-category", "建模方案辅助分析",
            "--route-ledger", str(self.ledger.relative_to(self.project)),
            "--capability-snapshot", str(self.snapshot.relative_to(self.project)),
        ]
        for item in approval_artifacts:
            arguments.extend(["--artifact", str(item.relative_to(self.project))])
        return self.run_gate(*arguments)

    def verify(self, *required: str) -> subprocess.CompletedProcess[str]:
        return self.run_gate(
            "verify", "--file", str(self.gate_file.relative_to(self.project)),
            "--project-root", str(self.project), "--require", *required, "--check-artifacts",
        )

    def test_gate_requires_completed_external_route_event(self) -> None:
        result = self.approve("G1", prepare_route=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("reasoning route ledger is empty", result.stdout)

    def test_sequential_approval_and_verification_pass(self) -> None:
        self.assertEqual(self.approve("G1").returncode, 0)
        self.assertEqual(self.approve("G2").returncode, 0)
        result = self.verify("G1", "G2")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        document = json.loads(self.gate_file.read_text(encoding="utf-8"))
        self.assertEqual(document["schema_version"], "2.0")
        self.assertNotIn("reasoning_route", document["gates"]["G1"])
        self.assertIn("route_reference", document["gates"]["G1"]["decision"])

    def test_cannot_approve_out_of_order(self) -> None:
        result = self.approve("G2")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("before G1", result.stdout)

    def test_changed_artifact_makes_approval_stale(self) -> None:
        self.assertEqual(self.approve("G1").returncode, 0)
        self.source.write_text("changed problem", encoding="utf-8")
        result = self.verify("G1")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("hash changed", result.stdout)

    def test_route_ledger_tampering_makes_gate_stale(self) -> None:
        self.assertEqual(self.approve("G1").returncode, 0)
        lines = self.ledger.read_text(encoding="utf-8").splitlines()
        event = json.loads(lines[1])
        event["limitation"] = "tampered"
        lines[1] = json.dumps(event)
        self.ledger.write_text("\n".join(lines) + "\n", encoding="utf-8")
        result = self.verify("G1")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("route ledger event hash mismatch", result.stdout)

    def test_gate_approval_does_not_create_or_apply_route(self) -> None:
        before = len(self.router.read_ledger(self.ledger))
        self.assertEqual(self.approve("G1", prepare_route=False).returncode, 1)
        self.prepare_route("G1")
        before = len(self.router.read_ledger(self.ledger))
        self.assertEqual(self.approve("G1", prepare_route=False).returncode, 0)
        self.assertEqual(len(self.router.read_ledger(self.ledger)), before)

    def test_new_upstream_approval_invalidates_downstream(self) -> None:
        self.assertEqual(self.approve("G1").returncode, 0)
        self.assertEqual(self.approve("G2").returncode, 0)
        result = self.run_gate(
            "invalidate", "--file", str(self.gate_file.relative_to(self.project)),
            "--project-root", str(self.project), "--gate", "G1",
            "--reason", "题意解释发生实质变化", "--trigger", "scope_changed",
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.approve("G1", "002").returncode, 0)
        verify = self.verify("G1", "G2")
        self.assertNotEqual(verify.returncode, 0)
        self.assertIn("required gate G2 is not approved (invalidated)", verify.stdout)

    def test_audit_chain_tampering_is_detected(self) -> None:
        self.assertEqual(self.approve("G1").returncode, 0)
        document = json.loads(self.gate_file.read_text(encoding="utf-8"))
        document["audit_chain"][-1]["payload"]["decision"]["rationale"] = "被修改"
        self.gate_file.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
        result = self.verify("G1")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("audit event hash mismatch", result.stdout)

    def test_full_g1_to_g6_flow_and_final_file_lock(self) -> None:
        for gate in ("G1", "G2", "G3", "G4", "G5"):
            result = self.approve(gate)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        final_pdf = self.project / "submission" / "论文.pdf"
        final_docx = self.project / "submission" / "论文.docx"
        final_manifest = self.project / "submission" / "FINAL_DELIVERY.json"
        final_pdf.parent.mkdir(parents=True)
        final_pdf.write_bytes(b"%PDF-1.4\nfinal\n")
        final_docx.write_bytes(b"editable")
        final_manifest.write_text('{"source_loop":"loop-001"}', encoding="utf-8")
        result = self.approve("G6", artifact=[final_docx, final_pdf, final_manifest])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.verify("G1", "G2", "G3", "G4", "G5", "G6").returncode, 0)
        final_pdf.write_bytes(b"changed")
        stale = self.verify("G6")
        self.assertNotEqual(stale.returncode, 0)
        self.assertIn("hash changed", stale.stdout)

    def test_g6_requires_word_pdf_and_final_manifest(self) -> None:
        for gate in ("G1", "G2", "G3", "G4", "G5"):
            self.assertEqual(self.approve(gate).returncode, 0)
        final_pdf = self.project / "submission" / "论文.pdf"
        final_manifest = self.project / "submission" / "FINAL_DELIVERY.json"
        final_pdf.parent.mkdir(parents=True)
        final_pdf.write_bytes(b"%PDF")
        final_manifest.write_text("{}", encoding="utf-8")
        result = self.approve("G6", artifact=[final_pdf, final_manifest])
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("final editable DOCX", result.stdout)


if __name__ == "__main__":
    unittest.main()
