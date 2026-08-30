#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from janus_spi.terminal_mailbox import PublicGitHubMailboxReader, mailbox_selection


def main() -> int:
    parser = argparse.ArgumentParser(description="Pull the oldest unanswered, non-cancelled sealed Terminal conversation message through public GitHub read only")
    parser.add_argument("--output", default="runtime/terminal-request.json")
    parser.add_argument("--status-out", default="runtime/terminal-pull-status.json")
    args = parser.parse_args()

    reader = PublicGitHubMailboxReader()
    selection = mailbox_selection(reader)
    request = selection["request"]
    status = {
        "schema": "janus.terminal.pull_status.v1",
        "credentialless_public_read": True,
        "cross_repo_write_credential_used": False,
        "request_found": request is not None,
        "message_id": request.get("message_id") if request else None,
        "message_hash": request.get("message_hash") if request else None,
        "request_count": selection["request_count"],
        "response_count": selection["response_count"],
        "cancellation_count": selection["cancellation_count"],
        "responded_message_ids": selection["responded_message_ids"],
        "cancelled_message_ids": selection["cancelled_message_ids"],
        "cancelled_request_fresh_cognition": False,
        "cancellation_deletes_request": False,
        "cancellation_deletes_response": False,
        "command_authority_granted": False,
        "external_effect_authorized": False,
        "laws": selection["laws"],
        "terminal": "TERMINAL_REQUEST_READY" if request else "TERMINAL_MAILBOX_NO_UNANSWERED_REQUEST",
    }
    status_path = Path(args.status_out)
    status_path.parent.mkdir(parents=True, exist_ok=True)
    status_path.write_text(json.dumps(status, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if request is not None:
        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(request, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(status, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
