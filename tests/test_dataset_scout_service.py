from __future__ import annotations

import copy
import unittest

from janus_spi.dataset_scout_service import digest, scout_public_datasets, verify_request, verify_result


class DatasetScoutServiceTests(unittest.TestCase):
    def request(self):
        req = {
            "schema": "janus.market_service.dataset_scout_request.v1",
            "request_id": "ds-shadow-" + "a" * 48,
            "sku": "JANUS.DATASET_SCOUT",
            "buyer_actor_id": "github:Hawkar-usls",
            "query": "climate",
            "domain": "earth science",
            "date_range": None,
            "license_preferences": ["cc-by"],
            "format_preferences": ["csv"],
            "bounds": {"max_results": 5, "max_catalogs": 2, "per_catalog_timeout_seconds": 8},
            "read_only": True,
            "dataset_payload_download_authorized": False,
            "redistribution_authority_granted": False,
            "command_authority_granted": False,
            "external_effect_authorized": False,
        }
        req["request_hash"] = digest(req)
        return req

    @staticmethod
    def fake_get(url, timeout):
        if "zenodo.org" in url:
            return {"hits": {"hits": [{
                "id": 101,
                "metadata": {"title": "Climate observations", "license": {"id": "cc-by-4.0"}, "publication_date": "2026-01-01"},
                "links": {"html": "https://zenodo.org/records/101"},
                "files": [{"key": "observations.csv"}],
            }]}}
        if "huggingface.co" in url:
            return [{"id": "janus/climate-demo", "tags": ["license:apache-2.0", "format:parquet"]}]
        raise RuntimeError("unexpected catalog")

    def test_metadata_only_result(self):
        request = self.request()
        self.assertTrue(verify_request(request))
        result = scout_public_datasets(request, get_json=self.fake_get)
        self.assertTrue(verify_result(result, request=request))
        self.assertGreaterEqual(len(result["dataset_manifest"]), 1)
        self.assertFalse(result["authority"]["dataset_payload_downloaded"])
        self.assertFalse(result["authority"]["redistribution_authority_granted"])
        self.assertTrue(result["provenance"]["metadata_only"])

    def test_request_authority_tamper_fails(self):
        request = self.request(); bad = copy.deepcopy(request)
        bad["redistribution_authority_granted"] = True
        self.assertFalse(verify_request(bad))

    def test_all_catalog_failure_is_not_delivery(self):
        def fail(url, timeout):
            raise TimeoutError("blocked")
        with self.assertRaisesRegex(RuntimeError, "UNKNOWN_RESOURCE_LIMIT"):
            scout_public_datasets(self.request(), get_json=fail)


if __name__ == "__main__":
    unittest.main()
