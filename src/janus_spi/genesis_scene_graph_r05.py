from __future__ import annotations

from typing import Any, Dict, Mapping

from .activator import canonical_hash
from .genesis_api_r05 import compile_intent as compile_intent_r05
from .genesis_scene_graph import (
    SCENE_GRAPH_RESPONSE_SCHEMA,
    SCENE_GRAPH_SCHEMA,
    _build_node,
    _graph_limits,
    validate_scene_graph,
)
from .genesis_scene_graph_r04 import compile_scene_graph as compile_scene_graph_r04

ALLOWED_OPERATIONS = {
    "STRUCTURE": {"GENERATE_STRUCTURE"},
    "ENTITY": {"SPAWN_ENTITY", "SPAWN_GROUP"},
    "MATERIAL": {"RESOLVE_MATERIAL"},
    "ATMOSPHERE": {"SET_ATMOSPHERE"},
    "TERRAIN": {"WORLD_TRANSFORM"},
    "SOUND": {"AUDIO_CUE"},
    "EFFECT": {"RUINED_TOWER"},
    "PRESENTATION": {"SET_CAMERA", "SET_MIRROR", "SET_CAMERA_DISTANCE"},
    "RULE": {"SPATIAL_RELATION"},
    "INSPECTION": {"INSPECT", "VISIBLE_FAILURE"},
    "NAVIGATION": {"MOVE", "JUMP", "RETURN_TO_HEARTH", "PLACE_MARK"},
}


def _validate_operations(graph: Mapping[str, Any]) -> None:
    for node in graph.get("nodes") or []:
        family = str(node.get("family") or "")
        operation = str(node.get("operation") or "")
        if operation not in ALLOWED_OPERATIONS.get(family, set()):
            raise ValueError("SCENE_GRAPH_OPERATION_NOT_ALLOWLISTED")
        params = node.get("params") or {}
        for key in params:
            if str(key).lower() in {"eval", "code", "source_code", "script", "shell", "exec", "module", "import", "require"}:
                raise ValueError("SCENE_GRAPH_ARBITRARY_CODE_FIELD_FORBIDDEN")


def _jump_graph(payload: Mapping[str, Any]) -> Dict[str, Any]:
    base = compile_intent_r05(payload)
    seed = str(base.get("action_seed") or "")
    node = _build_node(
        seed,
        0,
        "NAVIGATION",
        "JUMP",
        "jump",
        params={"canonical_world_mutation": False, "locomotion_only": True},
        deps=[],
        required=True,
        resource_units=1,
    )
    graph: Dict[str, Any] = {
        "schema": SCENE_GRAPH_SCHEMA,
        "version": "0.4.0",
        "graph_id": "sg-" + canonical_hash({"seed": seed, "request_id": base.get("request_id"), "kind": "JUMP"})[:24],
        "request_id": base.get("request_id"),
        "normalized_text": base.get("normalized_text"),
        "action_seed": seed,
        "world_state_hash": base.get("world_state_hash"),
        "nodes": [node],
        "limits": _graph_limits(),
        "execution_policy": {
            "order": "TOPOLOGICAL",
            "validate_whole_graph_before_first_mutation": True,
            "partial_failure": "DEPENDENTS_SKIP_FAILED_REQUIRED_ANCESTOR",
            "successful_prior_nodes_are_not_silently_rolled_back": True,
            "node_receipt_required": True,
            "silent_noop_forbidden": True,
        },
        "authority": {
            "janus_graph_is_world_authority": False,
            "model_output_is_command": False,
            "genesis_validator_required": True,
            "world_mutation_authorized_by_janus": False,
            "external_effect_authorized": False,
        },
        "provenance": {
            "home_repository": "Hawkar-usls/Hawkar-usls",
            "compiler": "janus_spi.genesis_scene_graph_r05.compile_scene_graph",
            "base_intent_receipt_hash": base.get("receipt_hash"),
            "overlay": "PAROGRAD_KRIEGER_R0_5",
        },
    }
    graph["topological_order"] = validate_scene_graph(graph)
    _validate_operations(graph)
    graph["graph_hash"] = canonical_hash(graph)
    response: Dict[str, Any] = {
        "schema": SCENE_GRAPH_RESPONSE_SCHEMA,
        "api_version": "0.4.0+r0.5",
        "status": "PROPOSED_GRAPH",
        "request_id": base.get("request_id"),
        "scene_graph": graph,
        "authority": dict(graph["authority"]),
    }
    response["receipt_hash"] = canonical_hash(response)
    return response


def compile_scene_graph(payload: Mapping[str, Any]) -> Dict[str, Any]:
    base = compile_intent_r05(payload)
    if (base.get("intent_plan") or {}).get("kind") == "JUMP":
        return _jump_graph(payload)
    response = compile_scene_graph_r04(payload)
    _validate_operations(response.get("scene_graph") or {})
    return response


__all__ = ["ALLOWED_OPERATIONS", "compile_scene_graph"]
