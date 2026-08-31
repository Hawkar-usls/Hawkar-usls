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
MAX_TEXT_CHARS = 4000
MAX_CONCEPT_CHARS = 120
MAX_STEPS = 64


class GenesisAPIError(RuntimeError):
    pass


def _ascii_fold(text: str) -> str:
    return "".join(ch for ch in unicodedata.normalize("NFKD", text) if not unicodedata.combining(ch))


def _phrase_pattern(value: str) -> str:
    return rf"(?<!\w){re.escape(_ascii_fold(value))}(?!\w)"


def _contains_any(text: str, values: Iterable[str]) -> bool:
    folded = _ascii_fold(text)
    return any(re.search(_phrase_pattern(v), folded, flags=re.IGNORECASE) is not None for v in values)


def _contains_fragment(text: str, values: Iterable[str]) -> bool:
    folded = _ascii_fold(text)
    return any(_ascii_fold(v) in folded for v in values)


@dataclass(frozen=True)
class LexemeSet:
    values: tuple[str, ...]
    def find(self, text: str) -> bool:
        return _contains_any(text, self.values)


BUILD = LexemeSet(("build","construct","generate","erect","построй","построить","возведи","создай","создать","сделай","поставь","размести","сгенерируй","побудуй","збудуй","створи","зроби","розмісти","zbuduj","stworz","postaw","baue","bauen","erschaffe","construye","crear","crea","construis","cree","creer"))
SPAWN = LexemeSet(("spawn","summon","add","create","make","place","породи","заспавнь","спавн","призови","добавь","створи","додай","dodaj","spawne","beschwore","fuge","invoca","anade","invoque","ajoute"))
MOVE = LexemeSet(("go","walk","move","travel","step","run","explore","wander","forward","backward","иди","идти","двигай","двигаться","пройди","беги","исследуй","броди","вперед","назад","йди","рухайся","біжи","досліджуй","мандруй","idz","rusz","biegnij","eksploruj","geh","gehe","lauf","erkunde","ve","camina","muevete","explora","va","marche","deplace"))
RETURN = LexemeSet(("return","home","hearth","back to fire","вернись","вернуться","домой","к огню","к костру","повернись","додому","до вогню","wroc","domu","ognia","zuruck","heim","feuer","regresa","casa","fuego","retourne","maison","feu"))
MARK = LexemeSet(("mark","sign","leave a mark","beacon marker","метка","метку","знак","оставь знак","оставь метку","мітка","познач","залиш знак","znak","znacznik","markierung","zeichen","marca","senal","marque","signe"))
INSPECT = LexemeSet(("inspect","scan","describe","what is here","look around","осмотри","что здесь","опиши место","просканируй","оглянь","що тут","опиши місце","sprawdz","opisz","untersuche","beschreibe","inspecciona","inspecte","decris"))
NIGHT = LexemeSet(("night","ночь","ніч","noc","nacht","noche","nuit"))
DAY = LexemeSet(("day","день","dzien","tag","dia","jour"))
FOG = LexemeSet(("fog","mist","туман","імла","mgla","nebel","niebla","brouillard"))
CLEAR_FOG = LexemeSet(("clear fog","remove fog","без тумана","убери туман","без туману","прибери туман","usun mgle","nebel aus","quita niebla","retire brouillard"))
RAISE = LexemeSet(("raise hill","make hill","raise terrain","подними холм","создай холм","подними землю","підніми пагорб","створи пагорб","wzgorze","hugel","colina","colline"))
LOWER = LexemeSet(("lower ground","dig pit","lower terrain","опусти землю","выкопай яму","зроби яму","grube","senke","hoyo","fosse"))

