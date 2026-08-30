from __future__ import annotations

import json
import unittest
from pathlib import Path

from janus_spi.model_fabric import ModelFabricCompiler


H = {
    "home": "1" * 40,
    "janus": "2" * 40,
    "memory": "3" * 40,
    "demiurge": "4" * 40,
    "simptomat": "5" * 40,
    "bfain": "6" * 40,
    "tool": "7" * 40,
    "external": "8" * 40,
    "state": "9" * 40,
}


class FakeReader:
    def __init__(self, files, heads):
        self.files = files
        self.heads = dict(heads)
        self.branch_calls = []

    def json_file(self, repository, path, *, ref="main", allow_missing=False):
        value = self.files.get((repository, path, ref))
        if value is None and not allow_missing:
            raise RuntimeError(f"missing {repository}:{path}@{ref}")
        return value

    def branch_head(self, repository, branch="main"):
        self.branch_calls.append((repository, branch))
        return self.heads.get((repository, branch))


def topology_files():
    repo = "Hawkar-usls/Janus"
    organism = {
        "schema": "janus.organism.v1",
        "version": "1.1.0",
        "members": {
            "gateway": {
                "repo": "Hawkar-usls/Janus", "class": "CORE", "role": "NERVOUS_SYSTEM_GATEWAY",
                "authority": "ROUTING_ONLY", "evidence_authority": False,
                "emits": ["TYPED_ROUTE"], "consumes": ["ORGAN_REQUEST"]
            },
            "memory": {
                "repo": "Hawkar-usls/janus-meta-registry", "class": "CORE", "role": "LONG_TERM_MEMORY",
                "authority": "ARCHIVAL_PROVENANCE", "evidence_authority": False,
                "emits": ["PROVENANCE_PATH"], "consumes": ["CHECKPOINT", "NEGATIVE_RESULT"]
            },
            "orchestrator": {
                "repo": "Hawkar-usls/Janus-Demiurge", "class": "CORE", "role": "SPIRAL_AGENT_CONTROL_PLANE",
                "authority": "DISPATCH", "evidence_authority": False,
                "emits": ["SCOUT_REPORT"], "consumes": ["MISSION"]
            },
            "somatosensory_skin": {
                "repo": None, "class": "PRIVATE_GATED", "role": "TACTILE_SENSING",
                "authority": "CALIBRATED_SENSOR_SCOPE", "evidence_authority": True,
                "emits": ["TACTILE_TELEMETRY"], "consumes": ["PHYSICAL_SENSOR_INPUT"]
            }
        },
        "external_dependencies": {
            "independent_instrument": {
                "repo": "Hawkar-usls/independent-instrument",
                "classification": "EXTERNAL_RESEARCH_INSTRUMENT",
                "reason": "independent provenance"
            }
        }
    }
    ecology = {
        "schema": "janus.organism.repository_ecology.v1",
        "version": "1.3.0",
        "public_subtissues": {
            "bfain": {
                "repo": "Hawkar-usls/BFain", "class": "SUBTISSUE",
                "parent_organ": "simulation_habitat", "role": "SIMULATION_UI"
            }
        },
        "private_subtissues": {
            "private_measurement": {
                "repo": None, "class": "PRIVATE_SUBTISSUE", "parent_organ": "measurement_bench",
                "locator_env": "JANUS_PRIVATE_MEASUREMENT_REPO", "role": "RAW_MEASUREMENT"
            }
        },
        "legacy_archives": {
            "simptomat": {
                "repo": "Hawkar-usls/Simptomat", "class": "LEGACY_ARCHIVE", "former_scope": "OLD_HEALTH"
            }
        },
        "toolchain_dependencies": {
            "tool": {"repo": "Hawkar-usls/tool", "class": "TOOLCHAIN_DEPENDENCY"}
        },
        "external_research_instruments": {
            "independent_instrument": {
                "repo": "Hawkar-usls/independent-instrument", "class": "EXTERNAL_RESEARCH_INSTRUMENT"
            }
        },
        "profile_navigation": {"repo": "Hawkar-usls/Hawkar-usls", "class": "PROFILE_NAVIGATION"}
    }
    ecology_delta = {
        "schema": "janus.organism.repository_ecology.v1", "version": "1.4.0",
        "promotion": {
            "repository": "Hawkar-usls/Simptomat", "organ_key": "diagnostic_reasoning",
            "organ_class": "DOMAIN_LAB"
        }
    }
    simptomat_delta = {"schema": "janus.organism.delta.v1", "version": "1.0.0"}
    execution = {"schema": "janus.organism.execution.spiral.extension.v1", "version": "1.4.0"}
    files = {
        (repo, "organism/JANUS_ORGANISM_v1.json", "main"): organism,
        (repo, "organism/JANUS_REPOSITORY_ECOLOGY_v1.3.json", "main"): ecology,
        (repo, "organism/JANUS_REPOSITORY_ECOLOGY_v1.4.json", "main"): ecology_delta,
        (repo, "organism/JANUS_ORGANISM_DELTA_2026-08-26_SIMPTOMAT_v1.json", "main"): simptomat_delta,
        (repo, "organism/JANUS_SPIRAL_TRANCEPTION_v1.4.json", "main"): execution,
        (
            "Hawkar-usls/Simptomat", ".janus/JANUS_ORGANISM_LINK.json", "main"
        ): {
            "schema": "janus.organism.member_link.v1",
            "organism_id": "JANUS_FEDERATED_ORGANISM",
            "member_repository": "Hawkar-usls/Simptomat",
            "organ_key": "diagnostic_reasoning",
            "role": "DIAGNOSTIC_REASONING",
            "authority": "RESEARCH_DIAGNOSTIC_HYPOTHESIS_ONLY",
            "evidence_authority": False,
            "consumes": ["SELF_REPORTED_SYMPTOM_PACKET"],
            "emits": ["DIAGNOSTIC_REASONING_PACKET"]
        }
    }
    return files


