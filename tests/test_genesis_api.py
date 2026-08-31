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
            "generator_version": "GENESIS_COMMAND_RUNTIME_R0.3.0",
            "player_position": {"x": 4.5, "y": -2.0},
            "world_settings": {"time": "DAY", "fog": 0.08},
            "discovered_chunk_coordinates": [[0, 0]],
            "explicit_world_mutations": [],
            "chronicle_tip_hash": "abc"
        }
    }


class GenesisAPITests(unittest.TestCase):
    def test_health_has_no_world_authority_and_lists_command_families(self):
        value = health()
        self.assertTrue(value["janus_api_available"])
        self.assertFalse(value["world_truth_authority"])
        self.assertFalse(value["external_effect_authorized"])
        for intent in ("SPAWN_ENTITY", "SET_ATMOSPHERE", "WORLD_TRANSFORM", "INSPECT"):
            self.assertIn(intent, value["intent_families"])

    def test_multilingual_build_commands_compile_to_same_mechanic_family(self):
        samples = ["build a lighthouse", "построй маяк", "побудуй маяк", "zbuduj latarnia", "baue einen leuchtturm", "construye un faro", "construis un phare"]
        for text in samples:
            with self.subTest(text=text):
                response = compile_intent(base_request(text))
                self.assertTrue(verify_response(response))
                self.assertEqual(response["intent_plan"]["kind"], "GENERATE_STRUCTURE")
                self.assertEqual(response["intent_plan"]["structure_kind"], "lighthouse")
                self.assertEqual(response["asset_requirements"][0]["preferred_provider"], "poly_haven")
                self.assertFalse(response["authority"]["world_mutation_authorized"])

    def test_spawn_castle_is_structure_not_entity(self):
        response = compile_intent(base_request("Spawn Castle"))
        self.assertEqual(response["intent_plan"]["kind"], "GENERATE_STRUCTURE")
        self.assertEqual(response["intent_plan"]["structure_kind"], "castle")

    def test_spawn_living_noun_is_entity(self):
        response = compile_intent(base_request("spawn dragon"))
        self.assertEqual(response["intent_plan"]["kind"], "SPAWN_ENTITY")
        self.assertIn("dragon", response["intent_plan"]["concept"])

    def test_generic_build_has_generic_structure_recipe(self):
        response = compile_intent(base_request("build a crystal observatory"))
        self.assertEqual(response["intent_plan"]["kind"], "GENERATE_STRUCTURE")
        self.assertEqual(response["intent_plan"]["structure_kind"], "generic_structure")

    def test_atmosphere_world_transform_and_inspect(self):
        night = compile_intent(base_request("сделай ночь и туман"))["intent_plan"]
        self.assertEqual(night["kind"], "SET_ATMOSPHERE")
        self.assertEqual(night["time"], "NIGHT")
        self.assertGreater(night["fog"], 0)
        hill = compile_intent(base_request("подними холм 6"))["intent_plan"]
        self.assertEqual(hill["kind"], "WORLD_TRANSFORM")
        self.assertEqual(hill["transform_kind"], "RAISE_HILL")
        inspect = compile_intent(base_request("осмотри что здесь"))["intent_plan"]
        self.assertEqual(inspect["kind"], "INSPECT")

    def test_multilingual_camera_and_distance(self):
        samples = {"first person": "FIRST_PERSON", "первое лицо": "FIRST_PERSON", "від третьої особи": "THIRD_PERSON", "isometrisch": "ISOMETRIC"}
        for text, expected in samples.items():
            with self.subTest(text=text):
                response = compile_intent(base_request(text))
                self.assertEqual(response["intent_plan"], {"kind": "SET_CAMERA", "camera": expected})
        distance = compile_intent(base_request("camera distance 12"))["intent_plan"]
        self.assertEqual(distance["kind"], "SET_CAMERA_DISTANCE")
        self.assertEqual(distance["distance"], 12.0)

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

    def test_unknown_text_is_visible_unresolved_not_guess(self):
        response = compile_intent(base_request("🜂 λ 非命令 こんにちは"))
        self.assertEqual(response["status"], "UNRESOLVED")
        self.assertEqual(response["intent_plan"]["kind"], "UNRESOLVED")
        self.assertEqual(response["intent_plan"]["reason"], "JANUS_SEMANTIC_TISSUE_REQUIRED")
        self.assertTrue(verify_response(response))


if __name__ == "__main__":
    unittest.main()
