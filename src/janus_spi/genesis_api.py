from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Mapping

from .activator import canonical_hash

REQUEST_SCHEMA = "janus.genesis.api.request.v1"
RESPONSE_SCHEMA = "janus.genesis.api.response.v1"
HEALTH_SCHEMA = "janus.genesis.api.health.v1"
API_VERSION = "1.0.0"
MAX_TEXT_CHARS = 2000
MAX_CONCEPT_CHARS = 96
MAX_STEPS = 64


class GenesisAPIError(RuntimeError):
    pass


@dataclass(frozen=True)
class LexemeSet:
    values: tuple[str, ...]

    def find(self, text: str) -> bool:
        return any(v in text for v in self.values)


CREATE = LexemeSet((
    "build", "create", "make", "place", "spawn", "construct",
    "построй", "построить", "создай", "создать", "сделай", "поставь", "размести",
    "побудуй", "створи", "зроби", "постав", "розмісти",
    "zbuduj", "stworz", "postaw", "umiesc",
    "baue", "bauen", "erschaffe", "platziere",
    "construye", "crear", "crea", "coloca",
    "construis", "cree", "creer", "place",
))
MOVE = LexemeSet((
    "go", "walk", "move", "travel", "step", "run", "explore", "wander",
    "иди", "идти", "двигай", "двигаться", "пройди", "беги", "исследуй", "броди",
    "йди", "рухайся", "пройди", "біжи", "досліджуй", "мандруй",
    "idz", "rusz", "biegnij", "eksploruj",
    "geh", "gehe", "lauf", "erkunde",
    "ve", "camina", "muevete", "explora",
    "va", "marche", "deplace", "explore",
))
RETURN = LexemeSet((
    "return", "home", "hearth", "back to fire",
    "вернись", "вернуться", "домой", "к огню", "к костру",
    "повернись", "додому", "до вогню",
    "wroc", "domu", "ognia",
    "zuruck", "heim", "feuer",
    "regresa", "casa", "fuego",
    "retourne", "maison", "feu",
))
MARK = LexemeSet((
    "mark", "sign", "leave a mark", "beacon marker",
    "метка", "метку", "знак", "оставь знак", "оставь метку",
    "мітка", "познач", "залиш знак",
    "znak", "znacznik",
    "markierung", "zeichen",
    "marca", "senal",
    "marque", "signe",
))

DIRECTION_ALIASES = {
    "N": ("north", "север", "північ", "polnoc", "norden", "norte", "nord"),
    "NE": ("north east", "northeast", "северо-вост", "північний схід", "polnocny wschod", "nordost", "noreste", "nord-est"),
    "E": ("east", "восток", "схід", "wschod", "osten", "este", "est"),
    "SE": ("south east", "southeast", "юго-вост", "південний схід", "poludniowy wschod", "sudost", "sureste", "sud-est"),
    "S": ("south", "юг", "південь", "poludnie", "suden", "sur", "sud"),
    "SW": ("south west", "southwest", "юго-зап", "південний захід", "poludniowy zachod", "sudwest", "suroeste", "sud-ouest"),
    "W": ("west", "запад", "захід", "zachod", "westen", "oeste", "ouest"),
    "NW": ("north west", "northwest", "северо-зап", "північний захід", "polnocny zachod", "nordwest", "noroeste", "nord-ouest"),
}

CAMERA_ALIASES = {
    "FIRST_PERSON": ("first person", "1st person", "первое лицо", "від першої особи", "pierwsza osoba", "ego perspektive", "primera persona", "premiere personne"),
    "THIRD_PERSON": ("third person", "3rd person", "третье лицо", "третє лице", "від третьої особи", "trzecia osoba", "dritte person", "tercera persona", "troisieme personne"),
    "ISOMETRIC": ("isometric", "isometry", "изометр", "ізометр", "izometr", "isometrisch", "isometrica", "isometrique"),
}

MIRROR_ALIASES = {
    "ORIGIN": ("origin", "исток", "початок"),
    "NOCTURNE": ("nocturne", "ноктюрн"),
    "AETHER": ("aether", "ether", "эфир", "ефір", "аэтер"),
    "EMBER": ("ember", "уголь", "угли", "пепел", "жар", "попіл"),
}

