from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from janus_spi.live_cycle_hardening import HardenedJanusLiveCycleV091


def main() -> None:
    parser = argparse.ArgumentParser(description="JANUS persistent fresh-stimulus closed-loop launch candidate")
    parser.add_argument("--source-ref", required=True)
    parser.add_argument("--payload-file", required=True)
    parser.add_argument("--state-dir", default="state/activator")
    parser.add_argument("--routing", default=".janus/activator/ROUTING_TABLE.json")
    parser.add_argument("--policy", default="config/JANUS_INTELLIGENCE_STEP_POLICY-v1.0.json")
    parser.add_argument("--dispatch-token-env", default="JANUS_DEMIURGE_DISPATCH_TOKEN")
    parser.add_argument("--provenance-token-env", default="JANUS_ACK_PROVENANCE_TOKEN")
    parser.add_argument("--poll-interval", type=float, default=5.0)
    parser.add_argument("--max-wait", type=float, default=240.0)
    parser.add_argument("--output")
    parser.add_argument("--require-complete", action="store_true")
    args = parser.parse_args()

    payload = json.loads(Path(args.payload_file).read_text(encoding="utf-8"))
    cycle = HardenedJanusLiveCycleV091(
        state_dir=args.state_dir,
        routing_path=args.routing,
        policy_path=args.policy,
        poll_interval_seconds=args.poll_interval,
        max_wait_seconds=args.max_wait,
    )
    result = cycle.run(
        source_ref=args.source_ref,
        payload=payload,
        dispatch_token=os.environ.get(args.dispatch_token_env, ""),
        provenance_token=os.environ.get(args.provenance_token_env, ""),
    )
    text = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
    print(text, end="")

    if args.require_complete and (
        result.get("terminal") != "LIVE_CYCLE_COMPLETED_RETURNED_HOME"
        or result.get("target_execution_observed") is not True
        or result.get("returned_at_home") is not True
        or result.get("physical_runtime_effect_authorized") is not False
    ):
        raise SystemExit(2)


if __name__ == "__main__":
    main()
