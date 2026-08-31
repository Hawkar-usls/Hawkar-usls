from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from janus_spi.activator import canonical_hash
from run_janus_real_launch_v2 import SUCCESS_TERMINAL, validate_launch_receipt


def valid_receipt():
    row = {
        "schema": "janus.activator.real_launch_v2_result.v1",
        "terminal": SUCCESS_TERMINAL,
        "cycle_id": "real-launch-v2-x",
        "event_id": "evt-x",
        "resident_uuid": "75e514ab-be76-42c8-bcb3-fc9670164f96",
        "same_resident_uuid": True,
        "fresh_external_stimulus": True,
        "model_first": True,
        "all_membership_compiled_before_routing": True,
        "routing_selects_activity_not_membership": True,
        "model_digest": "a" * 64,
        "model_member_count": 47,
        "model_organ_count": 23,
        "file_fabric_digest": "b" * 64,
        "file_fabric_coverage_complete": True,
        "active_organs": ["anomaly_lab", "left_context", "orchestrator"],
        "materialized_member_count": 3,
        "executed_adapters": ["anomaly_lab"],
        "executed_candidate_tissues": ["trump"],
        "specialized_turn_hash": "c" * 64,
        "candidate_result_promotion_performed": False,
        "trump": {
            "admission_status": "ADMITTED_CANDIDATE_RUNTIME",
            "manifest_hash": "d" * 64,
            "parent_head_sha": "e" * 40,
            "native_selftest_pass": True,
            "candidate_result_promoted": False,
            "proof_authority_granted": False,
            "scientific_claim_promotion_authority_granted": False,
            "scientific_boundary": {
                "P_equals_NP_proved": False,
                "P_VS_NP": "OPEN",
            },
        },
        "wake_hash": "f" * 64,
        "checkpoint_hash": "1" * 64,
        "sleep_hash": "2" * 64,
        "mode": "AT_HOME",
        "return_not_reset": True,
        "command_authority_granted": False,
        "claim_authority_granted": False,
        "scientific_evidence_authority_granted": False,
        "world_truth_authority_granted": False,
        "external_effect_authorized": False,
        "physical_runtime_effect_authorized": False,
    }
    row["launch_receipt_hash"] = canonical_hash(row)
    return row


class RealLaunchV2Tests(unittest.TestCase):
    def test_valid_receipt_is_accepted(self):
        self.assertTrue(validate_launch_receipt(valid_receipt()))

    def test_trump_must_actually_execute_and_selftest(self):
        row = valid_receipt()
        row["executed_candidate_tissues"] = []
        row["launch_receipt_hash"] = canonical_hash({k: v for k, v in row.items() if k != "launch_receipt_hash"})
        self.assertFalse(validate_launch_receipt(row))
        row = valid_receipt()
        row["trump"]["native_selftest_pass"] = False
        row["launch_receipt_hash"] = canonical_hash({k: v for k, v in row.items() if k != "launch_receipt_hash"})
        self.assertFalse(validate_launch_receipt(row))

    def test_candidate_or_authority_promotion_is_rejected(self):
        for path in (
            ("candidate_result_promotion_performed",),
            ("command_authority_granted",),
            ("external_effect_authorized",),
        ):
            row = valid_receipt()
            row[path[0]] = True
            row["launch_receipt_hash"] = canonical_hash({k: v for k, v in row.items() if k != "launch_receipt_hash"})
            self.assertFalse(validate_launch_receipt(row))
        row = valid_receipt()
        row["trump"]["proof_authority_granted"] = True
        row["launch_receipt_hash"] = canonical_hash({k: v for k, v in row.items() if k != "launch_receipt_hash"})
        self.assertFalse(validate_launch_receipt(row))

    def test_model_first_and_return_not_reset_are_required(self):
        for field in ("model_first", "all_membership_compiled_before_routing", "file_fabric_coverage_complete", "return_not_reset", "same_resident_uuid"):
            row = valid_receipt()
            row[field] = False
            row["launch_receipt_hash"] = canonical_hash({k: v for k, v in row.items() if k != "launch_receipt_hash"})
            self.assertFalse(validate_launch_receipt(row), field)

    def test_receipt_hash_tamper_is_rejected(self):
        row = valid_receipt()
        row["model_digest"] = "9" * 64
        self.assertFalse(validate_launch_receipt(row))

    def test_constitution_freezes_current_launch_laws(self):
        value = json.loads(Path(".janus/activator/REAL_LAUNCH_V2_CONSTITUTION.json").read_text(encoding="utf-8"))
        self.assertEqual(value["launch_success_terminal"], SUCCESS_TERMINAL)
        self.assertEqual(value["trump"]["canonical_location"], "Hawkar-usls/Janus-Demiurge/trump/TRUMP_MANIFEST.json")
        self.assertTrue(value["trump"]["wake_allowed"])
        self.assertTrue(value["trump"]["use_allowed"])
        self.assertTrue(value["trump"]["self_improvement_allowed"])
        self.assertFalse(value["trump"]["proof_authority"])
        self.assertEqual(value["trump"]["P_VS_NP"], "OPEN")
        self.assertEqual(value["persistent_identity"]["continuity_law"], "RETURN != RESET")
        self.assertTrue(value["legacy"]["must_not_be_used_as_v2_launch_witness"])
        self.assertEqual(
            value["transport_scope"]["dual_transport_law"],
            "IF_CROSS_REPO_TRANSPORT_IS_INVOKED_THEN_SECRET_PUSH_PARALLEL_CREDENTIALLESS_PULL",
        )


if __name__ == "__main__":
    unittest.main()
