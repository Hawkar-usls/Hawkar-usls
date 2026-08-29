from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from janus_spi.ack_provenance import GitHubAckProvenanceVerifier
from janus_spi.local_lineage import HardenedJanusAuthenticatedAckFinalizer

CREDENTIAL_ENV = "JANUS_ACK_PROVENANCE_TOKEN"
AUTHENTICATED_TERMINAL = "ACK_SOURCE_AUTHENTICATED_GITHUB_ACTIONS_TRUST_MODEL"
FINAL_SUCCESS_TERMINALS = {
    "ACK_AUTHENTICATED_DELIVERY_CONFIRMED_NO_EXECUTION",
    "ACK_AUTHENTICATED_REJECTION_CONFIRMED_NO_EXECUTION",
    "ACK_AUTHENTICATED_FINALIZATION_ALREADY_RECORDED",
}


def load_object(path: str) -> dict:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise SystemExit(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def write_json(path: str | None, value: dict) -> None:
    if not path:
        return
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="JANUS Activator GitHub Actions ACK source provenance verifier")
    parser.add_argument("--run-id", required=True, type=int, help="Janus-Demiurge receiver workflow run ID")
    parser.add_argument("--state-dir", default="state/activator")
    parser.add_argument("--provenance-output", help="Optional v0.6 provenance receipt path")
    parser.add_argument("--ack-output", help="Optional authenticated artifact ACK JSON path")
    parser.add_argument("--structural-receipt", help="Optional local structural receipt to finalize after source authentication")
    parser.add_argument("--final-output", help="Optional authenticated finalization receipt path")
    parser.add_argument("--require-authenticated", action="store_true", help="Exit non-zero unless source authentication succeeds")
    parser.add_argument("--require-finalized", action="store_true", help="Exit non-zero unless authenticated finalization succeeds")
    args = parser.parse_args()

    if args.require_finalized and not args.structural_receipt:
        raise SystemExit("REQUIRE_FINALIZED_NEEDS_STRUCTURAL_RECEIPT")

    token = os.environ.get(CREDENTIAL_ENV, "")
    verifier = GitHubAckProvenanceVerifier(state_dir=args.state_dir)
    provenance, ack = verifier.verify_run(args.run_id, token=token)
    write_json(args.provenance_output, provenance)
    if ack is not None:
        write_json(args.ack_output, ack)

    result = {"provenance": provenance, "ack": ack, "finalization": None}
    if args.structural_receipt and provenance.get("terminal") == AUTHENTICATED_TERMINAL:
        structural = load_object(args.structural_receipt)
        final = HardenedJanusAuthenticatedAckFinalizer(state_dir=args.state_dir).finalize(structural, provenance)
        write_json(args.final_output, final)
        result["finalization"] = final

    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))

    if args.require_authenticated and provenance.get("terminal") != AUTHENTICATED_TERMINAL:
        raise SystemExit(2)
    if args.require_finalized and (result["finalization"] or {}).get("terminal") not in FINAL_SUCCESS_TERMINALS:
        raise SystemExit(3)


if __name__ == "__main__":
    main()
