from __future__ import annotations

import copy
import hashlib
import json
import re
from typing import Any, Dict, Iterable, Mapping

from .activator import canonical_hash
from .genesis_api import GenesisAPIError, compile_intent

SCENE_GRAPH_SCHEMA = "janus.genesis.scene_graph.v1"
SCENE_GRAPH_RESPONSE_SCHEMA = "janus.genesis.scene_graph.response.v1"
SCENE_GRAPH_VERSION = "0.4.0"
MAX_NODES = 32
MAX_EDGES = 64
MAX_DEPTH = 8
MAX_RESOURCE_UNITS = 128
MAX_NODE_RESOURCE_UNITS = 16

NODE_FAMILIES = frozenset(
    {
        "STRUCTURE",
        "ENTITY",
        "MATERIAL",
        "ATMOSPHERE",
        "TERRAIN",
        "SOUND",
        "EFFECT",
        "PRESENTATION",
        "RULE",
        "INSPECTION",
        "NAVIGATION",
    }
)

INTENT_TO_FAMILY = {
    "GENERATE_STRUCTURE": "STRUCTURE",
    "SPAWN_ENTITY": "ENTITY",
    "SET_ATMOSPHERE": "ATMOSPHERE",
    "WORLD_TRANSFORM": "TERRAIN",
    "SET_CAMERA": "PRESENTATION",
    "SET_MIRROR": "PRESENTATION",
    "SET_CAMERA_DISTANCE": "PRESENTATION",
    "INSPECT": "INSPECTION",
    "MOVE": "NAVIGATION",
    "RETURN_TO_HEARTH": "NAVIGATION",
    "PLACE_MARK": "NAVIGATION",
}


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "").strip().lower().replace("ё", "е"))


def _has(text: str, words: Iterable[str]) -> bool:
    return any(word in text for word in words)


def _stable_id(seed: str, family: str, operation: str, concept: str, ordinal: int) -> str:
    body = f"{seed}|{ordinal}|{family}|{operation}|{concept}".encode("utf-8")
    return "n-" + hashlib.sha256(body).hexdigest()[:16]


def _copy_params(intent: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        str(k): copy.deepcopy(v)
        for k, v in intent.items()
        if k not in {"kind", "action_seed"} and v is not None
    }


def _node_from_intent(intent: Mapping[str, Any], seed: str, ordinal: int, deps: list[str] | None = None) -> Dict[str, Any] | None:
    kind = str(intent.get("kind") or "").upper()
    family = INTENT_TO_FAMILY.get(kind)
    if family is None:
        return None
    concept = str(intent.get("concept") or intent.get("query") or intent.get("label") or kind).strip()[:160]
    params = _copy_params(intent)
    return {
        "id": _stable_id(seed, family, kind, concept, ordinal),
        "family": family,
        "operation": kind,
        "concept": concept,
        "params": params,
        "depends_on": list(deps or []),
        "required": True,
        "resource_units": 3 if family in {"STRUCTURE", "ENTITY"} else 1,
    }


def _build_node(
    seed: str,
    ordinal: int,
    family: str,
    operation: str,
    concept: str,
    *,
    params: Mapping[str, Any] | None = None,
    deps: list[str] | None = None,
    required: bool = True,
    resource_units: int = 1,
) -> Dict[str, Any]:
    return {
        "id": _stable_id(seed, family, operation, concept, ordinal),
        "family": family,
        "operation": operation,
        "concept": str(concept)[:160],
        "params": dict(params or {}),
        "depends_on": list(deps or []),
        "required": bool(required),
        "resource_units": int(resource_units),
    }


def _graph_limits() -> Dict[str, int]:
    return {
        "max_nodes": MAX_NODES,
        "max_edges": MAX_EDGES,
        "max_depth": MAX_DEPTH,
        "max_resource_units": MAX_RESOURCE_UNITS,
        "max_node_resource_units": MAX_NODE_RESOURCE_UNITS,
    }


