from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from janus_spi.persistent_state_v08 import HardenedJanusPersistentStateV08


def main() -> None:
    parser = argparse.ArgumentParser(description="JANUS HOME persistent Activator hearth")
    parser.add_argument("--state-dir", default="state/activator")
    sub = parser.add_subparsers(dest="command", required=True)

    cycle = sub.add_parser("cycle", help="Run non-cognitive WAKE -> HEARTBEAT -> SLEEP cycle")
    cycle.add_argument("--source", required=True)
    cycle.add_argument("--reason", required=True)
    cycle.add_argument("--architecture-sha", required=True)
    cycle.add_argument("--workflow-run-id", default="")

    sub.add_parser("verify", help="Verify persistent resident identity and all known local ledgers")

    args = parser.parse_args()
    state = HardenedJanusPersistentStateV08(args.state_dir)

    if args.command == "cycle":
        result = state.hearth_cycle(
            source=args.source,
            reason=args.reason,
            architecture_sha=args.architecture_sha,
            workflow_run_id=args.workflow_run_id,
        )
    else:
        state.initialize()
        result = state.verify()
        if not result.get("ok"):
            print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
            raise SystemExit(2)

    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
