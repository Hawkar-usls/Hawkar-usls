from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, Mapping

from .activator import canonical_hash
from .genesis_scene_graph_r05 import compile_scene_graph as compile_scene_graph_r05


def compile_scene_graph(payload: Mapping[str, Any]) -> Dict[str, Any]:
    response = compile_scene_graph_r05(payload)
    graph = response["scene_graph"]
    canonical_json = json.dumps(graph, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    response["transport_proof"] = {
        "canonical_graph_json": canonical_json,
        "canonical_graph_utf8_sha256": hashlib.sha256(canonical_json.encode("utf-8")).hexdigest(),
        "verification": "HASH_EXACT_UTF8_STRING_THEN_PARSE_AND_STRUCTURALLY_COMPARE_TO_SCENE_GRAPH",
    }
    response.pop("receipt_hash", None)
    response["receipt_hash"] = canonical_hash(response)
    return response


__all__ = ["compile_scene_graph"]