def topological_order(graph: Mapping[str, Any]) -> list[str]:
    nodes = graph.get("nodes")
    if not isinstance(nodes, list) or not nodes:
        raise GenesisAPIError("SCENE_GRAPH_NODES_REQUIRED")
    if len(nodes) > MAX_NODES:
        raise GenesisAPIError("SCENE_GRAPH_NODE_LIMIT")

    by_id: dict[str, Mapping[str, Any]] = {}
    edge_count = 0
    total_resources = 0
    for node in nodes:
        if not isinstance(node, Mapping):
            raise GenesisAPIError("SCENE_GRAPH_NODE_INVALID")
        node_id = str(node.get("id") or "")
        if not re.fullmatch(r"n-[0-9a-f]{16}", node_id):
            raise GenesisAPIError("SCENE_GRAPH_NODE_ID_INVALID")
        if node_id in by_id:
            raise GenesisAPIError("SCENE_GRAPH_NODE_ID_DUPLICATE")
        family = str(node.get("family") or "").upper()
        if family not in NODE_FAMILIES:
            raise GenesisAPIError("SCENE_GRAPH_FAMILY_NOT_ALLOWLISTED")
        operation = str(node.get("operation") or "")
        if not operation or len(operation) > 64:
            raise GenesisAPIError("SCENE_GRAPH_OPERATION_INVALID")
        params = node.get("params")
        if not isinstance(params, Mapping):
            raise GenesisAPIError("SCENE_GRAPH_PARAMS_INVALID")
        deps = node.get("depends_on")
        if not isinstance(deps, list) or len(deps) > MAX_NODES:
            raise GenesisAPIError("SCENE_GRAPH_DEPENDENCIES_INVALID")
        units = int(node.get("resource_units") or 0)
        if units < 0 or units > MAX_NODE_RESOURCE_UNITS:
            raise GenesisAPIError("SCENE_GRAPH_NODE_RESOURCE_LIMIT")
        total_resources += units
        edge_count += len(deps)
        by_id[node_id] = node

    if edge_count > MAX_EDGES:
        raise GenesisAPIError("SCENE_GRAPH_EDGE_LIMIT")
    if total_resources > MAX_RESOURCE_UNITS:
        raise GenesisAPIError("SCENE_GRAPH_RESOURCE_LIMIT")

    outgoing: dict[str, list[str]] = {node_id: [] for node_id in by_id}
    indegree: dict[str, int] = {node_id: 0 for node_id in by_id}
    depth: dict[str, int] = {node_id: 1 for node_id in by_id}
    for node_id, node in by_id.items():
        for raw_dep in node.get("depends_on") or []:
            dep = str(raw_dep)
            if dep == node_id:
                raise GenesisAPIError("SCENE_GRAPH_SELF_CYCLE")
            if dep not in by_id:
                raise GenesisAPIError("SCENE_GRAPH_DEPENDENCY_MISSING")
            outgoing[dep].append(node_id)
            indegree[node_id] += 1

    ready = sorted(node_id for node_id, degree in indegree.items() if degree == 0)
    order: list[str] = []
    while ready:
        node_id = ready.pop(0)
        order.append(node_id)
        for child in sorted(outgoing[node_id]):
            depth[child] = max(depth[child], depth[node_id] + 1)
            if depth[child] > MAX_DEPTH:
                raise GenesisAPIError("SCENE_GRAPH_DEPTH_LIMIT")
            indegree[child] -= 1
            if indegree[child] == 0:
                ready.append(child)
                ready.sort()
    if len(order) != len(by_id):
        raise GenesisAPIError("SCENE_GRAPH_CYCLE")
    return order


def validate_scene_graph(graph: Mapping[str, Any]) -> list[str]:
    if graph.get("schema") != SCENE_GRAPH_SCHEMA:
        raise GenesisAPIError("SCENE_GRAPH_SCHEMA_INVALID")
    if graph.get("version") != SCENE_GRAPH_VERSION:
        raise GenesisAPIError("SCENE_GRAPH_VERSION_INVALID")
    limits = graph.get("limits")
    if not isinstance(limits, Mapping) or dict(limits) != _graph_limits():
        raise GenesisAPIError("SCENE_GRAPH_LIMITS_INVALID")
    return topological_order(graph)


