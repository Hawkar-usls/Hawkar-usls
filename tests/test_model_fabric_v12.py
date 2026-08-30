from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from janus_spi.model_fabric_v12 import ModelFabricCompilerV12
from tests.test_model_fabric import FakeReader, H, heads, topology_files


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
        "candidate_sources": [
            {
                "repository": "Hawkar-usls/Janus-Fundamentum",
                "pinned_commit": "a" * 40,
                "path": "experiments/direct/candidate.py",
                "git_blob_sha": "b" * 40,
            }
        ],
        "algorithmic_spine": ["SEARCH_GRAMMAR", "RESOURCE_LEDGER", "MAD_LAB"],
        "scientific_boundary": {
            "TRUMP_finished": False,
            "polynomial_time_SAT_proved": False,
            "P_equals_NP_proved": False,
            "P_VS_NP": "OPEN",
        },
    }


def files_with_trump():
    files = topology_files()
    files[(
        "Hawkar-usls/Janus-Demiurge",
        "trump/TRUMP_MANIFEST.json",
        H["demiurge"],
    )] = trump_manifest()
    return files


class TrackingReader(FakeReader):
    def __init__(self, files, head_map):
        super().__init__(files, head_map)
        self.json_calls = []

    def json_file(self, repository, path, *, ref="main", allow_missing=False):
        self.json_calls.append((repository, path, ref, allow_missing))
        return super().json_file(repository, path, ref=ref, allow_missing=allow_missing)


class ModelFabricV12TrumpTests(unittest.TestCase):
    def manifest(self):
        return json.loads(Path(".janus/activator/JANUS_MODEL_MANIFEST.json").read_text(encoding="utf-8"))

    def compile(self, *, files=None, now=100.0):
        reader = TrackingReader(files if files is not None else files_with_trump(), heads())
        lock = ModelFabricCompilerV12(
            self.manifest(),
            reader=reader,
            now_fn=lambda: now,
        ).compile()
        return lock, reader

    def test_trump_is_candidate_tissue_bound_to_locked_demiurge_not_duplicate_member(self):
        lock, reader = self.compile()
        self.assertTrue(lock["ready"])
        self.assertEqual(lock["model_fabric_version"], "1.2")
        self.assertNotIn("trump", lock["members"])
        tissue = lock["candidate_runtime_tissues"]["trump"]
        self.assertEqual(tissue["parent_organ"], "orchestrator")
        self.assertEqual(tissue["repository"], "Hawkar-usls/Janus-Demiurge")
        self.assertEqual(tissue["parent_head_sha"], H["demiurge"])
        self.assertEqual(tissue["admission_status"], "ADMITTED_CANDIDATE_RUNTIME")
        self.assertTrue(tissue["wake_allowed"])
        self.assertTrue(tissue["use_allowed"])
        self.assertTrue(tissue["self_improvement_allowed"])
        self.assertFalse(tissue["proof_authority"])
        self.assertEqual(tissue["scientific_boundary"]["P_VS_NP"], "OPEN")
        self.assertEqual(lock["candidate_tissue_unavailable"], [])
        self.assertIn(
            ("Hawkar-usls/Janus-Demiurge", "trump/TRUMP_MANIFEST.json", H["demiurge"], True),
            reader.json_calls,
        )

    def test_candidate_capabilities_are_visible_without_becoming_organ_membership(self):
        lock, _ = self.compile()
        self.assertIn(
            "candidate_tissue:trump",
            lock["capability_index"]["emitters"]["CANDIDATE_COMPUTATION_RECEIPT"],
        )
        self.assertIn(
            "candidate_tissue:trump",
            lock["capability_index"]["consumers"]["FORMAL_PROBLEM"],
        )
        organ_count = sum(1 for row in lock["members"].values() if row.get("kind") == "ORGAN")
        self.assertEqual(organ_count, sum(1 for row in lock["members"].values() if row.get("kind") == "ORGAN"))

    def test_candidate_manifest_authority_escalation_blocks_only_candidate_tissue(self):
        files = files_with_trump()
        bad = copy.deepcopy(files[("Hawkar-usls/Janus-Demiurge", "trump/TRUMP_MANIFEST.json", H["demiurge"])])
        bad["activation"]["proof_authority"] = True
        files[("Hawkar-usls/Janus-Demiurge", "trump/TRUMP_MANIFEST.json", H["demiurge"])] = bad
        lock, _ = self.compile(files=files)
        self.assertTrue(lock["ready"])
        tissue = lock["candidate_runtime_tissues"]["trump"]
        self.assertEqual(tissue["admission_status"], "BLOCKED_FAIL_CLOSED")
        self.assertEqual(tissue["blocked_reason"], "CANDIDATE_AUTHORITY_CEILING_VIOLATION")
        self.assertFalse(tissue["wake_allowed"])
        self.assertIn("trump", lock["candidate_tissue_unavailable"])
        self.assertNotIn(
            "candidate_tissue:trump",
            lock["capability_index"]["emitters"].get("CANDIDATE_COMPUTATION_RECEIPT", []),
        )

    def test_missing_optional_candidate_manifest_does_not_fake_admission(self):
        lock, _ = self.compile(files=topology_files())
        self.assertTrue(lock["ready"])
        tissue = lock["candidate_runtime_tissues"]["trump"]
        self.assertEqual(tissue["admission_status"], "BLOCKED_FAIL_CLOSED")
        self.assertEqual(tissue["blocked_reason"], "CANDIDATE_MANIFEST_MISSING_AT_LOCKED_PARENT_SHA")
        self.assertIn("trump", lock["candidate_tissue_unavailable"])

    def test_candidate_manifest_changes_model_digest(self):
        a, _ = self.compile()
        files = files_with_trump()
        changed = copy.deepcopy(files[("Hawkar-usls/Janus-Demiurge", "trump/TRUMP_MANIFEST.json", H["demiurge"])])
        changed["algorithmic_spine"].append("EXACT_JANUS")
        files[("Hawkar-usls/Janus-Demiurge", "trump/TRUMP_MANIFEST.json", H["demiurge"])] = changed
        b, _ = self.compile(files=files)
        self.assertNotEqual(a["model_digest"], b["model_digest"])

    def test_v12_model_digest_is_stable_across_compile_clock(self):
        a, _ = self.compile(now=100.0)
        b, _ = self.compile(now=999.0)
        self.assertNotEqual(a["compiled_at"], b["compiled_at"])
        self.assertEqual(a["model_digest"], b["model_digest"])


if __name__ == "__main__":
    unittest.main()