GENERIC_ASSET_HINTS = {
    "lighthouse": ("lighthouse", "маяк", "маяк", "latarnia", "leuchtturm", "faro", "phare"),
    "bridge": ("bridge", "мост", "міст", "most", "brucke", "puente", "pont"),
    "tower": ("tower", "башн", "веж", "wieza", "turm", "torre", "tour"),
    "house": ("house", "home", "дом", "будинок", "dom", "haus", "casa", "maison"),
    "wall": ("wall", "стен", "стіна", "sciana", "mauer", "muro", "mur"),
    "portal": ("portal", "портал"),
    "tree": ("tree", "дерев", "drzew", "baum", "arbol", "arbre"),
    "statue": ("statue", "стату", "памятник", "пам'ятник", "pomnik", "statua"),
}


def _normalize(text: str) -> str:
    value = unicodedata.normalize("NFKC", str(text or "")).strip().lower()
    value = value.replace("ё", "е")
    value = re.sub(r"[\u2010-\u2015]", "-", value)
    value = re.sub(r"\s+", " ", value)
    return value


def _ascii_fold(text: str) -> str:
    return "".join(ch for ch in unicodedata.normalize("NFKD", text) if not unicodedata.combining(ch))


def _contains_any(text: str, values: Iterable[str]) -> bool:
    folded = _ascii_fold(text)
    return any(_ascii_fold(v) in folded for v in values)


def _direction(text: str) -> str | None:
    for direction, aliases in DIRECTION_ALIASES.items():
        if _contains_any(text, aliases):
            return direction
    return None


def _camera(text: str) -> str | None:
    for camera, aliases in CAMERA_ALIASES.items():
        if _contains_any(text, aliases):
            return camera
    return None


def _mirror(text: str) -> str | None:
    for mirror, aliases in MIRROR_ALIASES.items():
        if _contains_any(text, aliases):
            return mirror
    return None


def _steps(text: str) -> int:
    match = re.search(r"(?<!\w)(\d{1,3})(?!\w)", text)
    if not match:
        return 1
    return max(1, min(MAX_STEPS, int(match.group(1))))


def _concept(text: str) -> str:
    cleaned = re.sub(r"[^\w\- '\u0400-\u04ff]", " ", text, flags=re.UNICODE)
    noise = (
        CREATE.values + MOVE.values + RETURN.values + MARK.values +
        tuple(alias for values in DIRECTION_ALIASES.values() for alias in values) +
        tuple(alias for values in CAMERA_ALIASES.values() for alias in values)
    )
    folded = _ascii_fold(cleaned)
    for token in sorted(noise, key=len, reverse=True):
        folded = folded.replace(_ascii_fold(token), " ")
    folded = re.sub(r"\b\d+\b", " ", folded)
    folded = re.sub(r"\s+", " ", folded).strip(" -'")
    return folded[:MAX_CONCEPT_CHARS] or "generated structure"


def _asset_kind(concept: str) -> str:
    for kind, aliases in GENERIC_ASSET_HINTS.items():
        if _contains_any(concept, aliases):
            return kind
    return "generic_structure"


def _world_state(payload: Mapping[str, Any]) -> Dict[str, Any]:
    source = payload.get("canonical_world_state")
    if not isinstance(source, Mapping):
        raise GenesisAPIError("CANONICAL_WORLD_STATE_REQUIRED")
    required = ("world_id", "world_seed", "generator_version", "player_position")
    for key in required:
        if key not in source:
            raise GenesisAPIError(f"WORLD_STATE_FIELD_REQUIRED:{key}")
    position = source.get("player_position")
    if not isinstance(position, Mapping):
        raise GenesisAPIError("PLAYER_POSITION_INVALID")
    x = float(position.get("x", 0.0))
    y = float(position.get("y", 0.0))
    if not (-1_000_000 <= x <= 1_000_000 and -1_000_000 <= y <= 1_000_000):
        raise GenesisAPIError("PLAYER_POSITION_OUT_OF_RANGE")
    return {
        "world_id": str(source["world_id"]),
        "world_seed": str(source["world_seed"]),
        "generator_version": str(source["generator_version"]),
        "player_position": {"x": x, "y": y},
        "discovered_chunk_coordinates": list(source.get("discovered_chunk_coordinates") or [])[-8192:],
        "explicit_world_mutations": list(source.get("explicit_world_mutations") or [])[-512:],
        "chronicle_tip_hash": str(source.get("chronicle_tip_hash") or "GENESIS"),
    }


