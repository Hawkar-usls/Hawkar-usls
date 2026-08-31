from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from janus_spi.activator import ActivationEvent
from janus_spi.activator_slime_r0 import SlimeAwareJanusActivatorR0


def main() -> None:
    parser = argparse.ArgumentParser(description="JANUS HOME bounded root activator with advisory Slime Memory R0")
    parser.add_argument("--event-file", required=True, help="JSON activation event file")
    parser.add_argument("--state-dir", default="state/activator")
    parser.add_argument("--routing", default=".janus/activator/ROUTING_TABLE.json")
    parser.add_argument("--policy", default="config/JANUS_INTELLIGENCE_STEP_POLICY-v1.0.json")
    args = parser.parse_args()

    raw = json.loads(Path(args.event_file).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise SystemExit("ACTIVATION_EVENT_JSON_OBJECT_REQUIRED")

    event = ActivationEvent.build(
        source_kind=raw.get("source_kind", ""),
        source_ref=raw.get("source_ref", ""),
        payload=raw.get("payload"),
        classifications=raw.get("classifications") or [],
        fresh=bool(raw.get("fresh", False)),
        self_generated=bool(raw.get("self_generated", False)),
        command_authority=bool(raw.get("command_authority", False)),
        effect_authorized=bool(raw.get("effect_authorized", False)),
    )
    activator = SlimeAwareJanusActivatorR0(
        state_dir=args.state_dir,
        routing_path=args.routing,
        policy_path=args.policy,
    )
    receipt = activator.activate(event)
    print(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
