from __future__ import annotations

import copy
import unittest

from src.janus_spi.genesis_api import REQUEST_SCHEMA, GenesisAPIError
from src.janus_spi.genesis_scene_graph import (
    MAX_NODES,
    SCENE_GRAPH_SCHEMA,
    SCENE_GRAPH_VERSION,
    compile_scene_graph,
    topological_order,
    validate_scene_graph,
    verify_scene_graph_response,
)


def base_request(text: str) -> dict:
    return {
        "schema": REQUEST_SCHEMA,
        "request_id": "scene-test-1",
        "player_text": text,
        "canonical_world_state": {
            "world_id": "GENESIS_ONE_WORLD_R0",
            "world_seed": "genesis-one-world-r0",
            "generator_version": "GENESIS_COMMAND_RUNTIME_R0.3.0",
            "player_position": {"x": 4.5, "y": -2.0},
            "world_settings": {"time": "DAY", "fog": 0.08},
            "discovered_chunk_coordinates": [[0, 0]],
            "explicit_world_mutations": [],
            "chronicle_tip_hash": "abc",
        },
    }


def graph_for(text: str) -> dict:
    return compile_scene_graph(base_request(text))["scene_graph"]


class GenesisSceneGraphTests(unittest.TestCase):
    def test_complex_russian_scene_is_composition_not_single_tower(self):
        response = compile_scene_graph(
            base_request(
                "построй заброшенный собор на холме, одна башня разрушена, "
                "внутри орган, у входа белые деревья"
            )
        )
        self.assertTrue(verify_scene_graph_response(response))
        graph = response["scene_graph"]
        families = {node["family"] for node in graph["nodes"]}
        for family in {"TERRAIN", "MATERIAL", "STRUCTURE", "EFFECT", "ENTITY", "SOUND", "RULE"}:
            self.assertIn(family, families)
        roots = [node for node in graph["nodes"] if node["family"] == "STRUCTURE"]
        self.assertEqual(len(roots), 1)
        self.assertIn("cathedral", roots[0]["concept"])
        self.assertNotEqual(roots[0]["params"].get("structure_kind"), "tower")
        ruined = [node for node in graph["nodes"] if node["operation"] == "RUINED_TOWER"]
        self.assertEqual(len(ruined), 1)
        self.assertEqual(ruined[0]["depends_on"], [roots[0]["id"]])

    def test_deterministic_graph_ids_hash_and_receipt(self):
        a = compile_scene_graph(base_request("построй маяк"))
        b = compile_scene_graph(base_request("построй маяк"))
        self.assertEqual(a["receipt_hash"], b["receipt_hash"])
        self.assertEqual(a["scene_graph"]["graph_hash"], b["scene_graph"]["graph_hash"])
        self.assertEqual(
            [n["id"] for n in a["scene_graph"]["nodes"]],
            [n["id"] for n in b["scene_graph"]["nodes"]],
        )

    def test_spawn_castle_and_spawn_dragon_preserve_noun_aware_semantics(self):
        castle = graph_for("Spawn Castle")
        self.assertEqual(castle["nodes"][0]["family"], "STRUCTURE")
        self.assertEqual(castle["nodes"][0]["operation"], "GENERATE_STRUCTURE")
        self.assertEqual(castle["nodes"][0]["params"]["structure_kind"], "castle")
        dragon = graph_for("spawn dragon")
        self.assertEqual(dragon["nodes"][0]["family"], "ENTITY")
        self.assertEqual(dragon["nodes"][0]["operation"], "SPAWN_ENTITY")
        self.assertEqual(dragon["nodes"][0]["params"]["concept"], "dragon")

    def test_unknown_unicode_is_visible_failure_not_guessed_mutation(self):
        graph = graph_for("🜂 λ 非命令 こんにちは")
        self.assertEqual(len(graph["nodes"]), 1)
        node = graph["nodes"][0]
        self.assertEqual(node["family"], "INSPECTION")
        self.assertEqual(node["operation"], "VISIBLE_FAILURE")
        self.assertEqual(node["resource_units"], 0)
        self.assertIn("reason", node["params"])

    def test_graph_authority_boundary_and_partial_failure_policy(self):
        response = compile_scene_graph(base_request("build a lighthouse"))
        authority = response["authority"]
        self.assertFalse(authority["janus_graph_is_world_authority"])
        self.assertFalse(authority["model_output_is_command"])
        self.assertFalse(authority["world_mutation_authorized_by_janus"])
        self.assertFalse(authority["external_effect_authorized"])
        self.assertTrue(authority["genesis_validator_required"])
        policy = response["scene_graph"]["execution_policy"]
        self.assertTrue(policy["validate_whole_graph_before_first_mutation"])
        self.assertEqual(policy["partial_failure"], "DEPENDENTS_SKIP_FAILED_REQUIRED_ANCESTOR")
        self.assertTrue(policy["node_receipt_required"])
        self.assertTrue(policy["silent_noop_forbidden"])

    def test_cycle_is_rejected(self):
        graph = graph_for("build tower")
        first = graph["nodes"][0]
        second = copy.deepcopy(first)
        second["id"] = "n-aaaaaaaaaaaaaaaa"
        second["concept"] = "dependent"
        first["depends_on"] = [second["id"]]
        second["depends_on"] = [first["id"]]
        graph["nodes"] = [first, second]
        with self.assertRaisesRegex(GenesisAPIError, "SCENE_GRAPH_CYCLE"):
            topological_order(graph)

    def test_missing_dependency_is_rejected(self):
        graph = graph_for("build tower")
        graph["nodes"][0]["depends_on"] = ["n-deadbeefdeadbeef"]
        with self.assertRaisesRegex(GenesisAPIError, "SCENE_GRAPH_DEPENDENCY_MISSING"):
            topological_order(graph)

    def test_node_limit_is_rejected_before_execution(self):
        graph = graph_for("build tower")
        template = graph["nodes"][0]
        graph["nodes"] = []
        for index in range(MAX_NODES + 1):
            node = copy.deepcopy(template)
            node["id"] = f"n-{index:016x}"
            node["depends_on"] = []
            graph["nodes"].append(node)
        with self.assertRaisesRegex(GenesisAPIError, "SCENE_GRAPH_NODE_LIMIT"):
            topological_order(graph)

    def test_resource_limit_is_rejected(self):
        graph = graph_for("build tower")
        template = graph["nodes"][0]
        graph["nodes"] = []
        for index in range(9):
            node = copy.deepcopy(template)
            node["id"] = f"n-{index:016x}"
            node["resource_units"] = 16
            node["depends_on"] = []
            graph["nodes"].append(node)
        with self.assertRaisesRegex(GenesisAPIError, "SCENE_GRAPH_RESOURCE_LIMIT"):
            topological_order(graph)

    def test_depth_limit_is_rejected(self):
        graph = graph_for("build tower")
        template = graph["nodes"][0]
        nodes = []
        previous = None
        for index in range(9):
            node = copy.deepcopy(template)
            node["id"] = f"n-{index:016x}"
            node["resource_units"] = 1
            node["depends_on"] = [previous] if previous else []
            nodes.append(node)
            previous = node["id"]
        graph["nodes"] = nodes
        with self.assertRaisesRegex(GenesisAPIError, "SCENE_GRAPH_DEPTH_LIMIT"):
            topological_order(graph)

    def test_declared_limits_are_part_of_validator_contract(self):
        graph = graph_for("build tower")
        self.assertEqual(graph["schema"], SCENE_GRAPH_SCHEMA)
        self.assertEqual(graph["version"], SCENE_GRAPH_VERSION)
        broken = copy.deepcopy(graph)
        broken["limits"]["max_nodes"] += 1
        with self.assertRaisesRegex(GenesisAPIError, "SCENE_GRAPH_LIMITS_INVALID"):
            validate_scene_graph(broken)


if __name__ == "__main__":
    unittest.main()
