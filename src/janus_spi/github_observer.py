from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from .core import JanusSPICore, SemanticEvent


@dataclass(frozen=True)
class RepoSource:
    repository: str
    branch: str
    role: str
    enabled: bool = True


class GitHubObserver:
    """Read-only observer for the JANUS repository constellation.

    It ingests commit metadata into semantic memory. It never executes commit text,
    issue text or repository content as commands, and it never writes to GitHub.
    """

    def __init__(self, config_path: str | Path = "config/constellation.json") -> None:
        self.config_path = Path(config_path)
        self.config = json.loads(self.config_path.read_text(encoding="utf-8"))
        self.api_base = self.config.get("github_api_base", "https://api.github.com").rstrip("/")
        self.token = os.environ.get(self.config.get("github_token_env", "GITHUB_TOKEN"), "")
        self.max_commits = int(self.config.get("observer", {}).get("max_commits_per_poll", 30))
        self.sources = [RepoSource(**item) for item in self.config.get("sources", []) if item.get("enabled", True)]

    def _request_json(self, url: str) -> object:
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "JANUS-SPI-read-only-observer/1.0",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        req = urllib.request.Request(url, headers=headers, method="GET")
        with urllib.request.urlopen(req, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))

    def _commit_events(self, source: RepoSource) -> Iterable[SemanticEvent]:
        owner, repo = source.repository.split("/", 1)
        q = urllib.parse.urlencode({"sha": source.branch, "per_page": self.max_commits})
        url = f"{self.api_base}/repos/{owner}/{repo}/commits?{q}"
        try:
            payload = self._request_json(url)
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError) as exc:
            yield SemanticEvent.build(
                source="github-observer-error",
                source_ref=source.repository,
                text=f"Observer could not read {source.repository}@{source.branch}: {type(exc).__name__}",
                metadata={"role": source.role, "branch": source.branch, "error_type": type(exc).__name__},
            )
            return

        if not isinstance(payload, list):
            return
        for item in payload:
            if not isinstance(item, dict):
                continue
            sha = str(item.get("sha", ""))
            commit = item.get("commit") or {}
            message = str(commit.get("message", ""))
            author = commit.get("author") or {}
            timestamp = author.get("date")
            html_url = item.get("html_url")
            text = f"repository={source.repository}\nrole={source.role}\nbranch={source.branch}\ncommit={sha}\nmessage={message}"
            yield SemanticEvent.build(
                source="github-commit",
                source_ref=f"{source.repository}@{sha}",
                text=text,
                metadata={
                    "repository": source.repository,
                    "branch": source.branch,
                    "role": source.role,
                    "commit_sha": sha,
                    "commit_time": timestamp,
                    "html_url": html_url,
                    "command_authority": False,
                },
            )

    def poll_once(self, core: JanusSPICore) -> Dict[str, int]:
        inserted = 0
        duplicates = 0
        by_repo: Dict[str, int] = {}
        for source in self.sources:
            count = 0
            for event in self._commit_events(source):
                if core.observe(event):
                    inserted += 1
                    count += 1
                else:
                    duplicates += 1
            by_repo[source.repository] = count
        return {"inserted": inserted, "duplicates": duplicates, "repositories": len(self.sources), **{f"repo:{k}": v for k, v in by_repo.items()}}

    def run_forever(self, core: JanusSPICore, poll_seconds: Optional[int] = None) -> None:
        interval = int(poll_seconds or self.config.get("poll_seconds", 300))
        while True:
            result = self.poll_once(core)
            print(json.dumps({"type": "JANUS_SPI_POLL", "time": time.time(), **result}, ensure_ascii=False))
            time.sleep(max(60, interval))
