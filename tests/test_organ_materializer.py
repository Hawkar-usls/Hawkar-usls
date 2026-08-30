from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from janus_spi.activator import canonical_hash
from janus_spi.organ_materializer import OrganMaterializer, OrganMaterializationError


SHAS = {
    "anomaly_lab": "1" * 40,
    "left_context": "2" * 40,
    "orchestrator": "3" * 40,
}


def model_lock():
    members = {}
    for key, repo, role in [
        ("anomaly_lab", "Hawkar-usls/TOPA", "ANOMALY_LAB"),
        ("left_context", "Hawkar-usls/Hrain", "STRUCTURAL_CONTEXT_HEMISPHERE"),
        ("orchestrator", "Hawkar-usls/Janus-Demiurge", "SPIRAL_AGENT_CONTROL_PLANE"),
    ]:
        members[key] = {
            "kind": "ORGAN",
            "repository": repo,
            "member_class": "CORE",
            "role": role,
            "head_sha": SHAS[key],
            "branch": "main",
            "resolved_branch": "main",
            "load_mode": "REQUIRED_BOOT_PRESENCE",
        }
    return {
        "schema": "janus.activator.model_lock.v1",
        "model_id": "JANUS",
        "model_digest": "a" * 64,
        "ready": True,
        "terminal": "JANUS_MODEL_FABRIC_LOCKED_AT_HOME",
        "members": members,
        "external_effect_authorized": False,
        "physical_runtime_effect_authorized": False,
    }


def runtime_receipt(lock):
    row = {
        "schema": "janus.activator.model_runtime_receipt.v1",
        "model_digest": lock["model_digest"],
        "model_lock_hash": canonical_hash(lock),
        "runtime_receipt_hash": "b" * 64,
        "activation_id": "act-1",
        "active_members": ["anomaly_lab", "left_context", "orchestrator"],
        "routing_selects_activity_not_membership": True,
        "membership_was_locked_before_activation": True,
        "dispatch_authorized": False,
        "command_authority_granted": False,
        "world_truth_authority_granted": False,
        "external_effect_authorized": False,
        "physical_runtime_effect_authorized": False,
    }
    return row


def constitution():
    return {
        "schema": "janus.activator.organ_materialization_constitution.v1",
        "terminal_success": "JANUS_ACTIVE_ORGANS_MATERIALIZED_EXACT_SHA",
        "initial_adapters": {
            "anomaly_lab": {
                "repository": "Hawkar-usls/TOPA",
                "adapter": "TOPA_DETECTIVE_SELF_TEST",
                "admitted_entrypoint": "tools/topa_detective_spider.py",
                "argv": ["--mode", "DETECTIVE", "--self-test"],
                "expected_identity": "TOPA_DETECTIVE_SPIDER",
            },
            "left_context": {
                "repository": "Hawkar-usls/Hrain",
                "adapter": "HRAIN_READ_ONLY_CONTEXT_CAPSULE",
                "read_only_paths": [".janus/JANUS_ORGANISM_LINK.json", ".janus/TOPA_SPIDER_LINK.json", ".janus/SPIDER_HOME.json"],
            },
            "orchestrator": {
                "repository": "Hawkar-usls/Janus-Demiurge",
                "adapter": "DEMIURGE_READ_ONLY_CONTROL_CAPSULE",
                "read_only_paths": [".janus/JANUS_ORGANISM_LINK.json", "tools/activator_readonly_execution.py"],
            },
        },
    }


class FixtureMaterializer(OrganMaterializer):
    def __init__(self, *args, fixture_roots, actual_shas=None, **kwargs):
        self.fixture_roots = fixture_roots
        self.actual_shas = actual_shas or dict(SHAS)
        super().__init__(*args, **kwargs)

    def _checkout_exact(self, key, member):
        sha = self.actual_shas[key]
        expected = str(member["head_sha"])
        if sha != expected:
            raise OrganMaterializationError(f"MATERIALIZED_SHA_MISMATCH:{key}:{sha}:{expected}")
        return self.fixture_roots[key], sha


def write_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")