def _seed(world_state: Mapping[str, Any], text: str) -> str:
    body = json.dumps({"world": world_state, "text": text}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def health() -> Dict[str, Any]:
    return {
        "schema": HEALTH_SCHEMA,
        "api_version": API_VERSION,
        "home_repository": "Hawkar-usls/Hawkar-usls",
        "janus_api_available": True,
        "genesis_intent_available": True,
        "asset_resolution_available": True,
        "external_effect_authorized": False,
        "world_truth_authority": False,
        "routes": ["ACTIVATOR", "LANGUAGE_SYNTHESIS", "SEMANTIC_TO_MECHANIC", "FILE_FABRIC"],
    }


def compile_intent(payload: Mapping[str, Any]) -> Dict[str, Any]:
    if payload.get("schema") != REQUEST_SCHEMA:
        raise GenesisAPIError("REQUEST_SCHEMA_INVALID")
    raw_text = str(payload.get("player_text") or "").strip()
    if not raw_text:
        raise GenesisAPIError("PLAYER_TEXT_REQUIRED")
    if len(raw_text) > MAX_TEXT_CHARS:
        raise GenesisAPIError("PLAYER_TEXT_TOO_LONG")
    if "\x00" in raw_text:
        raise GenesisAPIError("PLAYER_TEXT_NUL_FORBIDDEN")

    text = _normalize(raw_text)
    world = _world_state(payload)
    action_seed = _seed(world, text)
    request_id = str(payload.get("request_id") or action_seed[:24])[:96]

    direction = _direction(text)
    camera = _camera(text)
    mirror = _mirror(text)
    intent: Dict[str, Any]
    requirements: list[Dict[str, Any]] = []

    if camera:
        intent = {"kind": "SET_CAMERA", "camera": camera}
    elif mirror:
        intent = {"kind": "SET_MIRROR", "mirror": mirror}
    elif RETURN.find(text):
        intent = {"kind": "RETURN_TO_HEARTH"}
    elif MARK.find(text) and not CREATE.find(text):
        intent = {"kind": "PLACE_MARK", "label": raw_text[:64]}
    elif CREATE.find(text):
        concept = _concept(text)
        kind = _asset_kind(concept)
        intent = {
            "kind": "GENERATE_STRUCTURE",
            "concept": concept,
            "structure_kind": kind,
            "action_seed": action_seed,
            "placement": "IN_FRONT_OF_PLAYER",
        }
        requirements.append({
            "kind": "TEXTURE_OR_MATERIAL_REFERENCE",
            "query": concept,
            "preferred_provider": "poly_haven",
            "rights_required": "CC0",
            "binary_transport": "DIRECT_PROVIDER_CDN_NOT_SLIME",
        })
    elif MOVE.find(text) or direction:
        intent = {
            "kind": "MOVE",
            "direction": direction or "FORWARD",
            "steps": _steps(text),
            "explore": any(word in text for word in ("explore", "исслед", "дослід", "erkund", "explor")),
        }
    else:
        intent = {
            "kind": "UNRESOLVED",
            "reason": "NO_BOUNDED_MECHANIC_MATCH",
            "player_text": raw_text[:280],
        }

    core: Dict[str, Any] = {
        "schema": RESPONSE_SCHEMA,
        "api_version": API_VERSION,
        "request_id": request_id,
        "status": "PROPOSED" if intent["kind"] != "UNRESOLVED" else "UNRESOLVED",
        "language_policy": "RESPOND_AND_COMPILE_IN_EXPLICIT_PLAYER_LANGUAGE_WHEN_SUPPORTED",
        "normalized_text": text,
        "action_seed": action_seed,
        "world_state_hash": canonical_hash(world),
        "intent_plan": intent,
        "asset_requirements": requirements,
        "routes_consulted": ["HOME", "ACTIVATOR", "SEMANTIC_TO_MECHANIC", "FILE_FABRIC"],
        "authority": {
            "model_output_is_command": False,
            "janus_api_is_world_authority": False,
            "world_mutation_authorized": False,
            "genesis_validator_required": True,
            "external_effect_authorized": False,
        },
        "provenance": {
            "home_repository": "Hawkar-usls/Hawkar-usls",
            "request_schema": REQUEST_SCHEMA,
            "response_schema": RESPONSE_SCHEMA,
            "compiler": "janus_spi.genesis_api.compile_intent",
        },
    }
    core["receipt_hash"] = canonical_hash(core)
    return core


def verify_response(response: Mapping[str, Any]) -> bool:
    if response.get("schema") != RESPONSE_SCHEMA:
        return False
    core = dict(response)
    claimed = str(core.pop("receipt_hash", ""))
    if len(claimed) != 64 or canonical_hash(core) != claimed:
        return False
    authority = response.get("authority") or {}
    return (
        authority.get("model_output_is_command") is False
        and authority.get("janus_api_is_world_authority") is False
        and authority.get("world_mutation_authorized") is False
        and authority.get("genesis_validator_required") is True
        and authority.get("external_effect_authorized") is False
    )
