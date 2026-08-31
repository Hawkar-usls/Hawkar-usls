from __future__ import annotations

import unittest
from unittest.mock import patch

from janus_spi.genesis_api_r05 import compile_intent, health
from janus_spi.genesis_asset_federation_r05 import PROVIDERS, federated_search
from janus_spi.genesis_scene_graph_transport_r05 import compile_scene_graph


WORLD = {
    "world_id": "GENESIS_ONE_WORLD_R0",
    "world_seed": "genesis-one-world-r0",
    "generator_version": "GENESIS_COMMAND_RUNTIME_R0.3.0",
    "player_position": {"x": 0.5, "y": 0.5},
    "world_settings": {"time": "DAY", "fog": 0.08},
    "discovered_chunk_coordinates": [[0, 0]],
    "explicit_world_mutations": [],
    "chronicle_tip_hash": "GENESIS",
}


def payload(text: str):
    return {"schema": "janus.genesis.api.request.v1", "request_id": "r05-test", "player_text": text, "canonical_world_state": WORLD}


class GenesisParogradKriegerR05Tests(unittest.TestCase):
    def test_jump_compiles_multilingually_without_world_mutation_authority(self):
        for text in ("jump", "прыгни", "стрибни", "skocz", "springe", "salta", "saute"):
            out = compile_intent(payload(text))
            self.assertEqual(out["intent_plan"]["kind"], "JUMP")
            self.assertFalse(out["intent_plan"]["canonical_world_mutation"])
            self.assertTrue(out["authority"]["genesis_validator_required"])
            self.assertFalse(out["authority"]["world_mutation_authorized"])

    def test_jump_scene_graph_is_bounded_navigation_node(self):
        out = compile_scene_graph(payload("прыгни"))
        graph = out["scene_graph"]
        self.assertEqual(len(graph["nodes"]), 1)
        node = graph["nodes"][0]
        self.assertEqual(node["family"], "NAVIGATION")
        self.assertEqual(node["operation"], "JUMP")
        self.assertFalse(node["params"]["canonical_world_mutation"])
        self.assertEqual(graph["topological_order"], [node["id"]])
        self.assertEqual(len(graph["graph_hash"]), 64)
        self.assertEqual(len(out["receipt_hash"]), 64)
        self.assertEqual(len(out["transport_proof"]["canonical_graph_utf8_sha256"]), 64)

    def test_health_advertises_exact_r05_channels_without_live_host_claim(self):
        out = health()
        self.assertIn("JUMP", out["intent_families"])
        self.assertEqual(out["asset_federation_channels"], ["material", "mesh", "audio", "mechanic"])
        self.assertFalse(out["jump_is_world_mutation"])

    def test_provider_matrix_does_not_promote_registered_to_live(self):
        providers = {row["provider_id"]: row for row in PROVIDERS}
        self.assertEqual(providers["poly_haven"]["status"], "LIVE_ADAPTER")
        self.assertEqual(providers["wikimedia_commons"]["status"], "LIVE_METADATA_ADAPTER")
        self.assertEqual(providers["openverse"]["status"], "DISCOVERY_ONLY")
        self.assertIn("DISABLED_CONDITIONAL", providers["freesound"]["status"])
        self.assertIn("ADAPTER_PENDING", providers["ambientcg"]["status"])
        self.assertEqual(providers["genesis_mechanic_forge"]["status"], "LOCAL_RECIPE_FORGE")

    @patch("janus_spi.genesis_asset_federation_r05._json_url")
    def test_polyhaven_material_result_is_cc0_direct_cdn_not_slime(self, get_json):
        def fake(url, timeout=8.0):
            if "/files/" in url:
                return {"Diffuse": {"1k": {"jpg": {"url": "https://cdn.example/stone.jpg", "size": 1000}}}}
            return {"stone_floor": {"name": "Stone Floor", "description": "old stone floor", "tags": ["stone"]}}
        get_json.side_effect = fake
        out = federated_search("material", "stone", 2)
        self.assertTrue(out["results"])
        ref = out["results"][0]
        self.assertEqual(ref["provider_id"], "poly_haven")
        self.assertEqual(ref["rights"], "CC0")
        self.assertEqual(ref["binary_transport"], "DIRECT_PROVIDER_CDN_NOT_SLIME")
        self.assertEqual(ref["download_pointer"], "https://cdn.example/stone.jpg")

    @patch("janus_spi.genesis_asset_federation_r05._json_url")
    def test_wikimedia_audio_item_level_rights_gate(self, get_json):
        get_json.return_value = {
            "query": {"pages": {"1": {"pageid": 1, "title": "File:wind.ogg", "imageinfo": [{
                "mime": "audio/ogg", "url": "https://upload.example/wind.ogg", "descriptionurl": "https://commons.example/wind",
                "extmetadata": {"LicenseShortName": {"value": "CC BY-SA 4.0"}, "LicenseUrl": {"value": "https://creativecommons.org/licenses/by-sa/4.0/"}, "Artist": {"value": "Author"}}
            }]}}}
        }
        out = federated_search("audio", "wind", 2)
        self.assertEqual(len(out["results"]), 1)
        ref = out["results"][0]
        self.assertEqual(ref["rights"], "CC-BY-SA")
        self.assertTrue(ref["attribution_required"])
        self.assertEqual(ref["binary_transport"], "DIRECT_PROVIDER_CDN_NOT_SLIME")

    @patch("janus_spi.genesis_asset_federation_r05._json_url")
    def test_unknown_wikimedia_rights_fail_closed(self, get_json):
        get_json.return_value = {
            "query": {"pages": {"1": {"pageid": 1, "title": "File:mystery.ogg", "imageinfo": [{
                "mime": "audio/ogg", "url": "https://upload.example/mystery.ogg", "descriptionurl": "https://commons.example/mystery",
                "extmetadata": {"LicenseShortName": {"value": "Unknown custom license"}}
            }]}}}
        }
        out = federated_search("audio", "mystery", 2)
        self.assertEqual(out["results"], [])
        self.assertEqual(out["rights_gate"], "PER_REFERENCE_FAIL_CLOSED")

    def test_mechanic_channel_never_fabricates_remote_executable_code(self):
        out = federated_search("mechanic", "rotating lighthouse", 4)
        self.assertEqual(out["results"], [])
        self.assertFalse(out["foreign_code_execution"])
        self.assertTrue(out["procedural_fallback_required"])


if __name__ == "__main__":
    unittest.main()
