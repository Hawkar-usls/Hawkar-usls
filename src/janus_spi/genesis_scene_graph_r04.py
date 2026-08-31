from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, Mapping

from .activator import canonical_hash
from .genesis_api import compile_intent
from .genesis_scene_graph import (
    SCENE_GRAPH_RESPONSE_SCHEMA,
    SCENE_GRAPH_SCHEMA,
    SCENE_GRAPH_VERSION,
    _build_node,
    _graph_limits,
    compile_scene_graph as compile_core_scene_graph,
    validate_scene_graph,
    verify_scene_graph_response,
)


def _norm(value: str) -> str:
    return " ".join(str(value or "").strip().lower().replace("ё", "е").split())


def _has(text: str, *fragments: str) -> bool:
    return any(fragment in text for fragment in fragments)


def _cathedral_scene(text: str) -> bool:
    return _has(text, "собор", "кафедраль", "cathedral", "церкв", "church")


def _graph_id(base: Mapping[str, Any]) -> str:
    body = json.dumps(
        {
            "request_id": base.get("request_id"),
            "world_state_hash": base.get("world_state_hash"),
            "normalized_text": base.get("normalized_text"),
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "sg-" + hashlib.sha256(body).hexdigest()[:24]


def _compile_cathedral(payload: Mapping[str, Any]) -> Dict[str, Any]:
    base = compile_intent(payload)
    text = _norm(str(payload.get("player_text") or ""))
    seed = str(base.get("action_seed") or "")
    nodes: list[Dict[str, Any]] = []

    def add(
        family: str,
        operation: str,
        concept: str,
        *,
        params: Mapping[str, Any] | None = None,
        deps: list[str] | None = None,
        required: bool = True,
        resource_units: int = 1,
    ) -> Dict[str, Any]:
        node = _build_node(
            seed,
            len(nodes),
            family,
            operation,
            concept,
            params=params,
            deps=deps,
            required=required,
            resource_units=resource_units,
        )
        nodes.append(node)
        return node

    hill = None
    if _has(text, "на холме", "на пагорбі", "on a hill", "on the hill", "auf einem hügel", "sur une colline"):
        hill = add(
            "TERRAIN",
            "WORLD_TRANSFORM",
            "scene hill",
            params={"transform_kind": "RAISE_HILL", "radius": 7.0, "amount": 2.8, "distance": 5.0},
            resource_units=3,
        )

    weathered = None
    if _has(text, "заброш", "покинут", "занедбан", "abandoned", "weathered", "ruined"):
        weathered = add(
            "MATERIAL",
            "RESOLVE_MATERIAL",
            "weathered stone",
            params={"query": "weathered old stone", "rights_required": "CC0", "fallback": "KRR_WEATHERED_STONE_R1"},
            required=False,
            resource_units=2,
        )

    root_dependencies = [node["id"] for node in (hill, weathered) if node]
    cathedral = add(
        "STRUCTURE",
        "GENERATE_STRUCTURE",
        "abandoned cathedral" if weathered else "cathedral",
        params={
            "structure_kind": "generic_structure",
            "placement": "IN_FRONT_OF_PLAYER",
            "distance": 5.0,
            "style": "CATHEDRAL_R0",
            "action_seed": seed,
        },
        deps=root_dependencies,
        resource_units=8,
    )

    if _has(text, "башня разруш", "башни разруш", "разрушенная башн", "зруйнована веж", "tower ruined", "tower is ruined", "ruined tower"):
        add(
            "EFFECT",
            "RUINED_TOWER",
            "ruined tower",
            params={"target": cathedral["id"], "visual_fallback": "GENERATE_RUINED_TOWER"},
            deps=[cathedral["id"]],
            required=False,
            resource_units=3,
        )

    organ = None
    if _has(text, "внутри орган", "всередині орган", "inside organ", "organ inside", "pipe organ"):
        organ = add(
            "ENTITY",
            "SPAWN_ENTITY",
            "pipe organ",
            params={
                "entity_kind": "architectural_prop",
                "concept": "pipe organ",
                "placement": "INSIDE_PARENT",
                "target": cathedral["id"],
                "action_seed": seed,
            },
            deps=[cathedral["id"]],
            resource_units=4,
        )
        add(
            "SOUND",
            "AUDIO_CUE",
            "cathedral organ ambience",
            params={"cue": "resolve", "profile": "ORGAN_DRONE_R0"},
            deps=[organ["id"]],
            required=False,
            resource_units=2,
        )

    grove = None
    if _has(text, "белые дерев", "білі дерев", "white trees", "white tree"):
        grove = add(
            "ENTITY",
            "SPAWN_GROUP",
            "white trees",
            params={
                "entity_kind": "tree_grove",
                "concept": "white trees",
                "count": 5,
                "appearance": "WHITE_BARK",
                "placement": "AT_ENTRANCE",
                "target": cathedral["id"],
                "action_seed": seed,
            },
            deps=[cathedral["id"]],
            resource_units=6,
        )

    if _has(text, "у входа", "біля входу", "at the entrance", "near the entrance"):
        add(
            "RULE",
            "SPATIAL_RELATION",
            "entrance placement relation",
            params={
                "relation": "AT_ENTRANCE",
                "target": cathedral["id"],
                "subject": grove["id"] if grove else None,
            },
            deps=[cathedral["id"]] + ([grove["id"]] if grove else []),
            required=False,
            resource_units=1,
        )

    graph: Dict[str, Any] = {
        "schema": SCENE_GRAPH_SCHEMA,
        "version": SCENE_GRAPH_VERSION,
        "graph_id": _graph_id(base),
        "request_id": base.get("request_id"),
        "normalized_text": base.get("normalized_text"),
        "action_seed": seed,
        "world_state_hash": base.get("world_state_hash"),
        "nodes": nodes,
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
            "compiler": "janus_spi.genesis_scene_graph_r04.compile_scene_graph",
            "base_intent_receipt_hash": base.get("receipt_hash"),
            "composition_policy": "SCENE_SUBJECT_PRECEDES_NESTED_DETAIL_NOUNS",
        },
    }
    graph["topological_order"] = validate_scene_graph(graph)
    graph["graph_hash"] = canonical_hash(graph)
    response: Dict[str, Any] = {
        "schema": SCENE_GRAPH_RESPONSE_SCHEMA,
        "api_version": SCENE_GRAPH_VERSION,
        "status": "PROPOSED_GRAPH",
        "request_id": base.get("request_id"),
        "scene_graph": graph,
        "authority": dict(graph["authority"]),
    }
    response["receipt_hash"] = canonical_hash(response)
    return response


def compile_scene_graph(payload: Mapping[str, Any]) -> Dict[str, Any]:
    text = _norm(str(payload.get("player_text") or ""))
    if _cathedral_scene(text):
        return _compile_cathedral(payload)
    response = compile_core_scene_graph(payload)
    graph = response.get("scene_graph") or {}
    provenance = dict(graph.get("provenance") or {})
    provenance["active_policy_overlay"] = "SCENE_SUBJECT_PRECEDES_NESTED_DETAIL_NOUNS"
    graph["provenance"] = provenance
    graph_without_hash = dict(graph)
    graph_without_hash.pop("graph_hash", None)
    graph["graph_hash"] = canonical_hash(graph_without_hash)
    response["scene_graph"] = graph
    response_without_hash = dict(response)
    response_without_hash.pop("receipt_hash", None)
    response["receipt_hash"] = canonical_hash(response_without_hash)
    return response


__all__ = [
    "SCENE_GRAPH_SCHEMA",
    "SCENE_GRAPH_RESPONSE_SCHEMA",
    "SCENE_GRAPH_VERSION",
    "compile_scene_graph",
    "validate_scene_graph",
    "verify_scene_graph_response",
]
