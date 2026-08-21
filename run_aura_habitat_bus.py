from __future__ import annotations

import argparse
import json
import shlex
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from janus_spi.advancing_spiral import AdvancingSpiralDialogueEngine, AuraPeerAdapter
from janus_spi.habitat_bus import HabitatEventBus


def main() -> None:
    parser = argparse.ArgumentParser(description="Continuous Habitat -> Aura/SPI -> Habitat state-advancing spiral bus")
    parser.add_argument("--habitat-root", required=True, help="Path to local Janus_Genesis/habitat directory")
    parser.add_argument("--state-dir", default="state")
    parser.add_argument("--aura-peer", required=True, help="Aura peer command, e.g. python ../aura-oracle-tg/tools/aura_habitat_spiral_peer_v2.py")
    parser.add_argument("--interval", type=float, default=5.0)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--demihead-decision", choices=["PASS", "HOLD", "REJECT"], default="HOLD")
    args = parser.parse_args()

    habitat_root = Path(args.habitat_root)
    state_dir = Path(args.state_dir)
    engine = AdvancingSpiralDialogueEngine(
        state_dir=state_dir,
        habitat_root=habitat_root,
        aura_peer=AuraPeerAdapter(shlex.split(args.aura_peer)),
    )
    bus = HabitatEventBus(habitat_root, state_dir / "habitat_bus_state.json")

    print(json.dumps({
        "type": "JANUS_AURA_HABITAT_BUS",
        "status": "RUNNING_LOCAL_PROCESS",
        "habitat_root": str(habitat_root),
        "idle_behavior": "SILENT_NO_SELF_CHAT",
        "operation": "SPIRAL_STEP",
        "position_may_repeat_state_must_advance": True,
        "return_is_reset": False,
        "writeback": "LOCAL_EXPLICITLY_PUBLIC_MIRROR_ONLY",
    }, ensure_ascii=False))

    while True:
        events = bus.poll()
        for event in events:
            try:
                receipt = engine.spiral_step(
                    trigger_text=event["text"],
                    source_ref=event["source_ref"],
                    demihead_decision=args.demihead_decision,
                    intent_authority="LOCAL_PREVIEW",
                    public_content=bool(event.get("public_content", False)),
                )
                print(json.dumps(receipt, ensure_ascii=False))
            except Exception as exc:
                print(json.dumps({"type": "HABITAT_SPIRAL_EVENT_REJECT", "source_ref": event.get("source_ref"), "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        if args.once:
            return
        time.sleep(max(1.0, args.interval))


if __name__ == "__main__":
    main()
