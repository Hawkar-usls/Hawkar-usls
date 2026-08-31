from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from janus_spi.genesis_api import GenesisAPIError, compile_intent, health  # noqa: E402

USER_AGENT = "JANUS-Genesis-Asset-Trunk/1.0 (+https://github.com/Hawkar-usls/Hawkar-usls)"
MAX_BODY = 1_000_000


def _json_bytes(payload: Any) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")


def _read_json(handler: BaseHTTPRequestHandler) -> dict[str, Any]:
    length = int(handler.headers.get("Content-Length") or "0")
    if length <= 0 or length > MAX_BODY:
        raise GenesisAPIError("BODY_LENGTH_INVALID")
    raw = handler.rfile.read(length)
    try:
        value = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise GenesisAPIError("BODY_JSON_INVALID") from exc
    if not isinstance(value, dict):
        raise GenesisAPIError("BODY_OBJECT_REQUIRED")
    return value


def _polyhaven_asset_search(query: str, *, asset_type: str = "textures", limit: int = 6) -> dict[str, Any]:
    text = str(query or "").strip().lower()
    if not text:
        raise GenesisAPIError("ASSET_QUERY_REQUIRED")
    if asset_type not in {"textures", "models", "hdris"}:
        raise GenesisAPIError("ASSET_TYPE_INVALID")
    url = f"https://api.polyhaven.com/assets?type={urllib.parse.quote(asset_type)}"
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=8) as response:
        data = json.load(response)
    if not isinstance(data, dict):
        raise GenesisAPIError("POLYHAVEN_RESPONSE_INVALID")
    terms = [token for token in text.replace("-", " ").split() if len(token) >= 2]
    scored: list[tuple[int, str, dict[str, Any]]] = []
    for asset_id, row in data.items():
        if not isinstance(row, dict):
            continue
        haystack = " ".join([
            str(asset_id), str(row.get("name") or ""), str(row.get("description") or ""),
            str(row.get("category") or ""), " ".join(map(str, row.get("tags") or [])),
        ]).lower()
        score = sum(3 if term in str(row.get("name") or "").lower() else 1 for term in terms if term in haystack)
        if not terms:
            score = 1
        if score > 0:
            scored.append((score, str(asset_id), row))
    scored.sort(key=lambda item: (-item[0], item[1]))
    results = []
    for score, asset_id, row in scored[: max(1, min(12, int(limit)))]:
        results.append({
            "provider_id": "poly_haven",
            "asset_id": asset_id,
            "name": row.get("name"),
            "type": asset_type,
            "category": row.get("category"),
            "tags": row.get("tags") or [],
            "thumbnail_url": row.get("thumbnail_url"),
            "score": score,
            "rights": "CC0",
            "source_url": f"https://polyhaven.com/a/{asset_id}",
        })
    return {
        "schema": "janus.genesis.asset_search.v1",
        "provider_id": "poly_haven",
        "query": text,
        "asset_type": asset_type,
        "results": results,
        "rights_gate": "PROVIDER_WIDE_CC0_ASSETS",
        "binary_transport": "DIRECT_PROVIDER_CDN_NOT_SLIME",
        "powered_by": "Poly Haven",
    }


def _flatten_files(node: Any, path: tuple[str, ...] = ()) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if isinstance(node, dict):
        if isinstance(node.get("url"), str):
            rows.append({
                "path": "/".join(path),
                "url": node.get("url"),
                "size": node.get("size"),
                "md5": node.get("md5"),
            })
        for key, value in node.items():
            if key in {"url", "size", "md5", "include"}:
                continue
            rows.extend(_flatten_files(value, path + (str(key),)))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            rows.extend(_flatten_files(value, path + (str(index),)))
    return rows


def _polyhaven_files(asset_id: str) -> dict[str, Any]:
    safe_id = str(asset_id or "").strip()
    if not safe_id or not all(ch.isalnum() or ch in "_-" for ch in safe_id):
        raise GenesisAPIError("ASSET_ID_INVALID")
    url = f"https://api.polyhaven.com/files/{urllib.parse.quote(safe_id)}"
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=8) as response:
        data = json.load(response)
    files = _flatten_files(data)
    files.sort(key=lambda row: (row.get("size") is None, int(row.get("size") or 10**18), row.get("path") or ""))
    return {
        "schema": "janus.genesis.asset_files.v1",
        "provider_id": "poly_haven",
        "asset_id": safe_id,
        "rights": "CC0",
        "files": files[:80],
        "binary_transport": "DIRECT_PROVIDER_CDN_NOT_SLIME",
        "powered_by": "Poly Haven",
    }


class Handler(BaseHTTPRequestHandler):
    server_version = "JANUSGenesisAPI/1.0"

    def _send(self, status: int, payload: Any) -> None:
        body = _json_bytes(payload)
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", self.server.allowed_origin)
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Janus-Request-Id")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self) -> None:  # noqa: N802
        self._send(204, {})

    def do_GET(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        try:
            if parsed.path == "/v1/health":
                payload = health()
                payload["cors_origin"] = self.server.allowed_origin
                self._send(200, payload)
                return
            if parsed.path == "/v1/genesis/assets/search":
                qs = urllib.parse.parse_qs(parsed.query)
                query = (qs.get("q") or [""])[0]
                asset_type = (qs.get("type") or ["textures"])[0]
                limit = int((qs.get("limit") or ["6"])[0])
                self._send(200, _polyhaven_asset_search(query, asset_type=asset_type, limit=limit))
                return
            if parsed.path.startswith("/v1/genesis/assets/files/"):
                asset_id = parsed.path.rsplit("/", 1)[-1]
                self._send(200, _polyhaven_files(asset_id))
                return
            self._send(404, {"error": "NOT_FOUND"})
        except Exception as exc:
            self._send(400, {"error": type(exc).__name__, "detail": str(exc)[:300]})

    def do_POST(self) -> None:  # noqa: N802
        try:
            if self.path != "/v1/genesis/intent":
                self._send(404, {"error": "NOT_FOUND"})
                return
            payload = _read_json(self)
            self._send(200, compile_intent(payload))
        except GenesisAPIError as exc:
            self._send(400, {"error": "GENESIS_API_REJECT", "detail": str(exc)})
        except Exception as exc:
            self._send(500, {"error": type(exc).__name__, "detail": str(exc)[:300]})

    def log_message(self, fmt: str, *args: Any) -> None:
        if not self.server.quiet:
            super().log_message(fmt, *args)


def main() -> int:
    parser = argparse.ArgumentParser(description="JANUS HOME Genesis API adapter")
    parser.add_argument("--host", default=os.getenv("JANUS_API_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.getenv("JANUS_API_PORT", "8765")))
    parser.add_argument("--allow-origin", default=os.getenv("JANUS_API_ALLOW_ORIGIN", "https://hawkar-usls.github.io"))
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    server.allowed_origin = args.allow_origin
    server.quiet = args.quiet
    print(f"JANUS Genesis API listening on http://{args.host}:{args.port}")
    print(f"CORS origin: {args.allow_origin}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
