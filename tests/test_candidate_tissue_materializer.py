from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from janus_spi.activator import canonical_hash
from janus_spi.candidate_tissue_materializer import (
    CandidateAwareOrganMaterializer,
    CandidateTissueMaterializationError,
)
from tests.test_organ_materializer import (
    SHAS,
    FixtureMaterializer,
    constitution as base_constitution,
    fixtures as base_fixtures,
    model_lock as base_model_lock,
    runtime_receipt as base_runtime_receipt,
    write_json,
)


def trump_manifest():
    return {
        "schema": "janus.trump.manifest.v0.1",
        "component": "TRUMP",
        "status": "CANDIDATE_RUNTIME_TISSUE",
        "canonical_runtime_location": "Hawkar-usls/Janus-Demiurge/trump/TRUMP_MANIFEST.json",
        "activation": {
            "wake_allowed": True,
            "use_allowed": True,
            "candidate_experiment_allowed": True,
            "self_improvement_allowed": True,
            "proof_authority": False,
            "scientific_claim_promotion_authority": False,
            "command_authority": False,
            "external_effect_authority": False,
            "physical_runtime_effect_authority": False,
        },
        "scientific_boundary": {
            "TRUMP_finished": False,
            "polynomial_time_SAT_proved": False,
            "P_equals_NP_proved": False,
            "P_VS_NP": "OPEN",
        },
    }


def candidate_receipt(terminal: str, *, execution: bool, promoted: bool = False, proof: bool = False):
    body = {
        "schema": "janus.trump.candidate_runtime_receipt.v0.1",
        "component": "TRUMP",
        "mode": "CANDIDATE_RUNTIME_TISSUE",
        "terminal": terminal,
        "execution_performed": execution,
        "candidate_result_promoted": promoted if execution else False,
        "authority": {
            "proof_authority": proof,
            "scientific_claim_promotion_authority": False,
            "command_authority": False,
            "external_effect_authority": False,
            "physical_runtime_effect_authority": False,
        },
        "scientific_boundary": {
            "TRUMP_finished": False,
            "polynomial_time_SAT_proved": False,
            "P_equals_NP_proved": False,
            "P_VS_NP": "OPEN",
        },
    }
    body["receipt_hash"] = canonical_hash(body)
    return body


def fake_trump_script(*, proof=False, promoted=False):
    status = candidate_receipt("TRUMP_CANDIDATE_RUNTIME_AVAILABLE", execution=False, proof=proof)
    selftest = candidate_receipt(
        "TRUMP_CANDIDATE_SELFTEST_PASS",
        execution=True,
        promoted=promoted,
        proof=proof,
    )
    return (
        "import json, sys\n"
        f"STATUS={status!r}\n"
        f"SELFTEST={selftest!r}\n"
        "if sys.argv[1]=='status':\n"
        "    print(json.dumps(STATUS,sort_keys=True))\n"
        "elif sys.argv[1]=='selftest':\n"
        "    print('PASS: C025 unified exact-cap Akinator/JEC selftest')\n"
        "    print('P_VS_NP = OPEN')\n"
        "    print(json.dumps(SELFTEST,sort_keys=True))\n"
        "else:\n"
        "    raise SystemExit(2)\n"
    )


def lock_with_trump(*, admitted=True):
    lock = base_model_lock()
    manifest = trump_manifest()
    lock["candidate_runtime_tissues"] = {
        "trump": {
            "tissue_key": "trump",
            "component": "TRUMP",
            "kind": "CANDIDATE_RUNTIME_TISSUE",
            "parent_organ": "orchestrator",
            "repository": "Hawkar-usls/Janus-Demiurge",
            "parent_head_sha": SHAS["orchestrator"],
            "manifest_path": "trump/TRUMP_MANIFEST.json",
            "runtime_entrypoint": "trump/trump_candidate.py",
            "manifest_hash": canonical_hash(manifest),
            "admission_status": "ADMITTED_CANDIDATE_RUNTIME" if admitted else "BLOCKED_FAIL_CLOSED",
            "wake_allowed": admitted,
            "use_allowed": admitted,
            "self_improvement_allowed": admitted,
            "proof_authority": False,
            "scientific_claim_promotion_authority": False,
            "external_effect_authority": False,
            "physical_runtime_effect_authority": False,
            "scientific_boundary": dict(manifest["scientific_boundary"]),
        }
    }
    return lock


def receipt_for(lock, *, route="research_or_anomaly_investigation", active=None):
    receipt = base_runtime_receipt(lock)
    receipt["active_members"] = list(active or ["anomaly_lab", "left_context", "orchestrator"])
    receipt["route_bindings"] = [{"match": route, "bindings": []}]
    receipt["model_lock_hash"] = canonical_hash(lock)
    return receipt


def candidate_constitution():
    c = base_constitution()
    c["candidate_tissue_adapters"] = {
        "trump": {
            "component": "TRUMP",
            "repository": "Hawkar-usls/Janus-Demiurge",
            "parent_member_key": "orchestrator",
            "adapter": "TRUMP_CANDIDATE_SELFTEST",
            "manifest_path": "trump/TRUMP_MANIFEST.json",
            "admitted_entrypoint": "trump/trump_candidate.py",
            "activate_on_routes": ["research_or_anomaly_investigation", "formal_or_theorem_claim"],
            "expected_manifest_status": "CANDIDATE_RUNTIME_TISSUE",
            "expected_status_terminal": "TRUMP_CANDIDATE_RUNTIME_AVAILABLE",
            "expected_selftest_terminal": "TRUMP_CANDIDATE_SELFTEST_PASS",
        }
    }
    return c


