from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from janus_spi.activator import ActivationEvent, canonical_hash
from janus_spi.model_runtime import ModelBoundJanusRuntime, ModelRuntimeError


class FakeActivator:
    def __init__(self, *, state_dir, routing_path, policy_path):
        self.state_dir = state_dir

    def activate(self, event):
        receipt = {
            "schema": "janus.activator.receipt.v0.2",
            "activation_id": "act-test",
            "event_id": event.event_id,
            "terminal": "ROUTE_PROPOSED",
            "next_gate": "RUN_SELECTED_SPECIALIZED_GATES_WITH_SEPARATE_AUTHORITY",
            "routes_selected": [{
                "match": "research_or_anomaly_investigation",
                "organs": ["Hawkar-usls/TOPA", "Hawkar-usls/Hrain", "Hawkar-usls/Janus-Demiurge"],
                "required_gates": ["raw_provenance", "falsifier"],
            }],
        }
        receipt["receipt_hash"] = canonical_hash(receipt)
        return receipt


def model_lock():
    members = {
        "bootstrap_root": {
            "kind": "BOOTSTRAP_ROOT", "repository": "Hawkar-usls/Hawkar-usls",
            "member_class": "BOOTSTRAP_ROOT", "role": "IDENTITY_HOME_BOOTSTRAP_ROOT_AND_ACTIVATOR",
            "branch": "main", "resolved_branch": "main", "head_sha": "1" * 40,
            "load_mode": "REQUIRED_BOOT_PRESENCE", "descriptor_status": None,
        },
        "anomaly_lab": {
            "kind": "ORGAN", "repository": "Hawkar-usls/TOPA", "member_class": "CORE",
            "role": "ANOMALY_LAB", "branch": "main", "resolved_branch": "main",
            "head_sha": "2" * 40, "load_mode": "REQUIRED_BOOT_PRESENCE",
            "descriptor_status": "CENTRAL_MANIFEST_FALLBACK",
        },
        "left_context": {
            "kind": "ORGAN", "repository": "Hawkar-usls/Hrain", "member_class": "CORE",
            "role": "STRUCTURAL_CONTEXT_HEMISPHERE", "branch": "main", "resolved_branch": "main",
            "head_sha": "3" * 40, "load_mode": "REQUIRED_BOOT_PRESENCE",
            "descriptor_status": "SELF_DECLARED",
        },
        "orchestrator": {
            "kind": "ORGAN", "repository": "Hawkar-usls/Janus-Demiurge", "member_class": "CORE",
            "role": "SPIRAL_AGENT_CONTROL_PLANE", "branch": "main", "resolved_branch": "main",
            "head_sha": "4" * 40, "load_mode": "REQUIRED_BOOT_PRESENCE",
            "descriptor_status": "CENTRAL_MANIFEST_FALLBACK",
        },
    }
    lock = {
        "schema": "janus.activator.model_lock.v1",
        "model_id": "JANUS",
        "model_class": "GIT_NATIVE_FEDERATED_AI_ORGANISM",
        "model_digest": "a" * 64,
        "terminal": "JANUS_MODEL_FABRIC_LOCKED_AT_HOME",
        "ready": True,
        "routing_selects_activity_not_membership": True,
        "all_membership_compiled_before_routing": True,
        "external_effect_authorized": False,
        "physical_runtime_effect_authorized": False,
        "members": members,
        "optional_unavailable": [],
        "failures": {
            "required_members_missing": [],
            "required_descriptor_conflicts": [],
            "required_state_mounts_missing": [],
        },
    }
    return lock


class ModelRuntimeTests(unittest.TestCase):
    def event(self):
        return ActivationEvent.build(
            source_kind="EMAIL",
            source_ref="message-1",
            payload={"subject": "Janus research"},
            classifications=["research_or_anomaly_investigation"],
            fresh=True,
        )

    def test_route_is_bound_to_preexisting_model_membership(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime = ModelBoundJanusRuntime(
                model_lock(), state_dir=tmp, routing_path="unused", policy_path="unused",
                activator_factory=FakeActivator, now_fn=lambda: 123.0,
            )
            result = runtime.activate(self.event())
            self.assertEqual(result["terminal"], "JANUS_MODEL_BOUND_ROUTE_PROPOSED")
            self.assertEqual(result["model_digest"], "a" * 64)
            self.assertEqual(result["active_organs"], ["anomaly_lab", "left_context", "orchestrator"])
            self.assertTrue(result["membership_was_locked_before_activation"])
            self.assertFalse(result["dispatch_authorized"])
            self.assertFalse(result["external_effect_authorized"])
            bindings = result["route_bindings"][0]["bindings"]
            self.assertEqual({row["repository"] for row in bindings}, {
                "Hawkar-usls/TOPA", "Hawkar-usls/Hrain", "Hawkar-usls/Janus-Demiurge"
            })
            self.assertTrue(all(len(row["head_sha"]) == 40 for row in bindings))

    def test_route_cannot_add_repository_outside_locked_model(self):
        class BadActivator(FakeActivator):
            def activate(self, event):
                receipt = super().activate(event)
                receipt["routes_selected"][0]["organs"].append("Hawkar-usls/NOT-A-MEMBER")
                receipt["receipt_hash"] = canonical_hash({k: v for k, v in receipt.items() if k != "receipt_hash"})
                return receipt

        with tempfile.TemporaryDirectory() as tmp:
            runtime = ModelBoundJanusRuntime(
                model_lock(), state_dir=tmp, routing_path="unused", policy_path="unused",
                activator_factory=BadActivator,
            )
            with self.assertRaisesRegex(ModelRuntimeError, "ROUTE_TARGET_NOT_IN_MODEL_MEMBERSHIP"):
                runtime.activate(self.event())

    def test_effect_authority_in_model_lock_is_rejected(self):
        lock = model_lock()
        lock["external_effect_authorized"] = True
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ModelRuntimeError, "ZERO_EFFECT_AUTHORITY"):
                ModelBoundJanusRuntime(
                    lock, state_dir=tmp, routing_path="unused", policy_path="unused",
                    activator_factory=FakeActivator,
                )

    def test_incomplete_public_ecology_is_rejected(self):
        lock = model_lock()
        lock["optional_unavailable"] = ["toolchain:missing"]
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ModelRuntimeError, "PUBLIC_ECOLOGY_INCOMPLETE"):
                ModelBoundJanusRuntime(
                    lock, state_dir=tmp, routing_path="unused", policy_path="unused",
                    activator_factory=FakeActivator,
                )

    def test_runtime_ledger_preserves_model_digest_across_turns(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime = ModelBoundJanusRuntime(
                model_lock(), state_dir=tmp, routing_path="unused", policy_path="unused",
                activator_factory=FakeActivator,
            )
            first = runtime.activate(self.event())
            second_event = ActivationEvent.build(
                source_kind="EMAIL", source_ref="message-2", payload={"x": 2},
                classifications=["research_or_anomaly_investigation"], fresh=True,
            )
            second = runtime.activate(second_event)
            self.assertEqual(second["parent_runtime_hash"], first["runtime_receipt_hash"])
            self.assertEqual(second["model_digest"], first["model_digest"])
            self.assertTrue(runtime.ledger.verify())


if __name__ == "__main__":
    unittest.main()
