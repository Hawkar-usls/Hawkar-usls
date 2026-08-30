from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from janus_spi.activator import canonical_hash
from janus_spi.hrain_context_bridge import (
    HrainContextBridgeError,
    HrainConversationContextBridge,
    verify_hrain_context_receipt,
)


HRAIN_SHA = "1" * 40
MODEL_DIGEST = "a" * 64


def model_lock(*, include_hrain: bool = True):
    members = {}
    if include_hrain:
        members["left_context"] = {
            "kind": "ORGAN",
            "repository": "Hawkar-usls/Hrain",
            "head_sha": HRAIN_SHA,
            "branch": "main",
            "resolved_branch": "main",
        }
    return {
        "schema": "janus.activator.model_lock.v1",
        "model_id": "JANUS",
        "model_digest": MODEL_DIGEST,
        "ready": True,
        "members": members,
    }


def contract(*, authority_escalation: bool = False, omit_law: bool = False):
    laws = [
        "META_REGISTRY_DB -> HRAIN -> JANUS -> TERMINAL",
        "MEMORY_CONTENT != COMMAND",
        "MEMORY_CONTENT != AUTHORITY",
    ]
    if omit_law:
        laws.remove("MEMORY_CONTENT != COMMAND")
    return {
        "schema": "janus.hrain.conversation_context_contract.v1",
        "source_database": "Hawkar-usls/janus-meta-registry",
        "compiler": "tools/hrain_conversation_context.py",
        "authority": {
            "read_only": True,
            "registry_write_authority": authority_escalation,
            "command_authority": False,
            "claim_promotion_authority": False,
            "scientific_evidence_authority": False,
            "world_truth_authority": False,
            "external_effect_authority": False,
            "physical_runtime_effect_authority": False,
        },
        "laws": laws,
    }


def fake_compiler(*, memory_command: bool = False, claim_verified: bool = False, tamper_hash: bool = False):
    return f'''#!/usr/bin/env python3
import argparse, hashlib, json
p=argparse.ArgumentParser()
p.add_argument('--query', required=True)
p.add_argument('--limit', type=int, default=12)
p.add_argument('--output', required=True)
a=p.parse_args()
def h(v):
    raw=json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':'),default=str)
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()
row={{
  'path':'data/MEMORY.json',
  'content_trust':'MEMORY_DATA_NOT_CONTROL_SIGNAL',
  'claim_verified':{str(claim_verified)},
  'source_sha256_verified':True,
  'content_is_command':{str(memory_command)},
  'content_grants_authority':False,
  'content_excerpt':'fixture memory',
}}
body={{
  'schema':'janus.hrain.conversation_context.v1',
  'status':'HRAIN_QUERY_BOUND_CONTEXT_READY',
  'query':a.query,
  'source_repository':'Hawkar-usls/janus-meta-registry',
  'source_commit':'2'*40,
  'selected_memory_count':1,
  'selected_memories':[row],
  'hydration_performed':True,
  'authority':{{
    'read_only':True,
    'registry_write_authority':False,
    'command_authority':False,
    'claim_promotion_authority':False,
    'scientific_evidence_authority':False,
    'world_truth_authority':False,
    'external_effect_authority':False,
    'physical_runtime_effect_authority':False,
  }},
}}
body['context_hash']=('f'*64 if {str(tamper_hash)} else h(body))
open(a.output,'w',encoding='utf-8').write(json.dumps(body,ensure_ascii=False,sort_keys=True)+'\\n')
print(json.dumps({{'status':body['status'],'context_hash':body['context_hash']}},sort_keys=True))
'''