DIRECTION_ALIASES = {
    "N": ("north","север","північ","polnoc","norden","norte","nord"), "NE": ("north east","northeast","северо-вост","північний схід","nordost","noreste","nord-est"),
    "E": ("east","восток","схід","wschod","osten","este","est"), "SE": ("south east","southeast","юго-вост","південний схід","sudost","sureste","sud-est"),
    "S": ("south","юг","південь","poludnie","suden","sur","sud"), "SW": ("south west","southwest","юго-зап","південний захід","sudwest","suroeste","sud-ouest"),
    "W": ("west","запад","захід","zachod","westen","oeste","ouest"), "NW": ("north west","northwest","северо-зап","північний захід","nordwest","noroeste","nord-ouest"),
    "BACKWARD": ("backward","назад","zuruck","atras","arriere"),
}
CAMERA_ALIASES = {
    "FIRST_PERSON": ("first person","1st person","первое лицо","від першої особи","pierwsza osoba","ego perspektive","primera persona","premiere personne"),
    "THIRD_PERSON": ("third person","3rd person","третье лицо","від третьої особи","trzecia osoba","dritte person","tercera persona","troisieme personne"),
    "ISOMETRIC": ("isometric","isometry","изометр","ізометр","izometr","isometrisch","isometrica","isometrique"),
}
MIRROR_ALIASES = {
    "ORIGIN": ("style origin","origin style","стиль origin","стиль исток","стиль початок"),
    "NOCTURNE": ("style nocturne","nocturne style","стиль nocturne","стиль ноктюрн"),
    "AETHER": ("style aether","aether style","стиль aether","стиль эфир","стиль ефір"),
    "EMBER": ("style ember","ember style","стиль ember","стиль жар","стиль попіл"),
}
STRUCTURE_HINTS = {
    "lighthouse": ("lighthouse","маяк","latarnia","leuchtturm","faro","phare"), "castle": ("castle","крепост","замок","фортец","фортеця","zamek","burg","castillo","chateau"),
    "bridge": ("bridge","мост","міст","most","brucke","puente","pont"), "tower": ("tower","башн","веж","wieza","turm","torre","tour"),
    "house": ("house","building","дом","будинок","haus","casa","maison"), "wall": ("wall","стен","стіна","sciana","mauer","muro","mur"),
    "portal": ("portal","портал"), "tree": ("tree","дерев","drzew","baum","arbol","arbre"), "statue": ("statue","стату","памятник","пам'ятник","pomnik"), "road": ("road","дорог","шлях","droga","strasse","camino","route"),
}
ENTITY_HINTS = ("npc","person","human","guard","guardian","creature","animal","dragon","wolf","horse","робот","человек","персонаж","нпс","страж","существо","дракон","волк","кінь","людина","істота","smok","wilk","mensch","drache","persona","personne")


def _normalize(text: str) -> str:
    value = unicodedata.normalize("NFKC", str(text or "")).strip().lower().replace("ё", "е")
    value = re.sub(r"[\u2010-\u2015]", "-", value)
    return re.sub(r"\s+", " ", value)


def _match_map(text: str, mapping: Mapping[str, Iterable[str]]) -> str | None:
    for key, aliases in mapping.items():
        if _contains_any(text, aliases):
            return key
    return None


def _steps(text: str, fallback: int = 1) -> int:
    match = re.search(r"(?<!\w)(\d{1,3})(?!\w)", text)
    return max(1, min(MAX_STEPS, int(match.group(1)) if match else fallback))


def _number(text: str, fallback: float, minimum: float, maximum: float) -> float:
    match = re.search(r"(?<!\w)(-?\d+(?:\.\d+)?)(?!\w)", text)
    value = float(match.group(1)) if match else fallback
    return max(minimum, min(maximum, value))


def _concept(text: str) -> str:
    cleaned = re.sub(r"[^\w\- '\u0400-\u04ff]", " ", text, flags=re.UNICODE)
    noise = BUILD.values + SPAWN.values + MOVE.values + RETURN.values + MARK.values + INSPECT.values
    folded = _ascii_fold(cleaned)
    for token in sorted(noise, key=len, reverse=True):
        folded = re.sub(_phrase_pattern(token), " ", folded, flags=re.IGNORECASE)
    folded = re.sub(r"\b\d+(?:\.\d+)?\b", " ", folded)
    return re.sub(r"\s+", " ", folded).strip(" -'")[:MAX_CONCEPT_CHARS] or "generated object"


def _structure_kind(text: str) -> str | None:
    for kind, aliases in STRUCTURE_HINTS.items():
        if _contains_fragment(text, aliases):
            return kind
    return None


