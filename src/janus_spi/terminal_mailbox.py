from __future__ import annotations

import base64
import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable, Dict, Iterable

from .terminal_conversation import TERMINAL_REPOSITORY, verify_terminal_message

TERMINAL_MAILBOX_BRANCH = "janus/terminal-mailbox"
TERMINAL_REQUEST_PREFIX = ".janus/terminal-mailbox/requests/"
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
            "User-Agent": "JANUS-Terminal-Mailbox/1.0",
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
        rows.append(value)
    rows.sort(key=lambda row: (float(row.get("created_at") or 0.0), str(row.get("message_id") or "")))
    return rows


def responded_message_ids(reader: PublicGitHubMailboxReader) -> set[str]:
    ids: set[str] = set()
    for path in reader.paths(HOME_REPOSITORY, HOME_RESPONSE_BRANCH, HOME_RESPONSE_PREFIX):
        name = path.rsplit("/", 1)[-1]
        suffix = ".response.json"
        if name.startswith("tm-") and name.endswith(suffix):
            ids.add(name[:-len(suffix)])
    return ids


def next_unanswered_request(reader: PublicGitHubMailboxReader) -> Dict[str, Any] | None:
    seen = responded_message_ids(reader)
    for value in terminal_requests(reader):
        if str(value.get("message_id")) not in seen:
            return value
    return None


__all__ = [
    "HOME_RESPONSE_BRANCH",
    "HOME_RESPONSE_PREFIX",
    "PublicGitHubMailboxReader",
    "TERMINAL_MAILBOX_BRANCH",
    "TERMINAL_REQUEST_PREFIX",
    "TerminalMailboxError",
    "next_unanswered_request",
    "responded_message_ids",
    "terminal_requests",
]
