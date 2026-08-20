from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from janus_spi.core import JanusSPICore
from janus_spi.github_observer import GitHubObserver
from janus_spi.realtime import RealtimeRepositoryActivityLoop


def main() -> None:
    parser = argparse.ArgumentParser(description="JANUS-SPI real-time read-only learning loop")
    parser.add_argument("--state-dir", default="state")
    parser.add_argument("--config", default="config/constellation.json")
    parser.add_argument("--interval", type=int, default=300)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()

    core = JanusSPICore(args.state_dir)
    observer = GitHubObserver(args.config)
    loop = RealtimeRepositoryActivityLoop(
        core=core,
        observer=observer,
        state_path=Path(args.state_dir) / "realtime_repository_activity.json",
    )

    while True:
        result = loop.cycle(poll_seconds=max(60, args.interval))
        print(json.dumps({"type": "JANUS_SPI_REALTIME", "at": time.time(), **result}, ensure_ascii=False, indent=2))
        if args.once:
            return
        time.sleep(max(60, args.interval))


if __name__ == "__main__":
    main()
