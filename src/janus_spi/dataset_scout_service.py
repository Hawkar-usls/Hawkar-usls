from __future__ import annotations

import hashlib
import json
import re
import urllib.parse
import urllib.request
from typing import Any, Callable, Mapping

REQUEST_SCHEMA = "janus.market_service.dataset_scout_request.v1"
RESULT_SCHEMA = "janus.market_service.dataset_scout_result.v1"
CATALOGS = ("ZENODO", "HUGGINGFACE")


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(value: Any) -> str:
    text = value if isinstance(value, str) else canonical(value)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def verify_request(request: Mapping[str, Any]) -> bool:
    try:
        value = dict(request); claimed = str(value.pop("request_hash", ""))
        if len(claimed) != 64 or digest(value) != claimed:
            return False
        if value.get("schema") != REQUEST_SCHEMA or value.get("sku") != "JANUS.DATASET_SCOUT":
            return False
        if not re.fullmatch(r"ds-shadow-[0-9a-f]{48}", str(value.get("request_id") or "")):
            return False
        query = str(value.get("query") or "").strip()
        if not query or len(query) > 500 or value.get("read_only") is not True:
            return False
        for key in ("dataset_payload_download_authorized", "redistribution_authority_granted", "command_authority_granted", "external_effect_authorized"):
            if value.get(key) is not False:
                return False
        bounds = value.get("bounds") or {}
        return all([
            isinstance(bounds.get("max_results"), int) and 1 <= bounds["max_results"] <= 20,
            isinstance(bounds.get("max_catalogs"), int) and 1 <= bounds["max_catalogs"] <= 2,
            isinstance(bounds.get("per_catalog_timeout_seconds"), int) and 2 <= bounds["per_catalog_timeout_seconds"] <= 15,
            isinstance(value.get("license_preferences"), list),
            isinstance(value.get("format_preferences"), list),
        ])
    except Exception:
        return False


