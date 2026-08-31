from __future__ import annotations

import re
import subprocess
import urllib.parse
from typing import Any, Dict

from .model_fabric import GitHubRepositoryReader, ModelFabricCompiler


_REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_BRANCH_RE = re.compile(r"^[A-Za-z0-9._/-]+$")
_SHA40_RE = re.compile(r"^[0-9a-f]{40}$")


class GitHubRepositoryReaderV11(GitHubRepositoryReader):
    """Model-fabric reader that resolves repository refs without burning REST quota.

    A full JANUS boot touches dozens of repository HEADs. Resolving each HEAD and
    default branch through REST can exhaust an unauthenticated runner's rate budget
    before required persistent-state mounts are checked. Public Git refs are
    therefore resolved through read-only ``git ls-remote`` first. JSON descriptor
    content continues to use the GitHub Contents API. If Git transport is
    unavailable, the original REST implementation remains a bounded fallback.
    """

    def __init__(self, *args: Any, git_runner: Any | None = None, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._git_runner = git_runner or subprocess.run
        self._git_default_cache: Dict[str, str | None] = {}
        self._git_head_cache: Dict[tuple[str, str], str | None] = {}

    @staticmethod
    def _remote_url(repository: str) -> str:
        if not _REPOSITORY_RE.fullmatch(repository):
            raise ValueError("GIT_REPOSITORY_NAME_INVALID")
        return f"https://github.com/{repository}.git"

    @staticmethod
    def _validate_branch(branch: str) -> str:
        value = str(branch or "").strip()
        invalid = (
            not value
            or not _BRANCH_RE.fullmatch(value)
            or value.startswith("/")
            or value.endswith("/")
            or ".." in value
            or "//" in value
            or "@{" in value
            or value.endswith(".lock")
        )
        if invalid:
            raise ValueError("GIT_BRANCH_NAME_INVALID")
        return value

    def _ls_remote(self, repository: str, *args: str) -> str | None:
        url = self._remote_url(repository)
        options = [arg for arg in args if str(arg).startswith("-")]
        patterns = [arg for arg in args if not str(arg).startswith("-")]
        try:
            result = self._git_runner(
                ["git", "ls-remote", *options, url, *patterns],
                capture_output=True,
                text=True,
                timeout=20,
                check=False,
            )
        except (OSError, subprocess.SubprocessError, TimeoutError):
            return None
        if getattr(result, "returncode", 1) != 0:
            return None
        return str(getattr(result, "stdout", "") or "")

    def default_branch(self, repository: str) -> str | None:
        if repository in self._git_default_cache:
            return self._git_default_cache[repository]
        output = self._ls_remote(repository, "--symref")
        if output:
            for line in output.splitlines():
                if not line.startswith("ref: refs/heads/") or not line.endswith("\tHEAD"):
                    continue
                branch = line[len("ref: refs/heads/") : -len("\tHEAD")]
                try:
                    branch = self._validate_branch(branch)
                except ValueError:
                    break
                self._git_default_cache[repository] = branch
                return branch
        owner, name = repository.split("/", 1)
        value = self._request_json(
            f"{self.api_base}/repos/{urllib.parse.quote(owner)}/{urllib.parse.quote(name)}",
            allow_missing=True,
        )
        if not isinstance(value, dict):
            self._git_default_cache[repository] = None
            return None
        branch = str(value.get("default_branch") or "").strip()
        if branch:
            try:
                branch = self._validate_branch(branch)
            except ValueError:
                branch = ""
        resolved = branch or None
        self._git_default_cache[repository] = resolved
        return resolved

    def branch_head(self, repository: str, branch: str = "main") -> str | None:
        branch = self._validate_branch(branch)
        key = (repository, branch)
        if key in self._git_head_cache:
            return self._git_head_cache[key]
        output = self._ls_remote(repository, f"refs/heads/{branch}")
        if output:
            for line in output.splitlines():
                fields = line.strip().split("\t", 1)
                if len(fields) != 2 or fields[1] != f"refs/heads/{branch}":
                    continue
                sha = fields[0].lower()
                if _SHA40_RE.fullmatch(sha):
                    self._git_head_cache[key] = sha
                    return sha
        head = super().branch_head(repository, branch)
        self._git_head_cache[key] = head
        return head


class ModelFabricCompilerV11(ModelFabricCompiler):
    """Resolve model membership against the branch each repository actually lives on.

    v1 locked every ecology member against ``main`` because most active JANUS
    organs use it. Older toolchains and independent instruments legitimately use
    ``master``, ``develop`` or specialized branches. Those repositories still
    belong to JANUS ecology, so v1.1 resolves their real default branch rather
    than misclassifying them as unavailable.

    The bootstrap root remains explicitly pinned to the branch declared by the
    HOME manifest. Persistent-state mounts remain explicitly pinned by their own
    contracts and are handled by the base compiler.
    """

    @staticmethod
    def _uses_declared_branch(row: Dict[str, Any]) -> bool:
        return row.get("kind") == "BOOTSTRAP_ROOT"

    def _resolve_heads(self, entries: Dict[str, Dict[str, Any]]) -> tuple[list[str], list[str]]:
        required_missing: list[str] = []
        optional_unavailable: list[str] = []
        head_cache: Dict[tuple[str, str], str | None] = {}
        default_cache: Dict[str, str | None] = {}

        for key, row in entries.items():
            repo = row.get("repository")
            if not repo:
                row["head_status"] = "PRIVATE_OR_UNBOUND_SLOT"
                row["head_sha"] = None
                row["resolved_branch"] = None
                continue

            repository = str(repo)
            declared_branch = str(row.get("branch") or "main")
            resolved_branch = declared_branch
            resolution = "DECLARED_BRANCH"

            if not self._uses_declared_branch(row):
                try:
                    if repository not in default_cache:
                        resolver = getattr(self.reader, "default_branch", None)
                        default_cache[repository] = resolver(repository) if callable(resolver) else None
                    default_branch = default_cache[repository]
                except Exception as exc:
                    default_branch = None
                    row["default_branch_error"] = type(exc).__name__
                if default_branch:
                    resolved_branch = str(default_branch)
                    resolution = "REPOSITORY_DEFAULT_BRANCH"

            cache_key = (repository, resolved_branch)
            try:
                if cache_key not in head_cache:
                    head_cache[cache_key] = self.reader.branch_head(repository, resolved_branch)
                head = head_cache[cache_key]
            except Exception as exc:
                head = None
                row["head_error"] = type(exc).__name__

            if not head and resolved_branch != declared_branch:
                fallback_key = (repository, declared_branch)
                try:
                    if fallback_key not in head_cache:
                        head_cache[fallback_key] = self.reader.branch_head(repository, declared_branch)
                    fallback_head = head_cache[fallback_key]
                except Exception:
                    fallback_head = None
                if fallback_head:
                    head = fallback_head
                    resolved_branch = declared_branch
                    resolution = "DECLARED_BRANCH_FALLBACK"

            row["declared_branch"] = declared_branch
            row["branch"] = resolved_branch
            row["resolved_branch"] = resolved_branch
            row["branch_resolution"] = resolution
            row["head_sha"] = head
            if head:
                row["head_status"] = "LOCKED"
            elif row.get("required"):
                row["head_status"] = "REQUIRED_MISSING"
                required_missing.append(key)
            else:
                row["head_status"] = "OPTIONAL_UNAVAILABLE"
                optional_unavailable.append(key)

        return required_missing, optional_unavailable


__all__ = ["GitHubRepositoryReaderV11", "ModelFabricCompilerV11"]
