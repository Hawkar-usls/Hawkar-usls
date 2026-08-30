from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from janus_spi.mailbox_roundtrip import JanusCredentiallessPacketRoundtrip, SUCCESS_TERMINAL


def main() -> None:
    parser = argparse.ArgumentParser(description="JANUS bounded dual-lane credentialless packet roundtrip witness")
    parser.add_argument("--source-ref", required=True)
    parser.add_argument("--payload-file", required=True)
    parser.add_argument("--state-dir", default="runtime/credentialless-roundtrip/state")
    parser.add_argument("--routing", default=".janus/activator/ROUTING_TABLE.json")
    parser.add_argument("--policy", default="config/JANUS_INTELLIGENCE_STEP_POLICY-v1.0.json")
    parser.add_argument("--secret-token-env", default="JANUS_DEMIURGE_DISPATCH_TOKEN")
    parser.add_argument("--local-token-env", default="GITHUB_TOKEN")
    parser.add_argument("--poll-interval", type=float, default=10.0)
    parser.add_argument("--max-wait", type=float, default=420.0)
    parser.add_argument("--output", default="runtime/credentialless-roundtrip/result.json")
    parser.add_argument("--require-complete", action="store_true")
    args = parser.parse_args()

    payload = json.loads(Path(args.payload_file).read_text(encoding="utf-8"))
    witness = JanusCredentiallessPacketRoundtrip(
        state_dir=args.state_dir,
        routing_path=args.routing,
        policy_path=args.policy,
        poll_interval_seconds=args.poll_interval,
        max_wait_seconds=args.max_wait,
    )
    result = witness.run(
        source_ref=args.source_ref,
        payload=payload,
        secret_dispatch_token=os.environ.get(args.secret_token_env, ""),
        local_github_token=os.environ.get(args.local_token_env, ""),
    )

    text = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(text, encoding="utf-8")
    print(text, end="")

    if args.require_complete and result.get("terminal") != SUCCESS_TERMINAL:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
