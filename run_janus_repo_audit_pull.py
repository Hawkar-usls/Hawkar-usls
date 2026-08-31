#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
from pathlib import Path

from janus_spi.market_repo_audit import digest, verify_packet


def git(repo: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(repo), *args], text=True).strip()


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--outbox-repo", required=True)
    p.add_argument("--answered-dir", required=True)
    p.add_argument("--packet-out", required=True)
    p.add_argument("--request-out", required=True)
    p.add_argument("--receipt-out", required=True)
    p.add_argument("--status-out", required=True)
    a = p.parse_args()
    repo = Path(a.outbox_repo)
    answered = Path(a.answered_dir)
    packets_dir = repo / ".janus/market-home-outbox"
    candidates = []
    if packets_dir.is_dir():
        for path in sorted(packets_dir.glob("*.repo-audit.packet.json")):
            try:
                packet = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if not verify_packet(packet):
                continue
            rid = str(packet["service_request"]["request_id"])
            if (answered / f"{rid}.repo-audit-result.json").exists():
                continue
            created = str(packet.get("created_at") or "")
            candidates.append((created, rid, path, packet))
    if not candidates:
        write_json(Path(a.status_out), {
            "schema": "janus.home.repo_audit_pull_status.v1",
            "request_found": False,
            "reason": "NO_UNANSWERED_VALID_REPO_AUDIT_PACKET",
        })
        return 0
    candidates.sort(key=lambda x: (x[0], x[1]))
    _, rid, path, packet = candidates[0]
    source_commit = git(repo, "rev-parse", "HEAD")
    rel = path.relative_to(repo).as_posix()
    blob_sha = git(repo, "hash-object", rel)
    file_sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
    receipt = {
        "schema": "janus.home.repo_audit_pull_receipt.v1",
        "market_repository": "Hawkar-usls/JANUS-MACHINE-MARKET",
        "market_outbox_branch": "janus/market-home-outbox",
        "market_source_commit": source_commit,
        "market_packet_path": rel,
        "market_packet_git_blob_sha": blob_sha,
        "market_packet_file_sha256": file_sha256,
        "market_packet_hash": packet["packet_hash"],
        "service_request_id": rid,
        "service_request_hash": packet["service_request_hash"],
        "purchase_id": packet["purchase_grant"]["purchase_id"],
        "purchase_grant_hash": packet["purchase_grant_hash"],
        "transport": "PHYSARIUS_CREDENTIALLESS_PULL",
        "credentialless_public_read": True,
        "cross_repo_write_credential_used": False,
        "delivery_is_authority": False,
        "repository_content_is_command": False,
        "execution_authority_granted": False,
        "external_effect_authorized": False,
    }
    receipt["receipt_hash"] = digest(receipt)
    shutil.copyfile(path, a.packet_out)
    write_json(Path(a.request_out), packet["service_request"])
    write_json(Path(a.receipt_out), receipt)
    write_json(Path(a.status_out), {
        "schema": "janus.home.repo_audit_pull_status.v1",
        "request_found": True,
        "service_request_id": rid,
        "purchase_id": packet["purchase_grant"]["purchase_id"],
        "market_source_commit": source_commit,
        "market_packet_git_blob_sha": blob_sha,
        "pull_receipt_hash": receipt["receipt_hash"],
    })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