def fixtures(root: Path, *, topa_spider=True):
    roots = {
        "anomaly_lab": root / "topa",
        "left_context": root / "hrain",
        "orchestrator": root / "demiurge",
    }
    for path in roots.values():
        path.mkdir(parents=True)

    write_json(roots["anomaly_lab"] / ".janus/JANUS_ORGANISM_LINK.json", {
        "organism_id": "JANUS_FEDERATED_ORGANISM",
        "member_repository": "Hawkar-usls/TOPA",
        "organ_key": "anomaly_lab",
        "role": "ANOMALY_LAB",
        "authority": "RESEARCH_HYPOTHESIS_ONLY",
        "evidence_authority": False,
    })
    script = roots["anomaly_lab"] / "tools/topa_detective_spider.py"
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text(
        "import json\nprint(json.dumps({"
        "'status':'PASS','mode':'DETECTIVE','identity':'TOPA_DETECTIVE_SPIDER',"
        f"'activated':{{'topa_core':True,'spider':{str(topa_spider)}}},'checks':[{{'component':'TOPA_CORE','pass':True}},{{'component':'SPIDER','pass':{str(topa_spider)}}}]"
        "}))\n",
        encoding="utf-8",
    )

    write_json(roots["left_context"] / ".janus/JANUS_ORGANISM_LINK.json", {
        "organism_id": "JANUS_FEDERATED_ORGANISM",
        "member_repository": "Hawkar-usls/Hrain",
        "organ_key": "left_context",
        "role": "STRUCTURAL_CONTEXT_HEMISPHERE",
        "authority": "GRAPH_ANALYSIS_ONLY",
        "evidence_authority": False,
    })
    write_json(roots["left_context"] / ".janus/TOPA_SPIDER_LINK.json", {
        "writeback": False,
        "laws": [
            "REPLAY_IS_NOT_NEW_EVIDENCE",
            "CONTEXT_COMPLETENESS_IS_NOT_CLAIM_STRENGTH",
            "ATTENTION_WEIGHT_IS_NOT_EVIDENCE_WEIGHT",
            "TOPA_DETECTIVE_DEFAULT_INCLUDES_SPIDER",
        ],
        "hrain_components": {"context_fur_panel": True, "attention_ecosystem": True},
    })
    write_json(roots["left_context"] / ".janus/SPIDER_HOME.json", {"status": "ACTIVE_RESIDENT"})

    write_json(roots["orchestrator"] / ".janus/JANUS_ORGANISM_LINK.json", {
        "organism_id": "JANUS_FEDERATED_ORGANISM",
        "member_repository": "Hawkar-usls/Janus-Demiurge",
        "organ_key": "orchestrator",
        "role": "SPIRAL_AGENT_CONTROL_PLANE",
        "authority": "DISPATCH_COORDINATION",
        "evidence_authority": False,
    })
    executor = roots["orchestrator"] / "tools/activator_readonly_execution.py"
    executor.parent.mkdir(parents=True, exist_ok=True)
    executor.write_text("# bounded executor fixture\n", encoding="utf-8")
    workflow = roots["orchestrator"] / ".github/workflows/janus-activator-readonly-execution.yml"
    workflow.parent.mkdir(parents=True, exist_ok=True)
    workflow.write_text("name: bounded fixture\n", encoding="utf-8")
    return roots


class OrganMaterializerTests(unittest.TestCase):
    def make(self, root: Path, *, spider=True, lock=None, receipt=None, actual_shas=None):
        lock = lock or model_lock()
        receipt = receipt or runtime_receipt(lock)
        return FixtureMaterializer(
            lock,
            receipt,
            workspace=root / "workspace",
            constitution=constitution(),
            fixture_roots=fixtures(root / "fixtures", topa_spider=spider),
            actual_shas=actual_shas,
            now_fn=lambda: 100.0,
        )

    def test_three_heterogeneous_organs_materialize_under_exact_model_lock(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = self.make(Path(tmp)).materialize()
            self.assertEqual(result["terminal"], "JANUS_ACTIVE_ORGANS_MATERIALIZED_EXACT_SHA")
            self.assertEqual(result["materialized_member_count"], 3)
            self.assertEqual(result["executed_adapters"], ["anomaly_lab"])
            adapters = {row["member_key"]: row["adapter_result"] for row in result["materialized"]}
            self.assertEqual(adapters["anomaly_lab"]["identity"], "TOPA_DETECTIVE_SPIDER")
            self.assertTrue(adapters["anomaly_lab"]["activated"]["spider"])
            self.assertTrue(adapters["left_context"]["spider_resident"])
            self.assertFalse(adapters["left_context"]["writeback"])
            self.assertTrue(adapters["orchestrator"]["bounded_executor_present"])
            self.assertFalse(adapters["orchestrator"]["target_executor_invoked"])
            self.assertTrue(all(row["locked_head_sha"] == row["materialized_head_sha"] for row in result["materialized"]))
            self.assertFalse(result["external_effect_authorized"])

    def test_model_digest_tamper_is_rejected_before_materialization(self):
        with tempfile.TemporaryDirectory() as tmp:
            lock = model_lock()
            receipt = runtime_receipt(lock)
            receipt["model_digest"] = "f" * 64
            with self.assertRaisesRegex(OrganMaterializationError, "MODEL_DIGEST_BINDING_MISMATCH"):
                self.make(Path(tmp), lock=lock, receipt=receipt)

    def test_active_member_outside_locked_membership_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            lock = model_lock()
            receipt = runtime_receipt(lock)
            receipt["active_members"].append("invented_organ")
            materializer = self.make(Path(tmp), lock=lock, receipt=receipt)
            with self.assertRaisesRegex(OrganMaterializationError, "ACTIVE_MEMBER_OUTSIDE_MODEL"):
                materializer.materialize()

    def test_exact_sha_mismatch_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            actual = dict(SHAS)
            actual["anomaly_lab"] = "9" * 40
            materializer = self.make(Path(tmp), actual_shas=actual)
            with self.assertRaisesRegex(OrganMaterializationError, "MATERIALIZED_SHA_MISMATCH"):
                materializer.materialize()

    def test_detective_without_spider_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            materializer = self.make(Path(tmp), spider=False)
            with self.assertRaisesRegex(OrganMaterializationError, "TOPA_DETECTIVE"):
                materializer.materialize()


if __name__ == "__main__":
    unittest.main()