def _json_get(url: str, timeout: int) -> Any:
    request = urllib.request.Request(url, headers={"User-Agent": "JANUS-Dataset-Scout/1.0 (+https://github.com/Hawkar-usls/Hawkar-usls)"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        if getattr(response, "status", 200) != 200:
            raise RuntimeError(f"HTTP_{getattr(response, 'status', 'UNKNOWN')}")
        return json.loads(response.read().decode("utf-8"))


def _clean_formats(values: list[str]) -> list[str]:
    out: list[str] = []
    for value in values:
        text = str(value or "").strip().lower().lstrip(".")
        if text and text not in out:
            out.append(text[:40])
    return out[:20]


def _zenodo(query: str, limit: int, timeout: int, get_json: Callable[[str, int], Any]) -> tuple[list[dict[str, Any]], str]:
    url = "https://zenodo.org/api/records?" + urllib.parse.urlencode({"q": query, "size": limit, "sort": "bestmatch"})
    payload = get_json(url, timeout)
    hits = ((payload or {}).get("hits") or {}).get("hits") or []
    rows: list[dict[str, Any]] = []
    for item in hits[:limit]:
        metadata = item.get("metadata") or {}; links = item.get("links") or {}
        dataset_id = str(item.get("id") or "").strip()
        title = str(metadata.get("title") or "").strip()
        source_url = str(links.get("html") or links.get("self_html") or (f"https://zenodo.org/records/{dataset_id}" if dataset_id else "")).strip()
        if not dataset_id or not title or not source_url:
            continue
        license_value = metadata.get("license")
        if isinstance(license_value, Mapping):
            license_value = license_value.get("id") or license_value.get("title")
        formats: list[str] = []
        for file in item.get("files") or []:
            key = str((file or {}).get("key") or "")
            if "." in key:
                formats.append(key.rsplit(".", 1)[-1])
        rows.append({
            "catalog": "ZENODO",
            "dataset_id": dataset_id,
            "title": title[:500],
            "source_url": source_url,
            "license_observation": str(license_value or "UNSPECIFIED")[:200],
            "formats": _clean_formats(formats),
            "publication_date": str(metadata.get("publication_date") or "")[:40],
            "metadata_only": True,
        })
    return rows, url


def _huggingface(query: str, limit: int, timeout: int, get_json: Callable[[str, int], Any]) -> tuple[list[dict[str, Any]], str]:
    url = "https://huggingface.co/api/datasets?" + urllib.parse.urlencode({"search": query, "limit": limit, "full": "false"})
    payload = get_json(url, timeout)
    rows: list[dict[str, Any]] = []
    for item in (payload or [])[:limit]:
        dataset_id = str(item.get("id") or "").strip()
        if not dataset_id:
            continue
        tags = [str(x) for x in (item.get("tags") or [])]
        licenses = [x.split(":", 1)[1] for x in tags if x.startswith("license:") and ":" in x]
        formats = [x.split(":", 1)[1] for x in tags if x.startswith("format:") and ":" in x]
        rows.append({
            "catalog": "HUGGINGFACE",
            "dataset_id": dataset_id,
            "title": dataset_id[:500],
            "source_url": f"https://huggingface.co/datasets/{dataset_id}",
            "license_observation": (licenses[0] if licenses else "UNSPECIFIED")[:200],
            "formats": _clean_formats(formats),
            "publication_date": "",
            "metadata_only": True,
        })
    return rows, url


def scout_public_datasets(request: Mapping[str, Any], *, get_json: Callable[[str, int], Any] = _json_get) -> dict[str, Any]:
    if not verify_request(request):
        raise ValueError("DATASET_SCOUT_REQUEST_INVALID")
    query = str(request["query"]).strip()
    domain = str(request.get("domain") or "").strip()
    effective_query = f"{query} {domain}".strip()
    bounds = request["bounds"]
    max_results = int(bounds["max_results"])
    timeout = int(bounds["per_catalog_timeout_seconds"])
    selected = CATALOGS[: int(bounds["max_catalogs"])]

    candidates: list[dict[str, Any]] = []
    attempts: list[dict[str, Any]] = []
    succeeded: list[str] = []
    failures: list[dict[str, str]] = []
    adapters = {"ZENODO": _zenodo, "HUGGINGFACE": _huggingface}
    for catalog in selected:
        try:
            rows, endpoint = adapters[catalog](effective_query, max_results, timeout, get_json)
            candidates.extend(rows)
            succeeded.append(catalog)
            attempts.append({"catalog": catalog, "metadata_endpoint": endpoint, "status": "METADATA_READ_PASS", "candidate_count": len(rows)})
        except Exception as exc:
            failures.append({"catalog": catalog, "status": "CATALOG_READ_FAILED", "error_class": type(exc).__name__})
            attempts.append({"catalog": catalog, "metadata_endpoint": None, "status": "CATALOG_READ_FAILED", "candidate_count": 0})

    unique: dict[str, dict[str, Any]] = {}
    duplicate_count = 0
    for row in candidates:
        key = str(row["source_url"]).rstrip("/").lower()
        if key in unique:
            duplicate_count += 1
            continue
        unique[key] = row
    manifest = sorted(unique.values(), key=lambda row: (str(row["catalog"]), str(row["dataset_id"])))[:max_results]
    if not succeeded:
        raise RuntimeError("DATASET_SCOUT_ALL_CATALOGS_UNAVAILABLE_UNKNOWN_RESOURCE_LIMIT")
    if not manifest:
        raise RuntimeError("DATASET_SCOUT_NO_CANDIDATES_OBSERVED")

    license_observations = [{
        "source_url": row["source_url"],
        "observed": row["license_observation"],
        "authoritative_license_determination": False,
    } for row in manifest]
    result: dict[str, Any] = {
        "schema": RESULT_SCHEMA,
        "status": "BOUNDED_DATASET_SCOUT_COMPLETE",
        "request_id": request["request_id"],
        "request_hash": request["request_hash"],
        "query": query,
        "domain": domain,
        "date_range": request.get("date_range"),
        "license_preferences": list(request.get("license_preferences") or []),
        "format_preferences": list(request.get("format_preferences") or []),
        "dataset_manifest": manifest,
        "source_urls": [row["source_url"] for row in manifest],
        "license_observations": license_observations,
        "deduplication_notes": {"key": "normalized_source_url", "duplicates_removed": duplicate_count},
        "provenance": {
            "catalogs_attempted": list(selected),
            "catalogs_succeeded": succeeded,
            "catalog_failures": failures,
            "catalog_attempt_receipts": attempts,
            "metadata_only": True,
            "silence_is_negative_evidence": False,
        },
        "authority": {
            "read_only": True,
            "dataset_payload_downloaded": False,
            "redistribution_authority_granted": False,
            "license_authority_granted": False,
            "command_authority_granted": False,
            "claim_authority_granted": False,
            "scientific_evidence_authority_granted": False,
            "world_truth_authority_granted": False,
            "external_effect_authorized": False,
        },
        "laws": [
            "DATASET METADATA != DATASET PAYLOAD",
            "DATASET DISCOVERY != REDISTRIBUTION AUTHORITY",
            "LICENSE OBSERVATION != LICENSE AUTHORITY",
            "CATALOG SILENCE != NEGATIVE EVIDENCE",
        ],
    }
    result["result_hash"] = digest(result)
    return result


def verify_result(result: Mapping[str, Any], *, request: Mapping[str, Any]) -> bool:
    try:
        value = dict(result); claimed = str(value.pop("result_hash", ""))
        if len(claimed) != 64 or digest(value) != claimed:
            return False
        if value.get("schema") != RESULT_SCHEMA or value.get("status") != "BOUNDED_DATASET_SCOUT_COMPLETE":
            return False
        if value.get("request_id") != request.get("request_id") or value.get("request_hash") != request.get("request_hash"):
            return False
        manifest = value.get("dataset_manifest")
        if not isinstance(manifest, list) or not manifest:
            return False
        if len(manifest) > int((request.get("bounds") or {}).get("max_results", 0)):
            return False
        if any((row or {}).get("metadata_only") is not True for row in manifest):
            return False
        authority = value.get("authority") or {}
        return all([
            authority.get("read_only") is True,
            authority.get("dataset_payload_downloaded") is False,
            authority.get("redistribution_authority_granted") is False,
            authority.get("license_authority_granted") is False,
            authority.get("command_authority_granted") is False,
            authority.get("claim_authority_granted") is False,
            authority.get("scientific_evidence_authority_granted") is False,
            authority.get("world_truth_authority_granted") is False,
            authority.get("external_effect_authorized") is False,
            (value.get("provenance") or {}).get("metadata_only") is True,
        ])
    except Exception:
        return False


__all__ = ["CATALOGS", "digest", "scout_public_datasets", "verify_request", "verify_result"]
