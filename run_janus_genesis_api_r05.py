from __future__ import annotations

import argparse
import os
import sys
import urllib.parse
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from janus_spi.genesis_api import GenesisAPIError  # noqa: E402
from janus_spi.genesis_api_r05 import compile_intent, health  # noqa: E402
from janus_spi.genesis_asset_federation_r05 import federated_search  # noqa: E402
from run_janus_genesis_api import Handler as LegacyHandler, _read_json  # noqa: E402


class Handler(LegacyHandler):
    server_version = "JANUSGenesisAPI/0.5"

    def do_GET(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/v1/health":
            self._send(200, health())
            return
        if parsed.path == "/v1/genesis/assets/federated/search":
            try:
                qs = urllib.parse.parse_qs(parsed.query)
                kind = (qs.get("kind") or [""])[0]
                query = (qs.get("q") or [""])[0]
                limit = int((qs.get("limit") or ["6"])[0])
                self._send(200, federated_search(kind, query, limit))
            except ValueError as exc:
                self._send(400, {"error": "GENESIS_ASSET_FEDERATION_REJECT", "detail": str(exc)})
            except Exception as exc:
                self._send(502, {"error": "GENESIS_ASSET_PROVIDER_DEGRADED", "detail": type(exc).__name__})
            return
        super().do_GET()

    def do_POST(self) -> None:  # noqa: N802
        if self.path.split("?", 1)[0] != "/v1/genesis/intent":
            super().do_POST()
            return
        try:
            payload = _read_json(self)
            self._send(200, compile_intent(payload))
        except GenesisAPIError as exc:
            self._send(400, {"error": "GENESIS_INTENT_REJECT", "detail": str(exc)})
        except Exception as exc:
            self._send(500, {"error": type(exc).__name__, "detail": str(exc)[:300]})


def main() -> int:
    parser = argparse.ArgumentParser(description="JANUS HOME Genesis API R0.5")
    parser.add_argument("--host", default=os.getenv("JANUS_API_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.getenv("PORT", os.getenv("JANUS_API_PORT", "8765"))))
    parser.add_argument("--allow-origin", default=os.getenv("JANUS_API_ALLOW_ORIGIN", "https://hawkar-usls.github.io"))
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    server.allowed_origin = args.allow_origin
    server.quiet = args.quiet
    print(f"JANUS Genesis API R0.5 listening on http://{args.host}:{args.port}")
    print("Typed asset federation: material / mesh / audio / mechanic")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
