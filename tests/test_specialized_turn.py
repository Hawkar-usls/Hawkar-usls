from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from janus_spi.activator import canonical_hash
from janus_spi.specialized_turn import SpecializedTurnError, SpecializedTurnLedger, reintegrate_specialized_turn


def fixtures(*, with_trump=False):
    lock = {"model_digest": "a" * 64, "members": {"x": {}}}
    runtime = {
        "model_digest": lock["model_digest"],
        "model_lock_hash": canonical_hash(lock),
        "runtime_receipt_hash": "b" * 64,
        "activation_id": "act-1",
        "activation_receipt_hash": "c" * 64,
        "active_organs": ["anomaly_lab", "left_context", "orchestrator"],
        "route_bindings": [{"match": "research_or_anomaly_investigation", "bindings": []}],
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
        "materialized_candidate_tissues": [],
        "executed_candidate_tissues": [],
        "candidate_result_promotion_performed": False,
        "command_authority_granted": False,
        "world_truth_authority_granted": False,
        "external_effect_authorized": False,
        "physical_runtime_effect_authorized": False,
    }
    if with_trump:
        manifest_hash = "e" * 64
        lock["candidate_runtime_tissues"] = {
            "trump": {
                "admission_status": "ADMITTED_CANDIDATE_RUNTIME",
                "parent_head_sha": "1" * 40,
                "manifest_hash": manifest_hash,
            }
        }
        runtime["model_lock_hash"] = canonical_hash(lock)
        material["model_lock_hash"] = canonical_hash(lock)
        candidate = {
            "adapter": "TRUMP_CANDIDATE_SELFTEST",
            "component": "TRUMP",
            "terminal": "TRUMP_CANDIDATE_TISSUE_MATERIALIZED_AND_SELF_TESTED",
            "native_selftest_pass": True,
            "candidate_execution_performed": True,
            "candidate_result_promoted": False,
            "proof_authority": False,
            "scientific_claim_promotion_authority": False,
            "command_authority_granted": False,
            "world_truth_authority_granted": False,
            "external_effect_authorized": False,
            "physical_runtime_effect_authorized": False,
            "scientific_boundary": {"P_equals_NP_proved": False, "P_VS_NP": "OPEN"},
        }
        candidate["adapter_result_hash"] = canonical_hash(candidate)
        material["materialized_candidate_tissues"] = [{
            "candidate_tissue_key": "trump",
            "parent_member_key": "orchestrator",
            "repository": "Hawkar-usls/Janus-Demiurge",
            "parent_head_sha": "1" * 40,
            "manifest_hash": manifest_hash,
            "adapter_result": candidate,
        }]
        material["executed_candidate_tissues"] = ["trump"]
    return lock, runtime, material


class SpecializedTurnTests(unittest.TestCase):
    def test_reintegrates_three_organs_without_promoting_outputs(self):
        lock, runtime, material = fixtures()
        with tempfile.TemporaryDirectory() as tmp:
            ledger = SpecializedTurnLedger(Path(tmp) / "turns.jsonl")
            receipt = reintegrate_specialized_turn(lock, runtime, material, ledger=ledger, now_fn=lambda: 100.0)
            self.assertEqual(receipt["terminal"], "JANUS_SPECIALIZED_ORGAN_AND_CANDIDATE_TURN_REINTEGRATED")
            self.assertEqual(len(receipt["organ_outputs"]), 3)
            self.assertEqual(receipt["candidate_outputs"], [])
            self.assertIn("anomaly_lab", receipt["executed_adapters"])
            self.assertFalse(receipt["claim_promotion_performed"])
            self.assertFalse(receipt["candidate_result_promotion_performed"])
            self.assertFalse(receipt["scientific_evidence_authority_granted"])
            self.assertFalse(receipt["external_effect_authorized"])
            self.assertTrue(ledger.verify())

    def test_reintegrates_trump_as_candidate_not_proof_authority(self):
        lock, runtime, material = fixtures(with_trump=True)
        with tempfile.TemporaryDirectory() as tmp:
            receipt = reintegrate_specialized_turn(
                lock, runtime, material,
                ledger=SpecializedTurnLedger(Path(tmp) / "turns.jsonl"),
                now_fn=lambda: 100.0,
            )
            self.assertEqual(receipt["executed_candidate_tissues"], ["trump"])
            self.assertEqual(len(receipt["candidate_outputs"]), 1)
            row = receipt["candidate_outputs"][0]
            self.assertEqual(row["candidate_tissue_key"], "trump")
            self.assertTrue(row["native_selftest_pass"])
            self.assertFalse(row["candidate_result_promoted"])
            self.assertFalse(row["proof_authority_granted"])
            self.assertFalse(receipt["proof_authority_granted"])
            self.assertFalse(receipt["scientific_claim_promotion_authority_granted"])

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

    def test_trump_candidate_promotion_is_rejected(self):
        lock, runtime, material = fixtures(with_trump=True)
        adapter = material["materialized_candidate_tissues"][0]["adapter_result"]
        adapter["candidate_result_promoted"] = True
        adapter["adapter_result_hash"] = canonical_hash({k: v for k, v in adapter.items() if k != "adapter_result_hash"})
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(SpecializedTurnError, "CANDIDATE_RESULT_PROMOTION_FORBIDDEN"):
                reintegrate_specialized_turn(lock, runtime, material, ledger=SpecializedTurnLedger(Path(tmp) / "x"))


if __name__ == "__main__":
    unittest.main()
