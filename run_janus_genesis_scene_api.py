from __future__ import annotations

import argparse
import os
import sys
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from janus_spi.genesis_api import GenesisAPIError, health as legacy_health  # noqa: E402
from janus_spi.genesis_scene_graph import compile_scene_graph  # noqa: E402
from run_janus_genesis_api import Handler as LegacyHandler, _read_json  # noqa: E402


class SceneGraphHandler(LegacyHandler):
    server_version = "JANUSGenesisSceneAPI/0.4"

    def do_GET(self) -> None:  # noqa: N802
        if self.path.split("?", 1)[0] == "/v1/health":
            payload = legacy_health()
            payload.update(
                {
                    "scene_graph_available": True,
                    "scene_graph_schema": "janus.genesis.scene_graph.v1",
                    "scene_graph_response_schema": "janus.genesis.scene_graph.response.v1",
                    "scene_graph_version": "0.4.0",
                    "scene_graph_route": "POST /v1/genesis/scene-graph",
                    "persistent_service_claim": "DEPLOYMENT_REQUIRED_NOT_IMPLIED_BY_SOURCE_CODE",
                    "cors_origin": self.server.allowed_origin,
                }
            )
            self._send(200, payload)
            return
        super().do_GET()

    def do_POST(self) -> None:  # noqa: N802
        if self.path.split("?", 1)[0] != "/v1/genesis/scene-graph":
            super().do_POST()
            return
        try:
            payload = _read_json(self)
            self._send(200, compile_scene_graph(payload))
        except GenesisAPIError as exc:
            self._send(400, {"error": "GENESIS_SCENE_GRAPH_REJECT", "detail": str(exc)})
        except Exception as exc:
            self._send(500, {"error": type(exc).__name__, "detail": str(exc)[:300]})


def main() -> int:
    parser = argparse.ArgumentParser(description="JANUS HOME Genesis Scene Intent Graph API adapter")
    parser.add_argument("--host", default=os.getenv("JANUS_API_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.getenv("PORT", os.getenv("JANUS_API_PORT", "8765"))))
    parser.add_argument("--allow-origin", default=os.getenv("JANUS_API_ALLOW_ORIGIN", "https://hawkar-usls.github.io"))
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    server = ThreadingHTTPServer((args.host, args.port), SceneGraphHandler)
    server.allowed_origin = args.allow_origin
    server.quiet = args.quiet
    print(f"JANUS Genesis Scene API listening on http://{args.host}:{args.port}")
    print(f"CORS origin: {args.allow_origin}")
    print("Scene graph route: POST /v1/genesis/scene-graph")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
