from __future__ import annotations

import base64
import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable, Dict, Iterable, Mapping

from .activator import canonical_hash
from .terminal_conversation import TERMINAL_REPOSITORY, verify_terminal_message

TERMINAL_MAILBOX_BRANCH = "janus/terminal-mailbox"
TERMINAL_REQUEST_PREFIX = ".janus/terminal-mailbox/requests/"
TERMINAL_CANCELLATION_PREFIX = ".janus/terminal-mailbox/cancellations/"
TERMINAL_CANCELLATION_SCHEMA = "janus.terminal.message_cancellation.v1"
TERMINAL_CANCELLATION_ACTOR = "Hawkar-usls"
HOME_REPOSITORY = "Hawkar-usls/Hawkar-usls"
HOME_RESPONSE_BRANCH = "janus/terminal-responses"
HOME_RESPONSE_PREFIX = ".janus/terminal-responses/"


class TerminalMailboxError(RuntimeError):
    pass


class PublicGitHubMailboxReader:
    """Credentialless public-read transport for Terminal conversation mailboxes."""

    def __init__(
        self,
        *,
        api_base: str = "https://api.github.com",
        opener: Callable[..., Any] = urllib.request.urlopen,
    ) -> None:
        self.api_base = api_base.rstrip("/")
        self.opener = opener

    def _json(self, url: str, *, allow_404: bool = False) -> Any:
        request = urllib.request.Request(url, headers={
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "JANUS-Terminal-Mailbox/1.1",
        })
        try:
            response = self.opener(request, timeout=20.0)
            return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if allow_404 and exc.code == 404:
                return None
            raise TerminalMailboxError(f"PUBLIC_GITHUB_HTTP_{exc.code}:{url}") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise TerminalMailboxError(f"PUBLIC_GITHUB_READ_UNAVAILABLE:{type(exc).__name__}") from exc

    def branch_head(self, repository: str, branch: str) -> str | None:
        owner, name = repository.split("/", 1)
        value = self._json(
            f"{self.api_base}/repos/{urllib.parse.quote(owner)}/{urllib.parse.quote(name)}"
            f"/branches/{urllib.parse.quote(branch, safe='')}",
            allow_404=True,
        )
        if value is None:
            return None
        sha = str(((value.get("commit") or {}).get("sha") or ""))
        return sha if len(sha) == 40 else None

    def recursive_tree(self, repository: str, sha: str) -> Dict[str, Any]:
        owner, name = repository.split("/", 1)
        value = self._json(
            f"{self.api_base}/repos/{urllib.parse.quote(owner)}/{urllib.parse.quote(name)}"
            f"/git/trees/{urllib.parse.quote(sha, safe='')}?recursive=1"
        )
        if not isinstance(value, dict) or not isinstance(value.get("tree"), list):
            raise TerminalMailboxError("PUBLIC_MAILBOX_TREE_MALFORMED")
        if value.get("truncated") is True:
            raise TerminalMailboxError("PUBLIC_MAILBOX_TREE_UNKNOWN_RESOURCE_LIMIT")
        return value

    def json_file(self, repository: str, path: str, *, ref: str) -> Dict[str, Any]:
        owner, name = repository.split("/", 1)
        encoded = "/".join(urllib.parse.quote(part, safe="") for part in path.split("/"))
        value = self._json(
            f"{self.api_base}/repos/{urllib.parse.quote(owner)}/{urllib.parse.quote(name)}"
            f"/contents/{encoded}?ref={urllib.parse.quote(ref, safe='')}"
        )
        if not isinstance(value, dict) or value.get("encoding") != "base64":
            raise TerminalMailboxError("PUBLIC_MAILBOX_CONTENT_MALFORMED")
        try:
            raw = base64.b64decode(str(value.get("content") or ""), validate=False)
            parsed = json.loads(raw.decode("utf-8"))
        except Exception as exc:
            raise TerminalMailboxError("PUBLIC_MAILBOX_JSON_INVALID") from exc
        if not isinstance(parsed, dict):
            raise TerminalMailboxError("PUBLIC_MAILBOX_JSON_OBJECT_REQUIRED")
        return parsed

    def paths(self, repository: str, branch: str, prefix: str) -> list[str]:
        head = self.branch_head(repository, branch)
        if head is None:
            return []
        tree = self.recursive_tree(repository, head)
        return sorted(
            str(row.get("path"))
            for row in tree["tree"]
            if isinstance(row, dict)
            and row.get("type") == "blob"
            and str(row.get("path") or "").startswith(prefix)
            and str(row.get("path") or "").endswith(".json")
        )