def _world_state(payload: Mapping[str, Any]) -> Dict[str, Any]:
    source = payload.get("canonical_world_state")
    if not isinstance(source, Mapping):
        raise GenesisAPIError("CANONICAL_WORLD_STATE_REQUIRED")
    for key in ("world_id","world_seed","generator_version","player_position"):
        if key not in source:
            raise GenesisAPIError(f"WORLD_STATE_FIELD_REQUIRED:{key}")
    position = source.get("player_position")
    if not isinstance(position, Mapping):
        raise GenesisAPIError("PLAYER_POSITION_INVALID")
    x, y = float(position.get("x",0.0)), float(position.get("y",0.0))
    if not (-1_000_000 <= x <= 1_000_000 and -1_000_000 <= y <= 1_000_000):
        raise GenesisAPIError("PLAYER_POSITION_OUT_OF_RANGE")
    return {"world_id":str(source["world_id"]),"world_seed":str(source["world_seed"]),"generator_version":str(source["generator_version"]),"player_position":{"x":x,"y":y},"world_settings":dict(source.get("world_settings") or {}),"discovered_chunk_coordinates":list(source.get("discovered_chunk_coordinates") or [])[-8192:],"explicit_world_mutations":list(source.get("explicit_world_mutations") or [])[-768:],"chronicle_tip_hash":str(source.get("chronicle_tip_hash") or "GENESIS")}


def _seed(world_state: Mapping[str, Any], text: str) -> str:
    body=json.dumps({"world":world_state,"text":text},ensure_ascii=False,sort_keys=True,separators=(",",":"))
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _material_requirement(query: str) -> Dict[str, Any]:
    return {"kind":"TEXTURE_OR_MATERIAL_REFERENCE","query":query,"preferred_provider":"poly_haven","rights_required":"CC0","binary_transport":"DIRECT_PROVIDER_CDN_NOT_SLIME"}


def health() -> Dict[str, Any]:
    return {"schema":HEALTH_SCHEMA,"api_version":API_VERSION,"home_repository":"Hawkar-usls/Hawkar-usls","janus_api_available":True,"genesis_intent_available":True,"asset_resolution_available":True,"external_effect_authorized":False,"world_truth_authority":False,"intent_families":["MOVE","RETURN_TO_HEARTH","PLACE_MARK","GENERATE_STRUCTURE","SPAWN_ENTITY","SET_ATMOSPHERE","WORLD_TRANSFORM","SET_CAMERA","SET_MIRROR","SET_CAMERA_DISTANCE","INSPECT","UNRESOLVED"],"routes":["ACTIVATOR","LANGUAGE_SYNTHESIS","SEMANTIC_TO_MECHANIC","FILE_FABRIC"]}


