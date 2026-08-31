from __future__ import annotations

import json
import urllib.parse
import urllib.request
from typing import Any, Dict, Iterable

USER_AGENT = "JANUS-Genesis-Asset-Federation/0.5 (+https://github.com/Hawkar-usls/Hawkar-usls)"
SAFE_RIGHTS = {"CC0", "PUBLIC_DOMAIN", "CC-BY", "CC-BY-SA"}

PROVIDERS = (
    {"provider_id": "poly_haven", "channels": ["material", "mesh"], "status": "LIVE_ADAPTER", "rights_mode": "PROVIDER_WIDE_CC0"},
    {"provider_id": "wikimedia_commons", "channels": ["material", "audio", "mesh"], "status": "LIVE_METADATA_ADAPTER", "rights_mode": "PER_ITEM_LICENSE"},
    {"provider_id": "openverse", "channels": ["material", "audio"], "status": "DISCOVERY_ONLY", "rights_mode": "ORIGINAL_SOURCE_REVERIFY_REQUIRED"},
    {"provider_id": "smithsonian_open_access", "channels": ["mesh", "material"], "status": "ADAPTER_PENDING", "rights_mode": "ITEM_LEVEL_CC0_MEDIA"},
    {"provider_id": "met_open_access", "channels": ["material"], "status": "ADAPTER_PENDING", "rights_mode": "PUBLIC_DOMAIN_FILTER"},
    {"provider_id": "europeana", "channels": ["material", "audio", "mesh"], "status": "ADAPTER_PENDING", "rights_mode": "PER_OBJECT_RIGHTS"},
    {"provider_id": "library_of_congress", "channels": ["material", "audio"], "status": "DISCOVERY_ONLY", "rights_mode": "PER_ITEM_RIGHTS_ADVISORY"},
    {"provider_id": "nasa_media", "channels": ["material", "mesh", "audio"], "status": "ADAPTER_PENDING_CONDITIONAL", "rights_mode": "US_GOVERNMENT_WITH_EXCEPTIONS"},
    {"provider_id": "kenney_cc0", "channels": ["mesh", "mechanic"], "status": "CURATED_CATALOG_ADAPTER_PENDING", "rights_mode": "OFFICIAL_PACK_CC0_ONLY"},
    {"provider_id": "quaternius_cc0", "channels": ["mesh", "mechanic"], "status": "CURATED_CATALOG_ADAPTER_PENDING", "rights_mode": "OFFICIAL_PACK_CC0_ONLY"},
    {"provider_id": "freesound", "channels": ["audio"], "status": "DISABLED_CONDITIONAL_REQUIRES_CREDENTIAL_AND_API_TERMS_REVIEW", "rights_mode": "PER_ITEM_LICENSE_PLUS_API_TERMS"},
    {"provider_id": "ambientcg", "channels": ["material", "mesh"], "status": "ADAPTER_PENDING_OFFICIAL_INTERFACE_UNCONFIRMED", "rights_mode": "VERIFY_BEFORE_ENABLE"},
    {"provider_id": "genesis_mechanic_forge", "channels": ["mechanic"], "status": "LOCAL_RECIPE_FORGE", "rights_mode": "LOCAL_CODE_NOT_REMOTE_ASSET"},
)


def _json_url(url: str, timeout: float = 8.0) -> Any:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.load(response)


def _flatten_files(node: Any, path: tuple[str, ...] = ()) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if isinstance(node, dict):
        if isinstance(node.get("url"), str):
            rows.append({"path": "/".join(path), "url": node.get("url"), "size": node.get("size")})
        for key, value in node.items():
            if key in {"url", "size", "md5", "include"}:
                continue
            rows.extend(_flatten_files(value, path + (str(key),)))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            rows.extend(_flatten_files(value, path + (str(index),)))
    return rows


def _polyhaven_search(query: str, kind: str, limit: int) -> list[dict[str, Any]]:
    asset_type = "textures" if kind == "material" else "models"
    data = _json_url(f"https://api.polyhaven.com/assets?type={asset_type}")
    if not isinstance(data, dict):
        return []
    terms = [token for token in query.lower().replace("-", " ").split() if len(token) >= 2]
    scored: list[tuple[int, str, dict[str, Any]]] = []
    for asset_id, row in data.items():
        if not isinstance(row, dict):
            continue
        hay = " ".join([str(asset_id), str(row.get("name") or ""), str(row.get("description") or ""), " ".join(map(str, row.get("tags") or []))]).lower()
        score = sum(3 if term in str(row.get("name") or "").lower() else 1 for term in terms if term in hay)
        if score:
            scored.append((score, str(asset_id), row))
    scored.sort(key=lambda item: (-item[0], item[1]))
    results: list[dict[str, Any]] = []
    for _, asset_id, row in scored[: max(1, min(limit, 4))]:
        files = _flatten_files(_json_url(f"https://api.polyhaven.com/files/{urllib.parse.quote(asset_id)}"))
        wanted_ext = (".jpg", ".jpeg", ".png", ".webp") if kind == "material" else (".glb", ".gltf", ".fbx", ".obj")
        candidates = [f for f in files if str(f.get("url") or "").lower().endswith(wanted_ext)]
        candidates.sort(key=lambda f: (f.get("size") is None, int(f.get("size") or 10**18), str(f.get("path") or "")))
        pointer = candidates[0].get("url") if candidates else None
        results.append({
            "provider_id": "poly_haven", "asset_id": asset_id, "name": row.get("name") or asset_id,
            "type": kind, "rights": "CC0", "source_url": f"https://polyhaven.com/a/{asset_id}",
            "download_pointer": pointer, "binary_transport": "DIRECT_PROVIDER_CDN_NOT_SLIME",
            "attribution_required": False,
        })
    return results