def heads():
    return {
        ("Hawkar-usls/Hawkar-usls", "main"): H["home"],
        ("Hawkar-usls/Hawkar-usls", "janus/activator-state"): H["state"],
        ("Hawkar-usls/Janus", "main"): H["janus"],
        ("Hawkar-usls/janus-meta-registry", "main"): H["memory"],
        ("Hawkar-usls/Janus-Demiurge", "main"): H["demiurge"],
        ("Hawkar-usls/Simptomat", "main"): H["simptomat"],
        ("Hawkar-usls/BFain", "main"): H["bfain"],
        ("Hawkar-usls/tool", "main"): H["tool"],
        ("Hawkar-usls/independent-instrument", "main"): H["external"],
    }


class ModelFabricTests(unittest.TestCase):
    def manifest(self):
        return json.loads(Path(".janus/activator/JANUS_MODEL_MANIFEST.json").read_text(encoding="utf-8"))

    def compiler(self, *, files=None, head_map=None, now=100.0):
        return ModelFabricCompiler(
            self.manifest(),
            reader=FakeReader(files or topology_files(), head_map or heads()),
            now_fn=lambda: now,
        )

    def test_compiles_one_model_from_organs_and_ecology(self):
        result = self.compiler().compile()
        self.assertTrue(result["ready"])
        self.assertEqual(result["terminal"], "JANUS_MODEL_FABRIC_LOCKED_AT_HOME")
        self.assertIn("bootstrap_root", result["members"])
        self.assertIn("gateway", result["members"])
        self.assertIn("memory", result["members"])
        self.assertIn("orchestrator", result["members"])
        self.assertIn("diagnostic_reasoning", result["members"])
        self.assertIn("subtissue:bfain", result["members"])
        self.assertIn("toolchain:tool", result["members"])
        self.assertNotIn("legacy:simptomat", result["members"])
        self.assertEqual(result["members"]["diagnostic_reasoning"]["descriptor_status"], "SELF_DECLARED")
        self.assertTrue(result["routing_selects_activity_not_membership"])
        self.assertFalse(result["external_effect_authorized"])

    def test_capability_index_is_cross_repo_model_interface(self):
        result = self.compiler().compile()
        self.assertIn("gateway", result["capability_index"]["emitters"]["TYPED_ROUTE"])
        self.assertIn("diagnostic_reasoning", result["capability_index"]["emitters"]["DIAGNOSTIC_REASONING_PACKET"])
        self.assertIn("memory", result["capability_index"]["consumers"]["NEGATIVE_RESULT"])

    def test_missing_required_core_fails_closed(self):
        h = heads()
        h.pop(("Hawkar-usls/Janus-Demiurge", "main"))
        result = self.compiler(head_map=h).compile()
        self.assertFalse(result["ready"])
        self.assertEqual(result["terminal"], "JANUS_MODEL_FABRIC_FAIL_CLOSED")
        self.assertIn("orchestrator", result["failures"]["required_members_missing"])

    def test_optional_repository_missing_is_degraded_not_fatal(self):
        h = heads()
        h.pop(("Hawkar-usls/tool", "main"))
        result = self.compiler(head_map=h).compile()
        self.assertTrue(result["ready"])
        self.assertIn("toolchain:tool", result["optional_unavailable"])

    def test_required_descriptor_conflict_fails_closed(self):
        files = topology_files()
        files[("Hawkar-usls/Janus-Demiurge", ".janus/JANUS_ORGANISM_LINK.json", "main")] = {
            "organism_id": "JANUS_FEDERATED_ORGANISM",
            "member_repository": "Hawkar-usls/OTHER",
            "organ_key": "orchestrator"
        }
        result = self.compiler(files=files).compile()
        self.assertFalse(result["ready"])
        self.assertIn("orchestrator", result["failures"]["required_descriptor_conflicts"])

    def test_model_digest_is_independent_of_compile_clock(self):
        a = self.compiler(now=100.0).compile()
        b = self.compiler(now=999.0).compile()
        self.assertNotEqual(a["compiled_at"], b["compiled_at"])
        self.assertEqual(a["model_digest"], b["model_digest"])

    def test_private_slots_are_membership_without_fake_repository(self):
        reader = FakeReader(topology_files(), heads())
        result = ModelFabricCompiler(self.manifest(), reader=reader, now_fn=lambda: 1.0).compile()
        self.assertIn("somatosensory_skin", result["members"])
        self.assertIsNone(result["members"]["somatosensory_skin"]["repository"])
        self.assertEqual(result["members"]["somatosensory_skin"]["head_status"], "PRIVATE_OR_UNBOUND_SLOT")
        self.assertFalse(any(repo is None for repo, _branch in reader.branch_calls))


if __name__ == "__main__":
    unittest.main()