def terminal_requests(reader: PublicGitHubMailboxReader) -> list[Dict[str, Any]]:
    rows: list[Dict[str, Any]] = []
    for path in reader.paths(TERMINAL_REPOSITORY, TERMINAL_MAILBOX_BRANCH, TERMINAL_REQUEST_PREFIX):
        value = reader.json_file(TERMINAL_REPOSITORY, path, ref=TERMINAL_MAILBOX_BRANCH)
        if not verify_terminal_message(value):
            raise TerminalMailboxError(f"INVALID_TERMINAL_MESSAGE:{path}")
        expected_path = f"{TERMINAL_REQUEST_PREFIX}{value['message_id']}.json"
        if path != expected_path:
            raise TerminalMailboxError(f"TERMINAL_MESSAGE_FILENAME_ID_MISMATCH:{path}")
        rows.append(value)
    rows.sort(key=lambda row: (float(row.get("created_at") or 0.0), str(row.get("message_id") or "")))
    return rows


def verify_terminal_cancellation(value: Mapping[str, Any]) -> bool:
    if not isinstance(value, Mapping):
        return False
    body = dict(value)
    claimed = str(body.pop("cancellation_hash", ""))
    if len(claimed) != 64 or canonical_hash(body) != claimed:
        return False
    identity = {
        "terminal_repository": body.get("terminal_repository"),
        "message_id": body.get("message_id"),
        "message_hash": body.get("message_hash"),
        "conversation_id": body.get("conversation_id"),
        "source_ref": body.get("source_ref"),
        "cancelled_by": body.get("cancelled_by"),
        "cancelled_at": body.get("cancelled_at"),
        "reason": body.get("reason"),
    }
    laws = set(body.get("laws") or [])
    return all([
        body.get("schema") == TERMINAL_CANCELLATION_SCHEMA,
        body.get("cancellation_id") == "tc-" + canonical_hash(identity),
        body.get("terminal_repository") == TERMINAL_REPOSITORY,
        str(body.get("message_id") or "").startswith("tm-"),
        len(str(body.get("message_hash") or "")) == 64,
        body.get("cancelled_by") == TERMINAL_CANCELLATION_ACTOR,
        body.get("reason") == "ISSUE_CLOSED_BY_ADMITTED_HUMAN",
        body.get("request_deleted") is False,
        body.get("response_deleted") is False,
        body.get("cognition_authorized") is False,
        body.get("command_authority_granted") is False,
        body.get("claim_authority_granted") is False,
        body.get("scientific_evidence_authority_granted") is False,
        body.get("world_truth_authority_granted") is False,
        body.get("external_effect_authorized") is False,
        body.get("physical_runtime_effect_authorized") is False,
        body.get("terminal") == "TERMINAL_MESSAGE_CANCELLATION_TOMBSTONE_READY",
        {
            "CANCEL != DELETE",
            "CANCEL != ERASE_RESPONSE",
            "CANCELLED_REQUEST != FRESH_COGNITION",
        }.issubset(laws),
    ])