def _rights_from_extmetadata(meta: Dict[str, Any]) -> tuple[str | None, str | None, str | None]:
    def value(key: str) -> str:
        item = meta.get(key) or {}
        return str(item.get("value") or "") if isinstance(item, dict) else ""
    raw = " ".join([value("LicenseShortName"), value("UsageTerms"), value("Copyrighted")]).lower()
    license_url = value("LicenseUrl") or None
    author = value("Artist") or value("Credit") or None
    if "cc0" in raw or "creative commons cc0" in raw:
        return "CC0", license_url, author
    if "public domain" in raw:
        return "PUBLIC_DOMAIN", license_url, author
    if "cc by-sa" in raw or "cc-by-sa" in raw:
        return "CC-BY-SA", license_url, author
    if "cc by" in raw or "cc-by" in raw:
        return "CC-BY", license_url, author
    return None, license_url, author


def _wikimedia_search(query: str, kind: str, limit: int) -> list[dict[str, Any]]:
    params = {
        "action": "query", "format": "json", "generator": "search", "gsrsearch": query,
        "gsrnamespace": "6", "gsrlimit": str(max(1, min(limit * 3, 30))),
        "prop": "imageinfo", "iiprop": "url|mime|extmetadata", "iiurlwidth": "640",
    }
    data = _json_url("https://commons.wikimedia.org/w/api.php?" + urllib.parse.urlencode(params))
    pages = ((data or {}).get("query") or {}).get("pages") or {}
    rows: list[dict[str, Any]] = []
    for page in pages.values() if isinstance(pages, dict) else []:
        info = ((page or {}).get("imageinfo") or [{}])[0]
        mime = str(info.get("mime") or "")
        if kind == "audio" and not mime.startswith("audio/"):
            continue
        if kind == "material" and not mime.startswith("image/"):
            continue
        if kind == "mesh" and not ("model" in mime or str(page.get("title") or "").lower().endswith((".stl", ".glb", ".gltf"))):
            continue
        rights, license_url, author = _rights_from_extmetadata(info.get("extmetadata") or {})
        if rights not in SAFE_RIGHTS:
            continue
        title = str(page.get("title") or "File:unknown")
        rows.append({
            "provider_id": "wikimedia_commons", "asset_id": str(page.get("pageid") or title), "name": title.removeprefix("File:"),
            "type": kind, "rights": rights, "source_url": str(info.get("descriptionurl") or "https://commons.wikimedia.org/"),
            "download_pointer": info.get("url"), "binary_transport": "DIRECT_PROVIDER_CDN_NOT_SLIME",
            "license_url": license_url, "author": author, "attribution_required": rights in {"CC-BY", "CC-BY-SA"},
        })
        if len(rows) >= limit:
            break
    return rows


def provider_matrix(kind: str) -> list[dict[str, Any]]:
    return [dict(row) for row in PROVIDERS if kind in row["channels"]]


def federated_search(kind: str, query: str, limit: int = 6) -> Dict[str, Any]:
    channel = str(kind or "").strip().lower()
    text = str(query or "").strip()
    if channel not in {"material", "mesh", "audio", "mechanic"}:
        raise ValueError("ASSET_FEDERATION_KIND_INVALID")
    if not text:
        raise ValueError("ASSET_QUERY_REQUIRED")
    limit = max(1, min(12, int(limit)))
    results: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    if channel in {"material", "mesh"}:
        try:
            results.extend(_polyhaven_search(text, channel, limit))
        except Exception as exc:
            errors.append({"provider_id": "poly_haven", "error": type(exc).__name__})
    if channel in {"material", "audio", "mesh"} and len(results) < limit:
        try:
            results.extend(_wikimedia_search(text, channel, limit - len(results)))
        except Exception as exc:
            errors.append({"provider_id": "wikimedia_commons", "error": type(exc).__name__})
    # Mechanics are deliberately local recipes. Remote mechanic references may inform provenance later,
    # but never become executable code and are not fabricated here.
    results = [r for r in results if r.get("rights") in SAFE_RIGHTS and r.get("binary_transport") == "DIRECT_PROVIDER_CDN_NOT_SLIME"][:limit]
    return {
        "schema": "janus.genesis.asset_federation.search.v1",
        "version": "0.5.0",
        "kind": channel,
        "query": text,
        "results": results,
        "providers": provider_matrix(channel),
        "provider_errors": errors,
        "rights_gate": "PER_REFERENCE_FAIL_CLOSED",
        "binary_transport": "DIRECT_PROVIDER_OR_CDN_NOT_SLIME",
        "foreign_code_execution": False,
        "procedural_fallback_required": True,
    }


__all__ = ["PROVIDERS", "SAFE_RIGHTS", "federated_search", "provider_matrix"]