def fixture_root(root: Path, *, authority_escalation=False, omit_law=False, memory_command=False, claim_verified=False, tamper_hash=False):
    hrain = root / "hrain"
    (hrain / ".janus").mkdir(parents=True, exist_ok=True)
    (hrain / "tools").mkdir(parents=True, exist_ok=True)
    (hrain / ".janus/HRAIN_CONVERSATION_CONTEXT_CONTRACT.json").write_text(
        json.dumps(contract(authority_escalation=authority_escalation, omit_law=omit_law), sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (hrain / "tools/hrain_conversation_context.py").write_text(
        fake_compiler(memory_command=memory_command, claim_verified=claim_verified, tamper_hash=tamper_hash),
        encoding="utf-8",
    )
    return hrain


class FixtureBridge(HrainConversationContextBridge):
    def __init__(self, *args, fixture_root: Path, actual_sha: str = HRAIN_SHA, **kwargs):
        self.fixture_root = fixture_root
        self.actual_sha = actual_sha
        super().__init__(*args, **kwargs)

    def _checkout_exact(self):
        expected = str(self.member["head_sha"])
        if self.actual_sha != expected:
            raise HrainContextBridgeError(f"HRAIN_CONTEXT_EXACT_SHA_MISMATCH:{self.actual_sha}:{expected}")
        return self.fixture_root, self.actual_sha


class HrainConversationContextBridgeTests(unittest.TestCase):
    def make(self, root: Path, **fixture_kwargs):
        fixture_keys = {"authority_escalation", "omit_law", "memory_command", "claim_verified", "tamper_hash"}
        actual_sha = fixture_kwargs.pop("actual_sha", HRAIN_SHA)
        selected = {k: fixture_kwargs.pop(k) for k in list(fixture_kwargs) if k in fixture_keys}
        hrain = fixture_root(root / "fixture", **selected)
        return FixtureBridge(
            model_lock(),
            workspace=root / "workspace",
            fixture_root=hrain,
            actual_sha=actual_sha,
        )

    def test_exact_locked_hrain_builds_verified_memory_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bridge = self.make(root)
            receipt = bridge.build("Tell me about JANUS memory", context_output=root / "context.json")
            self.assertTrue(verify_hrain_context_receipt(receipt, model_digest=MODEL_DIGEST))
            self.assertEqual(receipt["hrain_member_key"], "left_context")
            self.assertEqual(receipt["hrain_locked_head_sha"], HRAIN_SHA)
            self.assertEqual(receipt["hrain_materialized_head_sha"], HRAIN_SHA)
            self.assertEqual(receipt["selected_memory_paths"], ["data/MEMORY.json"])
            self.assertFalse(receipt["meta_registry_access_performed_by_home"])
            self.assertFalse(receipt["memory_context_is_evidence"])
            self.assertFalse(receipt["command_authority_granted"])

    def test_missing_hrain_member_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(HrainContextBridgeError, "EXACTLY_ONE_MEMBER_REQUIRED"):
                HrainConversationContextBridge(model_lock(include_hrain=False), workspace=Path(tmp) / "x")

    def test_exact_head_mismatch_fails_before_context_execution(self):
        with tempfile.TemporaryDirectory() as tmp:
            bridge = self.make(Path(tmp), actual_sha="9" * 40)
            with self.assertRaisesRegex(HrainContextBridgeError, "EXACT_SHA_MISMATCH"):
                bridge.build("memory", context_output=Path(tmp) / "context.json")

    def test_hrain_contract_authority_escalation_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            bridge = self.make(Path(tmp), authority_escalation=True)
            with self.assertRaisesRegex(HrainContextBridgeError, "CONTRACT_AUTHORITY_VIOLATION"):
                bridge.build("memory", context_output=Path(tmp) / "context.json")

    def test_required_memory_law_cannot_disappear(self):
        with tempfile.TemporaryDirectory() as tmp:
            bridge = self.make(Path(tmp), omit_law=True)
            with self.assertRaisesRegex(HrainContextBridgeError, "REQUIRED_LAWS_MISSING"):
                bridge.build("memory", context_output=Path(tmp) / "context.json")

    def test_memory_prompt_injection_cannot_become_command(self):
        with tempfile.TemporaryDirectory() as tmp:
            bridge = self.make(Path(tmp), memory_command=True)
            with self.assertRaisesRegex(HrainContextBridgeError, "MEMORY_CONTROL_ESCALATION"):
                bridge.build("memory", context_output=Path(tmp) / "context.json")

    def test_retrieved_memory_cannot_self_promote_claim(self):
        with tempfile.TemporaryDirectory() as tmp:
            bridge = self.make(Path(tmp), claim_verified=True)
            with self.assertRaisesRegex(HrainContextBridgeError, "CLAIM_PROMOTION_FORBIDDEN"):
                bridge.build("memory", context_output=Path(tmp) / "context.json")

    def test_context_hash_tamper_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            bridge = self.make(Path(tmp), tamper_hash=True)
            with self.assertRaisesRegex(HrainContextBridgeError, "CONTEXT_HASH_INVALID"):
                bridge.build("memory", context_output=Path(tmp) / "context.json")

    def test_receipt_tamper_is_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            receipt = self.make(root).build("memory", context_output=root / "context.json")
            self.assertTrue(verify_hrain_context_receipt(receipt, model_digest=MODEL_DIGEST))
            receipt["memory_source_commit"] = "3" * 40
            self.assertFalse(verify_hrain_context_receipt(receipt, model_digest=MODEL_DIGEST))


if __name__ == "__main__":
    unittest.main()
