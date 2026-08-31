from __future__ import annotations

import copy
import unittest

from janus_spi.dataset_scout_service import digest as service_digest
from janus_spi.market_dataset_scout import build_home_response, digest, verify_home_response, verify_packet


class MarketDatasetScoutTests(unittest.TestCase):
    def request(self):
        req = {
            "schema": "janus.market_service.dataset_scout_request.v1",
            "request_id": "ds-shadow-" + "b" * 48,
            "sku": "JANUS.DATASET_SCOUT",
            "buyer_actor_id": "github:Hawkar-usls",
            "query": "climate",
            "domain": "earth science",
            "date_range": None,
            "license_preferences": [],
            "format_preferences": [],
            "bounds": {"max_results": 5, "max_catalogs": 2, "per_catalog_timeout_seconds": 8},
            "read_only": True,
            "dataset_payload_download_authorized": False,
            "redistribution_authority_granted": False,
            "command_authority_granted": False,
            "external_effect_authorized": False,
        }
        req["request_hash"] = service_digest(req)
        return req

    def packet(self):
        req = self.request()
        grant = {
            "schema": "janus.machine_market.purchase_grant.v1",
            "purchase_id": "pur-ds-shadow-" + "c" * 32,
            "sku": "JANUS.DATASET_SCOUT",
            "status": "PURCHASE_ELIGIBLE",
            "execution_authority_granted": False,
            "service_entitlement": {"service": "JANUS.DATASET_SCOUT", "request_id": req["request_id"], "bounds": req["bounds"], "read_only": True, "dataset_payload_download_authorized": False, "redistribution_authority_granted": False},
            "reasons": ["ZERO_PRICE_SHADOW_SERVICE_TEST"],
        }
        packet = {
            "schema": "janus.machine_market.home_dataset_scout_packet.v1",
            "packet_id": "dsp-shadow-" + "d" * 48,
            "created_at": "2026-08-31T15:00:00Z",
            "sku": "JANUS.DATASET_SCOUT",
            "market_repository": "Hawkar-usls/JANUS-MACHINE-MARKET",
            "home_repository": "Hawkar-usls/Hawkar-usls",
            "commerce_mode": "ZERO_PRICE_SHADOW",
            "money_enabled": False,
            "payment_reference": None,
            "purchase_grant": grant,
            "purchase_grant_hash": digest(grant),
            "service_request": req,
            "service_request_hash": req["request_hash"],
            "return_route": {"repository": "Hawkar-usls/JANUS-MACHINE-MARKET", "source_issue_number": 16, "source_issue_id": 123},
            "command_authority_granted": False,
            "external_effect_authorized": False,
            "dataset_payload_download_authorized": False,
            "redistribution_authority_granted": False,
        }
        packet["packet_hash"] = digest(packet)
        return packet

    def home_receipt(self, packet):
        req = packet["service_request"]
        result = {
            "schema": "janus.market_service.dataset_scout_result.v1",
            "status": "BOUNDED_DATASET_SCOUT_COMPLETE",
            "request_id": req["request_id"],
            "request_hash": req["request_hash"],
            "query": req["query"], "domain": req["domain"], "date_range": None,
            "license_preferences": [], "format_preferences": [],
            "dataset_manifest": [{"catalog":"ZENODO","dataset_id":"1","title":"Climate","source_url":"https://zenodo.org/records/1","license_observation":"cc-by","formats":["csv"],"publication_date":"2026-01-01","metadata_only":True}],
            "source_urls": ["https://zenodo.org/records/1"],
            "license_observations": [{"source_url":"https://zenodo.org/records/1","observed":"cc-by","authoritative_license_determination":False}],
            "deduplication_notes": {"key":"normalized_source_url","duplicates_removed":0},
            "provenance": {"catalogs_attempted":["ZENODO"],"catalogs_succeeded":["ZENODO"],"catalog_failures":[],"catalog_attempt_receipts":[],"metadata_only":True,"silence_is_negative_evidence":False},
            "authority": {"read_only":True,"dataset_payload_downloaded":False,"redistribution_authority_granted":False,"license_authority_granted":False,"command_authority_granted":False,"claim_authority_granted":False,"scientific_evidence_authority_granted":False,"world_truth_authority_granted":False,"external_effect_authorized":False},
            "laws": ["DATASET METADATA != DATASET PAYLOAD"],
        }
        result["result_hash"] = service_digest(result)
        receipt = {
            "schema": "janus.market_service.dataset_scout_home_receipt.v1",
            "request_id": req["request_id"], "request_hash": req["request_hash"], "sku":"JANUS.DATASET_SCOUT",
            "resident_uuid":"75e514ab-be76-42c8-bcb3-fc9670164f96",
            "model_digest":"1"*64,"file_fabric_digest":"2"*64,"runtime_receipt_hash":"3"*64,
            "home_receipt_hash":"4"*64,
            "dataset_scout_result_hash":result["result_hash"],"dataset_scout_result":result,
            "same_resident_uuid":True,"return_home_verified":True,
        }
        return receipt

    def test_packet_and_response(self):
        packet = self.packet(); self.assertTrue(verify_packet(packet))
        response = build_home_response(packet=packet, home_receipt=self.home_receipt(packet), source_binding={"market_source_commit":"a"*40}, replayed=False)
        self.assertTrue(verify_home_response(response))
        self.assertFalse(response["dataset_payload_downloaded"])
        self.assertFalse(response["redistribution_authority_granted"])

    def test_packet_authority_tamper_fails(self):
        packet = self.packet(); bad = copy.deepcopy(packet); bad["dataset_payload_download_authorized"] = True
        self.assertFalse(verify_packet(bad))


if __name__ == "__main__":
    unittest.main()