def terminal_cancellations(
    reader: PublicGitHubMailboxReader,
    *,
    requests: Iterable[Mapping[str, Any]] | None = None,
) -> Dict[str, Dict[str, Any]]:
    request_rows = list(requests) if requests is not None else terminal_requests(reader)
    request_by_id = {str(row.get("message_id")): dict(row) for row in request_rows}
    cancelled: Dict[str, Dict[str, Any]] = {}
    for path in reader.paths(TERMINAL_REPOSITORY, TERMINAL_MAILBOX_BRANCH, TERMINAL_CANCELLATION_PREFIX):
        value = reader.json_file(TERMINAL_REPOSITORY, path, ref=TERMINAL_MAILBOX_BRANCH)
        if not verify_terminal_cancellation(value):
            raise TerminalMailboxError(f"INVALID_TERMINAL_CANCELLATION:{path}")
        message_id = str(value.get("message_id") or "")
        expected_path = f"{TERMINAL_CANCELLATION_PREFIX}{message_id}.json"
        if path != expected_path:
            raise TerminalMailboxError(f"TERMINAL_CANCELLATION_FILENAME_ID_MISMATCH:{path}")
        request = request_by_id.get(message_id)
        if request is None:
            raise TerminalMailboxError(f"TERMINAL_CANCELLATION_UNBOUND_REQUEST:{message_id}")
        if any([
            value.get("message_hash") != request.get("message_hash"),
            value.get("conversation_id") != request.get("conversation_id"),
            value.get("source_ref") != request.get("source_ref"),
        ]):
            raise TerminalMailboxError(f"TERMINAL_CANCELLATION_REQUEST_BINDING_MISMATCH:{message_id}")
        if message_id in cancelled and cancelled[message_id] != value:
            raise TerminalMailboxError(f"TERMINAL_CANCELLATION_DUPLICATE_CONFLICT:{message_id}")
        cancelled[message_id] = value
    return cancelled


def responded_message_ids(reader: PublicGitHubMailboxReader) -> set[str]:
    ids: set[str] = set()
    for path in reader.paths(HOME_REPOSITORY, HOME_RESPONSE_BRANCH, HOME_RESPONSE_PREFIX):
        name = path.rsplit("/", 1)[-1]
        suffix = ".response.json"
        if name.startswith("tm-") and name.endswith(suffix):
            ids.add(name[:-len(suffix)])
    return ids


def mailbox_selection(reader: PublicGitHubMailboxReader) -> Dict[str, Any]:
    requests = terminal_requests(reader)
    responded = responded_message_ids(reader)
    cancellations = terminal_cancellations(reader, requests=requests)
    cancelled_ids = set(cancellations)
    selected = None
    for value in requests:
        message_id = str(value.get("message_id"))
        if message_id in responded or message_id in cancelled_ids:
            continue
        selected = value
        break
    return {
        "request": selected,
        "request_count": len(requests),
        "responded_message_ids": sorted(responded),
        "cancelled_message_ids": sorted(cancelled_ids),
        "response_count": len(responded),
        "cancellation_count": len(cancelled_ids),
        "laws": [
            "CANCEL != DELETE",
            "CANCELLED_REQUEST != FRESH_COGNITION",
            "CANCELLATION_SUPPRESSES_COGNITION != CANCELLATION_HIDES_PROVENANCE",
        ],
    }


def next_unanswered_request(reader: PublicGitHubMailboxReader) -> Dict[str, Any] | None:
    return mailbox_selection(reader)["request"]


__all__ = [
    "HOME_REPOSITORY",
    "HOME_RESPONSE_BRANCH",
    "HOME_RESPONSE_PREFIX",
    "PublicGitHubMailboxReader",
    "TERMINAL_CANCELLATION_PREFIX",
    "TERMINAL_CANCELLATION_SCHEMA",
    "TERMINAL_MAILBOX_BRANCH",
    "TERMINAL_REQUEST_PREFIX",
    "TerminalMailboxError",
    "mailbox_selection",
    "next_unanswered_request",
    "responded_message_ids",
    "terminal_cancellations",
    "terminal_requests",
    "verify_terminal_cancellation",
]
