from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from janus_spi import GitHubObserver, JanusSPICore, SemanticEvent


def cmd_observe(args: argparse.Namespace) -> None:
    core = JanusSPICore(args.state_dir)
    event = SemanticEvent.build(
        source=args.source,
        source_ref=args.source_ref,
        text=args.text,
        metadata={"STRATEGY_OWNER": args.strategy_owner, "EXECUTION_ASSISTANCE": args.execution_assistance},
    )
    print(json.dumps({"inserted": core.observe(event), "event_id": event.event_id}, ensure_ascii=False, indent=2))


def cmd_search(args: argparse.Namespace) -> None:
    core = JanusSPICore(args.state_dir)
    print(json.dumps(core.semantic_search(args.query, limit=args.limit), ensure_ascii=False, indent=2))


def cmd_poll(args: argparse.Namespace) -> None:
    core = JanusSPICore(args.state_dir)
    observer = GitHubObserver(args.config)
    if args.forever:
        observer.run_forever(core, poll_seconds=args.interval)
    else:
        print(json.dumps(observer.poll_once(core), ensure_ascii=False, indent=2))


def cmd_learn(args: argparse.Namespace) -> None:
    core = JanusSPICore(args.state_dir)
    event = SemanticEvent.build(
        source=args.source,
        source_ref=args.source_ref,
        text=args.text,
        metadata={"label_source": args.label_source},
    )
    core.observe(event)
    version = core.learn(
        task_id=args.task,
        task_type=args.type,
        event=event,
        label=args.label,
        provenance={
            "STRATEGY_OWNER": args.strategy_owner,
            "EXECUTION_ASSISTANCE": args.execution_assistance,
            "EVIDENCE_SOURCE": args.label_source,
        },
    )
    print(json.dumps({"task": args.task, "model_version": version, "event_id": event.event_id}, ensure_ascii=False, indent=2))


def cmd_predict(args: argparse.Namespace) -> None:
    core = JanusSPICore(args.state_dir)
    event = SemanticEvent.build(
        source=args.source,
        source_ref=args.source_ref,
        text=args.text,
        metadata={},
    )
    core.observe(event)
    target_time = time.time() + args.horizon_seconds
    target_definition = {
        "description": args.target,
        "horizon_seconds": args.horizon_seconds,
        "resolution_rule": args.resolution_rule,
    }
    forecast = core.predict(
        task_id=args.task,
        event=event,
        target_definition=target_definition,
        target_time=target_time,
        evidence_refs=[event.event_id],
    )
    print(json.dumps(forecast.__dict__, ensure_ascii=False, indent=2))


def cmd_resolve(args: argparse.Namespace) -> None:
    core = JanusSPICore(args.state_dir)
    print(json.dumps(core.resolve(args.forecast_id, args.outcome), ensure_ascii=False, indent=2))


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="JANUS Semantic-Predictive Intelligence runtime")
    p.add_argument("--state-dir", default="state")
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("observe", help="append one semantic observation")
    s.add_argument("--source", required=True)
    s.add_argument("--source-ref", required=True)
    s.add_argument("--text", required=True)
    s.add_argument("--strategy-owner", default="UNKNOWN")
    s.add_argument("--execution-assistance", default="UNKNOWN")
    s.set_defaults(func=cmd_observe)

    s = sub.add_parser("search", help="semantic search over the persistent ledger")
    s.add_argument("query")
    s.add_argument("--limit", type=int, default=10)
    s.set_defaults(func=cmd_search)

    s = sub.add_parser("poll", help="read repository constellation into semantic memory")
    s.add_argument("--config", default="config/constellation.json")
    s.add_argument("--forever", action="store_true")
    s.add_argument("--interval", type=int, default=300)
    s.set_defaults(func=cmd_poll)

    s = sub.add_parser("learn", help="incrementally learn from an explicitly resolved label")
    s.add_argument("--task", required=True)
    s.add_argument("--type", choices=["BINARY_PROBABILITY", "NUMERIC_FORECAST"], required=True)
    s.add_argument("--label", type=float, required=True)
    s.add_argument("--source", required=True)
    s.add_argument("--source-ref", required=True)
    s.add_argument("--text", required=True)
    s.add_argument("--label-source", required=True)
    s.add_argument("--strategy-owner", default="HAWKAR")
    s.add_argument("--execution-assistance", default="JANUS_SPI")
    s.set_defaults(func=cmd_learn)

    s = sub.add_parser("predict", help="freeze a probability or numeric forecast for a future target")
    s.add_argument("--task", required=True)
    s.add_argument("--source", required=True)
    s.add_argument("--source-ref", required=True)
    s.add_argument("--text", required=True)
    s.add_argument("--target", required=True)
    s.add_argument("--resolution-rule", required=True)
    s.add_argument("--horizon-seconds", type=int, required=True)
    s.set_defaults(func=cmd_predict)

    s = sub.add_parser("resolve", help="resolve a frozen forecast after its target time")
    s.add_argument("forecast_id")
    s.add_argument("--outcome", type=float, required=True)
    s.set_defaults(func=cmd_resolve)

    return p


if __name__ == "__main__":
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)