class FixtureCandidateMaterializer(CandidateAwareOrganMaterializer):
    def __init__(self, *args, fixture_roots, actual_shas=None, **kwargs):
        self.fixture_roots = fixture_roots
        self.actual_shas = actual_shas or dict(SHAS)
        super().__init__(*args, **kwargs)

    def _checkout_exact(self, key, member):
        sha = self.actual_shas[key]
        expected = str(member["head_sha"])
        if sha != expected:
            raise CandidateTissueMaterializationError(f"MATERIALIZED_SHA_MISMATCH:{key}:{sha}:{expected}")
        return self.fixture_roots[key], sha


def candidate_fixtures(root: Path, *, proof=False, promoted=False, tamper_manifest=False):
    roots = base_fixtures(root)
    demi = roots["orchestrator"]
    manifest = trump_manifest()
    if tamper_manifest:
        manifest["algorithmic_spine"] = ["TAMPER"]
    write_json(demi / "trump/TRUMP_MANIFEST.json", manifest)
    script = demi / "trump/trump_candidate.py"
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text(fake_trump_script(proof=proof, promoted=promoted), encoding="utf-8")
    return roots


class CandidateTissueMaterializerTests(unittest.TestCase):
    def make(self, root: Path, *, admitted=True, route="research_or_anomaly_investigation", active=None, proof=False, promoted=False, tamper_manifest=False, actual_shas=None):
        lock = lock_with_trump(admitted=admitted)
        receipt = receipt_for(lock, route=route, active=active)
        return FixtureCandidateMaterializer(
            lock,
            receipt,
            workspace=root / "workspace",
            constitution=candidate_constitution(),
            fixture_roots=candidate_fixtures(root / "fixtures", proof=proof, promoted=promoted, tamper_manifest=tamper_manifest),
            actual_shas=actual_shas,
            now_fn=lambda: 100.0,
        )

    def test_research_route_materializes_and_executes_candidate_trump(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = self.make(Path(tmp)).materialize()
            self.assertEqual(result["materialized_candidate_tissue_count"], 1)
            self.assertEqual(result["executed_candidate_tissues"], ["trump"])
            row = result["materialized_candidate_tissues"][0]
            self.assertEqual(row["parent_head_sha"], SHAS["orchestrator"])
            adapter = row["adapter_result"]
            self.assertEqual(adapter["terminal"], "TRUMP_CANDIDATE_TISSUE_MATERIALIZED_AND_SELF_TESTED")
            self.assertTrue(adapter["native_selftest_pass"])
            self.assertTrue(adapter["candidate_execution_performed"])
            self.assertFalse(adapter["candidate_result_promoted"])
            self.assertFalse(adapter["proof_authority"])
            self.assertEqual(adapter["scientific_boundary"]["P_VS_NP"], "OPEN")
            self.assertFalse(result["candidate_result_promotion_performed"])

    def test_unrelated_route_does_not_wake_trump(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = self.make(Path(tmp), route="human_read_only_conversation").materialize()
            self.assertEqual(result["materialized_candidate_tissue_count"], 0)
            self.assertEqual(result["executed_candidate_tissues"], [])

    def test_parent_not_active_does_not_wake_trump(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = self.make(Path(tmp), active=["anomaly_lab", "left_context"]).materialize()
            self.assertEqual(result["materialized_candidate_tissue_count"], 0)

    def test_unadmitted_candidate_is_rejected_on_candidate_route(self):
        with tempfile.TemporaryDirectory() as tmp:
            materializer = self.make(Path(tmp), admitted=False)
            with self.assertRaisesRegex(CandidateTissueMaterializationError, "CANDIDATE_TISSUE_NOT_ADMITTED"):
                materializer.materialize()

    def test_local_manifest_tamper_breaks_exact_model_binding(self):
        with tempfile.TemporaryDirectory() as tmp:
            materializer = self.make(Path(tmp), tamper_manifest=True)
            with self.assertRaisesRegex(CandidateTissueMaterializationError, "TRUMP_MANIFEST_HASH_BINDING_MISMATCH"):
                materializer.materialize()

    def test_candidate_receipt_proof_authority_escalation_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            materializer = self.make(Path(tmp), proof=True)
            with self.assertRaisesRegex(CandidateTissueMaterializationError, "CANDIDATE_AUTHORITY_CEILING_VIOLATION"):
                materializer.materialize()

    def test_candidate_result_promotion_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            materializer = self.make(Path(tmp), promoted=True)
            with self.assertRaisesRegex(CandidateTissueMaterializationError, "TRUMP_CANDIDATE_RESULT_PROMOTION_FORBIDDEN"):
                materializer.materialize()

    def test_parent_exact_sha_mismatch_is_rejected_before_candidate_execution(self):
        with tempfile.TemporaryDirectory() as tmp:
            actual = dict(SHAS)
            actual["orchestrator"] = "9" * 40
            materializer = self.make(Path(tmp), actual_shas=actual)
            with self.assertRaisesRegex(CandidateTissueMaterializationError, "MATERIALIZED_SHA_MISMATCH"):
                materializer.materialize()


if __name__ == "__main__":
    unittest.main()
