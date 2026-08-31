from __future__ import annotations

import unittest

from src.janus_spi.genesis_api import REQUEST_SCHEMA, compile_intent, health, verify_response


def base_request(text: str) -> dict:
    return {
        "schema": REQUEST_SCHEMA,
        "request_id": "test-1",
        "player_text": text,
        "canonical_world_state": {
            "world_id": "GENESIS_ONE_WORLD_R0",
            "world_seed": "genesis-one-world-r0",
            "generator_version": "GENESIS_WORLD_SHELL_R0.1.0",
            "player_position": {"x": 4.5, "y": -2.0},
            "discovered_chunk_coordinates": [[0, 0]],
            "explicit_world_mutations": [],
            "chronicle_tip_hash": "abc"
        }
    }


class GenesisAPITests(unittest.TestCase):
    def test_health_has_no_world_authority(self):
        value = health()
        self.assertTrue(value["janus_api_available"])
        self.assertFalse(value["world_truth_authority"])
        self.assertFalse(value["external_effect_authorized"])

    def test_multilingual_build_commands_compile_to_same_mechanic_family(self):
        samples = [
            "build a lighthouse",
            "построй маяк",
            "побудуй маяк",
            "zbuduj latarnia",
            "baue einen leuchtturm",
            "construye un faro",
            "construis un phare",
        ]
        for text in samples:
            with self.subTest(text=text):
                response = compile_intent(base_request(text))
                self.assertTrue(verify_response(response))
                self.assertEqual(response["intent_plan"]["kind"], "GENERATE_STRUCTURE")
                self.assertEqual(response["asset_requirements"][0]["preferred_provider"], "poly_haven")
                self.assertFalse(response["authority"]["world_mutation_authorized"])

    def test_multilingual_camera(self):
        samples = {
            "first person": "FIRST_PERSON",
            "первое лицо": "FIRST_PERSON",
            "від третьої особи": "THIRD_PERSON",
            "isometrisch": "ISOMETRIC",
        }
        for text, expected in samples.items():
            with self.subTest(text=text):
                response = compile_intent(base_request(text))
                self.assertEqual(response["intent_plan"], {"kind": "SET_CAMERA", "camera": expected})

    def test_same_world_and_text_same_seed(self):
        a = compile_intent(base_request("построй маяк"))
        b = compile_intent(base_request("построй маяк"))
        self.assertEqual(a["action_seed"], b["action_seed"])
        self.assertEqual(a["receipt_hash"], b["receipt_hash"])

    def test_world_change_changes_action_seed(self):
        a = base_request("build tower")
        b = base_request("build tower")
        b["canonical_world_state"]["player_position"] = {"x": 5.5, "y": -2.0}
        self.assertNotEqual(compile_intent(a)["action_seed"], compile_intent(b)["action_seed"])

    def test_unknown_text_fails_to_unresolved_not_guess(self):
        response = compile_intent(base_request("🜂 λ 非命令 こんにちは"))
        self.assertEqual(response["status"], "UNRESOLVED")
        self.assertEqual(response["intent_plan"]["kind"], "UNRESOLVED")
        self.assertTrue(verify_response(response))


if __name__ == "__main__":
    unittest.main()
