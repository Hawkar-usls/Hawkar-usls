from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))
from janus_spi.oidc_roundtrip import JanusOIDCPacketRoundtrip, SUCCESS_TERMINAL


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-ref", required=True)
    parser.add_argument("--payload-file", required=True)
    parser.add_argument("--state-dir", default="runtime/oidc-roundtrip/state")
    parser.add_argument("--poll-interval", type=float, default=10.0)
    parser.add_argument("--max-wait", type=float, default=660.0)
    parser.add_argument("--output", default="runtime/oidc-roundtrip/result.json")
    parser.add_argument("--require-complete", action="store_true")
    args = parser.parse_args()

    payload = json.loads(Path(args.payload_file).read_text(encoding="utf-8"))
    result = JanusOIDCPacketRoundtrip(
        state_dir=args.state_dir,
        poll_interval_seconds=args.poll_interval,
        max_wait_seconds=args.max_wait,
    ).run(
        source_ref=args.source_ref,
        payload=payload,
        secret_dispatch_token=os.environ.get("JANUS_DEMIURGE_DISPATCH_TOKEN", ""),
        local_github_token=os.environ.get("GITHUB_TOKEN", ""),
    )
    text = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    print(text, end="")
    if args.require_complete and result.get("terminal") != SUCCESS_TERMINAL:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