def _compose_nodes(payload: Mapping[str, Any], base_response: Mapping[str, Any]) -> list[Dict[str, Any]]:
    raw = str(payload.get("player_text") or "")
    text = _norm(raw)
    seed = str(base_response.get("action_seed") or "")
    nodes: list[Dict[str, Any]] = []
    signatures: set[str] = set()

    def add(node: Dict[str, Any]) -> Dict[str, Any]:
        signature = canonical_hash(
            {
                "family": node["family"],
                "operation": node["operation"],
                "concept": node["concept"],
                "params": node["params"],
                "depends_on": node["depends_on"],
            }
        )
        if signature in signatures:
            return next(existing for existing in nodes if existing.get("_signature") == signature)
        node["_signature"] = signature
        signatures.add(signature)
        nodes.append(node)
        return node

    # Scene anchors that are implicit in natural composition, not separate imperative clauses.
    hill = None
    if _has(text, ("на холме", "на пагорбі", "on a hill", "on the hill", "auf einem hügel", "sur une colline")):
        hill = add(
            _build_node(
                seed,
                len(nodes),
                "TERRAIN",
                "WORLD_TRANSFORM",
                "scene hill",
                params={"transform_kind": "RAISE_HILL", "radius": 7.0, "amount": 2.8, "distance": 5.0},
                resource_units=3,
            )
        )

    weathered = None
    if _has(text, ("заброш", "покинут", "abandoned", "ruined", "weathered", "занедбан")):
        weathered = add(
            _build_node(
                seed,
                len(nodes),
                "MATERIAL",
                "RESOLVE_MATERIAL",
                "weathered stone",
                params={"query": "weathered old stone", "rights_required": "CC0", "fallback": "KRR_WEATHERED_STONE_R1"},
                required=False,
                resource_units=2,
            )
        )

    base_intent = base_response.get("intent_plan") or {}
    primary = None
    if isinstance(base_intent, Mapping) and str(base_intent.get("kind") or "") != "UNRESOLVED":
        deps: list[str] = []
        family = INTENT_TO_FAMILY.get(str(base_intent.get("kind") or "").upper())
        if family == "STRUCTURE":
            if hill:
                deps.append(hill["id"])
            if weathered:
                deps.append(weathered["id"])
        primary_node = _node_from_intent(base_intent, seed, len(nodes), deps)
        if primary_node:
            primary = add(primary_node)

    # If a structure-rich sentence was unresolved by the R0.3 single-intent compiler,
    # preserve bounded composition instead of guessing arbitrary executable code.
    if primary is None and _has(text, ("собор", "cathedral", "кафедраль", "церкв", "church")):
        deps = [node["id"] for node in (hill, weathered) if node]
        primary = add(
            _build_node(
                seed,
                len(nodes),
                "STRUCTURE",
                "GENERATE_STRUCTURE",
                "abandoned cathedral" if weathered else "cathedral",
                params={"structure_kind": "generic_structure", "placement": "IN_FRONT_OF_PLAYER", "distance": 5.0, "style": "CATHEDRAL_R0"},
                deps=deps,
                resource_units=8,
            )
        )

    primary_id = primary["id"] if primary and primary.get("family") == "STRUCTURE" else None

    if primary_id and _has(text, ("башня разруш", "башни разруш", "tower is ruined", "tower ruined", "зруйнована веж", "разрушенная башн")):
        add(
            _build_node(
                seed,
                len(nodes),
                "EFFECT",
                "RUINED_TOWER",
                "ruined tower",
                params={"target": primary_id, "visual_fallback": "GENERATE_RUINED_TOWER"},
                deps=[primary_id],
                required=False,
                resource_units=3,
            )
        )

    organ = None
    if primary_id and _has(text, ("внутри орган", "inside organ", "organ inside", "всередині орган", "pipe organ")):
        organ = add(
            _build_node(
                seed,
                len(nodes),
                "ENTITY",
                "SPAWN_ENTITY",
                "pipe organ",
                params={"entity_kind": "architectural_prop", "placement": "INSIDE_PARENT", "target": primary_id},
                deps=[primary_id],
                resource_units=4,
            )
        )
        add(
            _build_node(
                seed,
                len(nodes),
                "SOUND",
                "AUDIO_CUE",
                "cathedral organ ambience",
                params={"cue": "resolve", "profile": "ORGAN_DRONE_R0"},
                deps=[organ["id"]],
                required=False,
                resource_units=2,
            )
        )

    if primary_id and _has(text, ("белые дерев", "білі дерев", "white trees", "white tree")):
        add(
            _build_node(
                seed,
                len(nodes),
                "ENTITY",
                "SPAWN_GROUP",
                "white trees",
                params={"entity_kind": "tree_grove", "count": 5, "appearance": "WHITE_BARK", "placement": "AT_ENTRANCE", "target": primary_id},
                deps=[primary_id],
                resource_units=6,
            )
        )

    if primary_id and _has(text, ("у входа", "біля входу", "at the entrance", "near the entrance")):
        add(
            _build_node(
                seed,
                len(nodes),
                "RULE",
                "SPATIAL_RELATION",
                "entrance placement relation",
                params={"relation": "AT_ENTRANCE", "target": primary_id},
                deps=[primary_id],
                required=False,
                resource_units=1,
            )
        )

    for node in nodes:
        node.pop("_signature", None)
    return nodes