def compile_intent(payload: Mapping[str, Any]) -> Dict[str, Any]:
    if payload.get("schema") != REQUEST_SCHEMA: raise GenesisAPIError("REQUEST_SCHEMA_INVALID")
    raw_text=str(payload.get("player_text") or "").strip()
    if not raw_text: raise GenesisAPIError("PLAYER_TEXT_REQUIRED")
    if len(raw_text)>MAX_TEXT_CHARS: raise GenesisAPIError("PLAYER_TEXT_TOO_LONG")
    if "\x00" in raw_text: raise GenesisAPIError("PLAYER_TEXT_NUL_FORBIDDEN")
    text=_normalize(raw_text); world=_world_state(payload); action_seed=_seed(world,text); request_id=str(payload.get("request_id") or action_seed[:24])[:96]
    camera=_match_map(text,CAMERA_ALIASES); mirror=_match_map(text,MIRROR_ALIASES); direction=_match_map(text,DIRECTION_ALIASES); sk=_structure_kind(text)
    intent: Dict[str,Any]; requirements: list[Dict[str,Any]]=[]
    if camera: intent={"kind":"SET_CAMERA","camera":camera}
    elif mirror: intent={"kind":"SET_MIRROR","mirror":mirror}
    elif re.search(r"camera|камера|камер|kamera|camara",text) and re.search(r"distance|дистанц|расстоя|відстан|odleg|entfern|distancia",text): intent={"kind":"SET_CAMERA_DISTANCE","distance":_number(text,8,2.5,30)}
    elif RETURN.find(text): intent={"kind":"RETURN_TO_HEARTH"}
    elif MARK.find(text) and not BUILD.find(text): intent={"kind":"PLACE_MARK","label":raw_text[:64]}
    elif INSPECT.find(text): intent={"kind":"INSPECT","query":raw_text[:280]}
    elif CLEAR_FOG.find(text): intent={"kind":"SET_ATMOSPHERE","fog":0.0}
    elif NIGHT.find(text) or DAY.find(text) or FOG.find(text): intent={"kind":"SET_ATMOSPHERE","time":"NIGHT" if NIGHT.find(text) else "DAY" if DAY.find(text) else None,"fog":0.48 if FOG.find(text) else None}
    elif RAISE.find(text): intent={"kind":"WORLD_TRANSFORM","transform_kind":"RAISE_HILL","radius":_number(text,5,1,16),"amount":2.6}
    elif LOWER.find(text): intent={"kind":"WORLD_TRANSFORM","transform_kind":"LOWER_GROUND","radius":_number(text,4,1,16),"amount":2.0}
    elif (BUILD.find(text) or SPAWN.find(text)) and sk:
        concept=_concept(text); intent={"kind":"GENERATE_STRUCTURE","concept":concept,"structure_kind":sk,"action_seed":action_seed,"placement":"IN_FRONT_OF_PLAYER"}; requirements.append(_material_requirement(concept))
    elif BUILD.find(text):
        concept=_concept(text); intent={"kind":"GENERATE_STRUCTURE","concept":concept,"structure_kind":"generic_structure","action_seed":action_seed,"placement":"IN_FRONT_OF_PLAYER"}; requirements.append(_material_requirement(concept))
    elif SPAWN.find(text):
        concept=_concept(text); intent={"kind":"SPAWN_ENTITY","concept":concept,"entity_kind":concept if _contains_any(text,ENTITY_HINTS) else "generic_entity","action_seed":action_seed,"placement":"IN_FRONT_OF_PLAYER"}; requirements.append(_material_requirement(concept))
    elif MOVE.find(text) or direction: intent={"kind":"MOVE","direction":direction or "FORWARD","steps":_steps(text),"explore":any(word in text for word in ("explore","исслед","дослід","erkund","explor"))}
    else: intent={"kind":"UNRESOLVED","reason":"JANUS_SEMANTIC_TISSUE_REQUIRED","player_text":raw_text[:280]}
    core: Dict[str,Any]={"schema":RESPONSE_SCHEMA,"api_version":API_VERSION,"request_id":request_id,"status":"PROPOSED" if intent["kind"]!="UNRESOLVED" else "UNRESOLVED","language_policy":"RESPOND_AND_COMPILE_IN_EXPLICIT_PLAYER_LANGUAGE_WHEN_SUPPORTED","normalized_text":text,"action_seed":action_seed,"world_state_hash":canonical_hash(world),"intent_plan":intent,"asset_requirements":requirements,"routes_consulted":["HOME","ACTIVATOR","LANGUAGE_SYNTHESIS","SEMANTIC_TO_MECHANIC","FILE_FABRIC"],"authority":{"model_output_is_command":False,"janus_api_is_world_authority":False,"world_mutation_authorized":False,"genesis_validator_required":True,"external_effect_authorized":False},"provenance":{"home_repository":"Hawkar-usls/Hawkar-usls","request_schema":REQUEST_SCHEMA,"response_schema":RESPONSE_SCHEMA,"compiler":"janus_spi.genesis_api.compile_intent"}}
    core["receipt_hash"]=canonical_hash(core); return core


def verify_response(response: Mapping[str, Any]) -> bool:
    if response.get("schema") != RESPONSE_SCHEMA: return False
    core=dict(response); claimed=str(core.pop("receipt_hash",""))
    if len(claimed)!=64 or canonical_hash(core)!=claimed: return False
    authority=response.get("authority") or {}
    return authority.get("model_output_is_command") is False and authority.get("janus_api_is_world_authority") is False and authority.get("world_mutation_authorized") is False and authority.get("genesis_validator_required") is True and authority.get("external_effect_authorized") is False
