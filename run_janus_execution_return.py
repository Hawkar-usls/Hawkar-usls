from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from janus_spi.execution_grant import ExecutionGrantLedger
from janus_spi.execution_return import GitHubExecutionReturnVerifier, JanusExecutionResultFinalizer
from janus_spi.execution_transport import ExecutionTransportLedger


def _unique(rows, predicate, error):
    matches = [row for row in rows if predicate(row)]
    if len(matches) != 1:
        raise SystemExit(f"{error}_MATCH_COUNT={len(matches)}")
    return matches[0]


def main() -> None:
    parser = argparse.ArgumentParser(description="JANUS HOME authenticate and finalize bounded target execution return")
    parser.add_argument("--run-id", required=True, type=int)
    parser.add_argument("--state-dir", default="state/activator")
    parser.add_argument("--token-env", default="JANUS_ACK_PROVENANCE_TOKEN")
    parser.add_argument("--provenance-output")
    parser.add_argument("--receipt-output")
    parser.add_argument("--snapshot-output")
    parser.add_argument("--final-output")
    parser.add_argument("--require-observed", action="store_true")
    args = parser.parse_args()

    state = Path(args.state_dir)
    verifier = GitHubExecutionReturnVerifier(state_dir=state)
    provenance, execution_receipt, snapshot = verifier.verify_run(
        args.run_id,
        token=os.environ.get(args.token_env, ""),
    )

    def dump(path_value, obj):
        if path_value and obj is not None:
            path = Path(path_value)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    dump(args.provenance_output, provenance)
    dump(args.receipt_output, execution_receipt)
    dump(args.snapshot_output, snapshot)

    final = None
    if provenance.get("source_authenticated") is True and execution_receipt is not None:
        grant_id = str(execution_receipt.get("grant_id") or "")
        grant_hash = str(execution_receipt.get("grant_hash") or "")
        grant = _unique(
            ExecutionGrantLedger(state / "execution_grant_ledger.jsonl").read(),
            lambda row: row.get("grant_id") == grant_id and row.get("grant_hash") == grant_hash,
            "EXECUTION_GRANT",
        )
        transport_rows = ExecutionTransportLedger(state / "execution_transport_ledger.jsonl").read()
        candidates = [
            row for row in transport_rows
            if row.get("grant_id") == grant_id
            and row.get("grant_hash") == grant_hash
            and row.get("network_boundary_entered") is True
            and row.get("terminal") in {"EXECUTION_TRANSPORT_SENT_AWAITING_RESULT", "EXECUTION_TRANSPORT_OUTCOME_UNDETERMINED"}
        ]
        if len(candidates) != 1:
            raise SystemExit(f"EXECUTION_TRANSPORT_MATCH_COUNT={len(candidates)}")
        final = JanusExecutionResultFinalizer(state_dir=state).finalize(grant, candidates[0], provenance, execution_receipt)
        dump(args.final_output, final)

    output = final if final is not None else provenance
    print(json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True))
    if args.require_observed and (
        final is None
        or final.get("terminal") != "EXECUTION_RESULT_AUTHENTICATED_READ_ONLY_ORIENTATION_OBSERVED"
        or final.get("target_execution_observed_under_github_trust_model") is not True
    ):
        raise SystemExit(2)


if __name__ == "__main__":
    main()
