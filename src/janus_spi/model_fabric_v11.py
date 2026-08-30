from __future__ import annotations

import urllib.parse
from typing import Any, Dict

from .model_fabric import GitHubRepositoryReader, ModelFabricCompiler


class GitHubRepositoryReaderV11(GitHubRepositoryReader):
    """Model-fabric reader that can resolve each repository's real default branch."""

    def default_branch(self, repository: str) -> str | None:
        owner, name = repository.split("/", 1)
        value = self._request_json(
            f"{self.api_base}/repos/{urllib.parse.quote(owner)}/{urllib.parse.quote(name)}",
            allow_missing=True,
        )
        if not isinstance(value, dict):
            return None
        branch = str(value.get("default_branch") or "").strip()
        return branch or None


class ModelFabricCompilerV11(ModelFabricCompiler):
    """Resolve model membership against the branch each repository actually lives on.

    v1 locked every ecology member against ``main`` because most active JANUS
    organs use it.  Older toolchains and independent instruments legitimately use
    ``master``, ``develop`` or specialized branches.  Those repositories still
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

            # If repository metadata could not be read, preserve the v1 declared
            # branch as a fail-safe rather than manufacturing unavailability.
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
