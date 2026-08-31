#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
from pathlib import Path

from janus_spi.activator import canonical_hash
from janus_spi.market_buyer_conversation import build_market_terminal_message, verify_market_buyer_packet

PAID_PACKET_SCHEMA = "janus.machine_market.home_paid_buyer_query_packet.v1"


def _git(repo: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(repo), *args], text=True).strip()


def _write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description="Pull the oldest unanswered paid JANUS Machine Market buyer-query packet")
    parser.add_argument("--outbox-repo", required=True)
    parser.add_argument("--answered-dir", required=True)
    parser.add_argument("--packet-out", required=True)
    parser.add_argument("--request-out", required=True)
    parser.add_argument("--receipt-out", required=True)
    parser.add_argument("--status-out", required=True)
    args = parser.parse_args()

    outbox_repo = Path(args.outbox_repo)
    answered_dir = Path(args.answered_dir)
    packets_dir = outbox_repo / ".janus/market-home-outbox"
    candidates = []
    if packets_dir.is_dir():
        for path in sorted(packets_dir.glob("*.paid.packet.json")):
            try:
                packet = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if packet.get("schema") != PAID_PACKET_SCHEMA or not verify_market_buyer_packet(packet):
                continue
            qid = str(packet["query_id"])
            if (answered_dir / f"{qid}.paid-result.json").exists():
                continue
            created_at = str((packet.get("buyer_query") or {}).get("created_at") or "")
            candidates.append((created_at, qid, path, packet))

    if not candidates:
        _write_json(Path(args.status_out), {
            "schema": "janus.home.market_paid_buyer_query_pull_status.v1",
            "request_found": False,
            "reason": "NO_UNANSWERED_VALID_PAID_MARKET_BUYER_QUERY",
        })
        return 0

    candidates.sort(key=lambda row: (row[0], row[1]))
    _, qid, path, packet = candidates[0]
    terminal_request = build_market_terminal_message(packet)
    source_commit = _git(outbox_repo, "rev-parse", "HEAD")
    rel = path.relative_to(outbox_repo).as_posix()
    receipt = {
        "schema": "janus.home.market_paid_buyer_query_pull_receipt.v1",
        "market_repository": "Hawkar-usls/JANUS-MACHINE-MARKET",
        "market_outbox_branch": "janus/market-home-outbox",
        "market_source_commit": source_commit,
        "market_packet_path": rel,
        "market_packet_git_blob_sha": _git(outbox_repo, "hash-object", rel),
        "market_packet_file_sha256": _file_sha256(path),
        "market_packet_hash": packet["packet_hash"],
        "query_id": qid,
        "query_hash": packet["query_hash"],
        "purchase_id": packet["purchase_grant"]["purchase_id"],
        "purchase_grant_hash": packet["purchase_grant_hash"],
        "payment_reference": packet["payment_receipt"]["payment_reference"],
        "payment_receipt_hash": packet["payment_receipt_hash"],
        "money_enabled": True,
        "production_purchase": True,
        "transport": "PHYSARIUS_CREDENTIALLESS_PULL",
        "credentialless_public_read": True,
        "cross_repo_write_credential_used": False,
        "delivery_is_authority": False,
        "execution_authority_granted": False,
        "external_effect_authorized": False,
    }
    receipt["receipt_hash"] = canonical_hash(receipt)
    shutil.copyfile(path, args.packet_out)
    _write_json(Path(args.request_out), terminal_request)
    _write_json(Path(args.receipt_out), receipt)
    _write_json(Path(args.status_out), {
        "schema": "janus.home.market_paid_buyer_query_pull_status.v1",
        "request_found": True,
        "query_id": qid,
        "purchase_id": packet["purchase_grant"]["purchase_id"],
        "payment_reference": packet["payment_receipt"]["payment_reference"],
        "market_source_commit": source_commit,
        "pull_receipt_hash": receipt["receipt_hash"],
    })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
