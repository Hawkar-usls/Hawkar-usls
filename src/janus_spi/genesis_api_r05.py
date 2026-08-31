from __future__ import annotations

from typing import Any, Dict, Mapping

from .activator import canonical_hash
from .genesis_api import compile_intent as compile_intent_r04
from .genesis_api import health as health_r04
from .genesis_api import _contains_any, _normalize

JUMP_LEXEMES = (
    "jump", "leap",
    "прыгни", "прыгай", "прыжок",
    "стрибни", "стрибай", "стрибок",
    "skocz", "skok",
    "spring", "springe", "sprung",
    "salta", "salto",
    "saute", "saut",
)


def health() -> Dict[str, Any]:
    payload = dict(health_r04())
    families = list(payload.get("intent_families") or [])
    if "JUMP" not in families:
        insert_at = families.index("MOVE") + 1 if "MOVE" in families else 0
        families.insert(insert_at, "JUMP")
    payload.update(
        {
            "api_version": "1.0.0+r0.5",
            "intent_families": families,
            "asset_federation_channels": ["material", "mesh", "audio", "mechanic"],
            "asset_federation_route": "GET /v1/genesis/assets/federated/search",
            "jump_is_world_mutation": False,
        }
    )
    return payload


def compile_intent(payload: Mapping[str, Any]) -> Dict[str, Any]:
    response = dict(compile_intent_r04(payload))
    text = _normalize(str(payload.get("player_text") or ""))
    if not _contains_any(text, JUMP_LEXEMES):
        return response
    response["status"] = "PROPOSED"
    response["intent_plan"] = {
        "kind": "JUMP",
        "canonical_world_mutation": False,
        "locomotion_only": True,
    }
    response["asset_requirements"] = []
    provenance = dict(response.get("provenance") or {})
    provenance["compiler"] = "janus_spi.genesis_api_r05.compile_intent"
    provenance["overlay"] = "PAROGRAD_KRIEGER_R0_5"
    response["provenance"] = provenance
    response.pop("receipt_hash", None)
    response["receipt_hash"] = canonical_hash(response)
    return response


__all__ = ["JUMP_LEXEMES", "compile_intent", "health"]