def compile_scene_graph(payload: Mapping[str, Any]) -> Dict[str, Any]:
    base = compile_intent(payload)
    nodes = _compose_nodes(payload, base)
    if not nodes:
        # Preserve unresolved semantics visibly; never invent an executable scene.
        seed = str(base.get("action_seed") or "")
        nodes = [
            _build_node(
                seed,
                0,
                "INSPECTION",
                "VISIBLE_FAILURE",
                "unresolved player command",
                params={"reason": (base.get("intent_plan") or {}).get("reason", "JANUS_SEMANTIC_TISSUE_REQUIRED")},
                required=False,
                resource_units=0,
            )
        ]

    graph_id = "sg-" + hashlib.sha256(
        json.dumps(
            {
                "request_id": base.get("request_id"),
                "world_state_hash": base.get("world_state_hash"),
                "normalized_text": base.get("normalized_text"),
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()[:24]

    graph: Dict[str, Any] = {
        "schema": SCENE_GRAPH_SCHEMA,
        "version": SCENE_GRAPH_VERSION,
        "graph_id": graph_id,
        "request_id": base.get("request_id"),
        "normalized_text": base.get("normalized_text"),
        "action_seed": base.get("action_seed"),
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
            "compiler": "janus_spi.genesis_scene_graph.compile_scene_graph",
            "base_intent_receipt_hash": base.get("receipt_hash"),
        },
    }
    order = validate_scene_graph(graph)
    graph["topological_order"] = order
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


def verify_scene_graph_response(response: Mapping[str, Any]) -> bool:
    if response.get("schema") != SCENE_GRAPH_RESPONSE_SCHEMA:
        return False
    core = dict(response)
    claimed = str(core.pop("receipt_hash", ""))
    if len(claimed) != 64 or canonical_hash(core) != claimed:
        return False
    graph = response.get("scene_graph")
    if not isinstance(graph, Mapping):
        return False
    graph_core = dict(graph)
    graph_claimed = str(graph_core.pop("graph_hash", ""))
    if len(graph_claimed) != 64 or canonical_hash(graph_core) != graph_claimed:
        return False
    try:
        order = validate_scene_graph(graph)
    except GenesisAPIError:
        return False
    if list(graph.get("topological_order") or []) != order:
        return False
    authority = response.get("authority") or {}
    return (
        authority.get("janus_graph_is_world_authority") is False
        and authority.get("model_output_is_command") is False
        and authority.get("genesis_validator_required") is True
        and authority.get("world_mutation_authorized_by_janus") is False
        and authority.get("external_effect_authorized") is False
    )
