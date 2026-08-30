from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from janus_spi.activator import canonical_hash
from janus_spi.specialized_turn import SpecializedTurnError, SpecializedTurnLedger, reintegrate_specialized_turn


def fixtures():
    lock = {"model_digest": "a" * 64, "members": {"x": {}}}
    runtime = {
        "model_digest": lock["model_digest"],
        "model_lock_hash": canonical_hash(lock),
        "runtime_receipt_hash": "b" * 64,
        "activation_id": "act-1",
        "activation_receipt_hash": "c" * 64,
        "active_organs": ["anomaly_lab", "left_context", "orchestrator"],
        "command_authority_granted": False,
        "world_truth_authority_granted": False,
        "external_effect_authorized": False,
        "physical_runtime_effect_authorized": False,
    }
    materialized = []
    for key, repo, adapter in [
        ("anomaly_lab", "Hawkar-usls/TOPA", "TOPA_DETECTIVE_SELF_TEST"),
        ("left_context", "Hawkar-usls/Hrain", "HRAIN_READ_ONLY_CONTEXT_CAPSULE"),
        ("orchestrator", "Hawkar-usls/Janus-Demiurge", "DEMIURGE_READ_ONLY_CONTROL_CAPSULE"),
    ]:
        result = {
            "adapter": adapter,
            "terminal": "PASS",
            "external_effect_authorized": False,
            "physical_runtime_effect_authorized": False,
        }
        result["adapter_result_hash"] = canonical_hash(result)
        materialized.append({
            "member_key": key,
            "repository": repo,
            "locked_head_sha": "1" * 40,
            "materialized_head_sha": "1" * 40,
            "adapter_result": result,
        })
    material = {
        "model_digest": lock["model_digest"],
        "model_lock_hash": canonical_hash(lock),
        "model_runtime_receipt_hash": runtime["runtime_receipt_hash"],
        "materialization_receipt_hash": "d" * 64,
        "terminal": "JANUS_ACTIVE_ORGANS_MATERIALIZED_EXACT_SHA",
        "materialized": materialized,
        "executed_adapters": ["anomaly_lab"],
        "command_authority_granted": False,
        "world_truth_authority_granted": False,
        "external_effect_authorized": False,
        "physical_runtime_effect_authorized": False,
    }
    return lock, runtime, material


class SpecializedTurnTests(unittest.TestCase):
    def test_reintegrates_three_organs_without_promoting_outputs(self):
        lock, runtime, material = fixtures()
        with tempfile.TemporaryDirectory() as tmp:
            ledger = SpecializedTurnLedger(Path(tmp) / "turns.jsonl")
            receipt = reintegrate_specialized_turn(lock, runtime, material, ledger=ledger, now_fn=lambda: 100.0)
            self.assertEqual(receipt["terminal"], "JANUS_SPECIALIZED_ORGAN_TURN_REINTEGRATED")
            self.assertEqual(len(receipt["organ_outputs"]), 3)
            self.assertIn("anomaly_lab", receipt["executed_adapters"])
            self.assertFalse(receipt["claim_promotion_performed"])
            self.assertFalse(receipt["scientific_evidence_authority_granted"])
            self.assertFalse(receipt["external_effect_authorized"])
            self.assertTrue(ledger.verify())

    def test_wrong_model_digest_is_rejected(self):
        lock, runtime, material = fixtures()
        material["model_digest"] = "f" * 64
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(SpecializedTurnError, "MODEL_DIGEST_MISMATCH"):
                reintegrate_specialized_turn(lock, runtime, material, ledger=SpecializedTurnLedger(Path(tmp) / "x"))

    def test_missing_topa_execution_is_rejected(self):
        lock, runtime, material = fixtures()
        material["executed_adapters"] = []
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(SpecializedTurnError, "TOPA_DETECTIVE"):
                reintegrate_specialized_turn(lock, runtime, material, ledger=SpecializedTurnLedger(Path(tmp) / "x"))

    def test_exact_sha_mismatch_is_rejected_at_reintegration(self):
        lock, runtime, material = fixtures()
        material["materialized"][0]["materialized_head_sha"] = "2" * 40
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(SpecializedTurnError, "EXACT_SHA_MISMATCH"):
                reintegrate_specialized_turn(lock, runtime, material, ledger=SpecializedTurnLedger(Path(tmp) / "x"))

    def test_adapter_hash_tamper_is_rejected(self):
        lock, runtime, material = fixtures()
        material["materialized"][1]["adapter_result"]["terminal"] = "TAMPER"
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(SpecializedTurnError, "ADAPTER_RESULT_HASH_MISMATCH"):
                reintegrate_specialized_turn(lock, runtime, material, ledger=SpecializedTurnLedger(Path(tmp) / "x"))


if __name__ == "__main__":
    unittest.main()
