from __future__ import annotations

import unittest

from janus_spi.market_repo_audit import build_home_response, digest, verify_home_response, verify_packet
from janus_spi.repo_audit_service import digest as service_digest


def packet():
    request = {
        "schema": "janus.market_service.repo_audit_request.v1",
        "request_id": "ra-1",
        "sku": "JANUS.REPO_AUDIT",
        "buyer_actor_id": "github:test",
        "repository": "acme/demo",
        "ref": "main",
        "audit_scope": "BOUNDED_STATIC_REPOSITORY_SURFACE",
        "bounds": {"max_tree_entries": 1000, "max_blob_files": 20, "max_total_blob_bytes": 500000},
        "read_only": True,
        "execute_repository_code": False,
        "command_authority_granted": False,
        "external_effect_authorized": False,
    }
    request["request_hash"] = service_digest(request)
    grant = {
        "schema": "janus.machine_market.purchase_grant.v1",
        "purchase_id": "pur-ra-1",
        "sku": "JANUS.REPO_AUDIT",
        "status": "PURCHASE_ELIGIBLE",
        "execution_authority_granted": False,
        "service_entitlement": {
            "service": "JANUS.REPO_AUDIT",
            "repository": "acme/demo",
            "ref": "main",
            "read_only": True,
            "execute_repository_code": False,
        },
    }
    body = {
        "schema": "janus.machine_market.home_repo_audit_packet.v1",
        "packet_id": "rap-1",
        "created_at": "2026-08-31T08:00:00Z",
        "sku": "JANUS.REPO_AUDIT",
        "market_repository": "Hawkar-usls/JANUS-MACHINE-MARKET",
        "home_repository": "Hawkar-usls/Hawkar-usls",
        "commerce_mode": "ZERO_PRICE_SHADOW",
        "money_enabled": False,
        "payment_reference": None,
        "purchase_grant": grant,
        "purchase_grant_hash": digest(grant),
        "service_request": request,
        "service_request_hash": request["request_hash"],
        "command_authority_granted": False,
        "external_effect_authorized": False,
        "repository_write_authorized": False,
        "execute_repository_code": False,
    }
    body["packet_hash"] = digest(body)
    return body


class MarketRepoAuditTest(unittest.TestCase):
    def test_zero_price_packet_valid(self):
        self.assertTrue(verify_packet(packet()))

    def test_repository_rebinding_invalid(self):
        p = packet()
        p["purchase_grant"]["service_entitlement"]["repository"] = "other/repo"
        p["purchase_grant_hash"] = digest(p["purchase_grant"])
        p["packet_hash"] = digest({k:v for k,v in p.items() if k != "packet_hash"})
        self.assertFalse(verify_packet(p))

    def test_execute_code_invalid(self):
        p = packet()
        p["execute_repository_code"] = True
        p["packet_hash"] = digest({k:v for k,v in p.items() if k != "packet_hash"})
        self.assertFalse(verify_packet(p))

    def test_home_response_seals_read_only_result(self):
        p = packet()
        audit = {
            "schema": "janus.market_service.repo_audit_result.v1",
            "status": "BOUNDED_REPOSITORY_AUDIT_COMPLETE",
            "request_id": "ra-1",
            "request_hash": p["service_request_hash"],
            "sku": "JANUS.REPO_AUDIT",
            "target": {"resolved_commit_sha": "a" * 40},
            "authority": {
                "read_only": True,
                "repository_write": False,
                "repository_code_executed": False,
                "command_authority_granted": False,
                "claim_authority_granted": False,
                "scientific_evidence_authority_granted": False,
                "world_truth_authority_granted": False,
                "external_effect_authorized": False,
            },
        }
        audit["result_hash"] = service_digest(audit)
        home = {
            "schema": "janus.market_service.repo_audit_home_receipt.v1",
            "request_id": "ra-1",
            "request_hash": p["service_request_hash"],
            "sku": "JANUS.REPO_AUDIT",
            "resident_uuid": "resident",
            "model_digest": "b" * 64,
            "file_fabric_digest": "c" * 64,
            "runtime_receipt_hash": "d" * 64,
            "home_receipt_hash": "e" * 64,
            "audit_result_hash": audit["result_hash"],
            "audit_result": audit,
            "same_resident_uuid": True,
            "return_home_verified": True,
        }
        out = build_home_response(packet=p, home_receipt=home, source_binding={"transport":"PHYSARIUS_CREDENTIALLESS_PULL"}, replayed=False)
        self.assertTrue(verify_home_response(out))
        self.assertFalse(out["repository_code_executed"])
        self.assertFalse(out["external_effect_authorized"])
        self.assertFalse(out["security_certification_granted"])


if __name__ == "__main__":
    unittest.main()
