from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path
from typing import Any, Callable, Dict, Mapping

from .activator import canonical_hash


class FileFabricError(RuntimeError):
    pass


class GitHubTreeReader:
    """Read exact Git trees without granting any execution or write authority."""

    def __init__(
        self,
        *,
        token: str | None = None,
        api_base: str = "https://api.github.com",
        opener: Callable[..., Any] = urllib.request.urlopen,
    ) -> None:
        self.token = token if token is not None else os.environ.get("GITHUB_TOKEN")
        self.api_base = api_base.rstrip("/")
        self.opener = opener

    def _get_json(self, url: str, *, token: str | None) -> Any:
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "JANUS-File-Fabric/1.0",
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"
        request = urllib.request.Request(url, headers=headers)
        response = self.opener(request, timeout=30.0)
        return json.loads(response.read().decode("utf-8"))

    def recursive_tree(self, repository: str, sha: str) -> Dict[str, Any] | None:
        if len(str(sha)) != 40:
            raise FileFabricError("EXACT_SHA40_REQUIRED")
        owner, name = repository.split("/", 1)
        url = (
            f"{self.api_base}/repos/{urllib.parse.quote(owner)}/{urllib.parse.quote(name)}"
            f"/git/trees/{urllib.parse.quote(str(sha), safe='')}?recursive=1"
        )
        try:
            value = self._get_json(url, token=self.token)
        except urllib.error.HTTPError as exc:
            # A HOME installation token can be narrower than the public GitHub
            # visibility boundary. Public-read fallback never grants write power.
            if self.token and exc.code in {403, 404}:
                try:
                    value = self._get_json(url, token=None)
                except urllib.error.HTTPError as public_exc:
                    if public_exc.code == 404:
                        return None
                    raise FileFabricError(f"GITHUB_TREE_HTTP_{public_exc.code}:{repository}@{sha}") from public_exc
            elif exc.code == 404:
                return None
            else:
                raise FileFabricError(f"GITHUB_TREE_HTTP_{exc.code}:{repository}@{sha}") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise FileFabricError(f"GITHUB_TREE_UNAVAILABLE:{repository}@{sha}:{type(exc).__name__}") from exc
        if not isinstance(value, dict) or not isinstance(value.get("tree"), list):
            raise FileFabricError(f"GITHUB_TREE_MALFORMED:{repository}@{sha}")
        return value


class FileFabricCompiler:
    def __init__(self, registry: Mapping[str, Any], *, reader: Any) -> None:
        self.registry = dict(registry)
        self.reader = reader
        self._validate_registry()

    @classmethod
    def from_file(cls, path: str | Path, *, reader: Any | None = None) -> "FileFabricCompiler":
        value = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise FileFabricError("FILE_FORMAT_REGISTRY_NOT_OBJECT")
        return cls(value, reader=reader or GitHubTreeReader())

    def _validate_registry(self) -> None:
        if self.registry.get("schema") != "janus.file_format_registry.v1":
            raise FileFabricError("FILE_FORMAT_REGISTRY_SCHEMA_MISMATCH")
        formats = self.registry.get("formats")
        if not isinstance(formats, dict) or not formats:
            raise FileFabricError("FILE_FORMAT_REGISTRY_EMPTY")
        required = {
            ".json", ".py", ".js", ".mjs", ".html", ".c", ".cpp", ".cc", ".cxx",
            ".h", ".hpp", ".sh", ".ps1", ".bat", ".cmd", ".yml", ".yaml", ".vce",
        }
        if not required.issubset(formats):
            raise FileFabricError("CANONICAL_FORMAT_SET_INCOMPLETE")
        for ext, row in formats.items():
            if not str(ext).startswith(".") or not isinstance(row, dict):
                raise FileFabricError("INVALID_FORMAT_REGISTRY_ROW")
            if row.get("default_execution_authorized") is not False:
                raise FileFabricError(f"FORMAT_MUST_NOT_GRANT_DEFAULT_EXECUTION:{ext}")
        vce = formats[".vce"]
        if vce.get("family") != "CUSTOM" or vce.get("adapter") is not None:
            raise FileFabricError("VCE_MUST_REMAIN_CUSTOM_WITHOUT_GUESSED_ADAPTER")

    @staticmethod
    def _extension(path: str) -> str:
        name = Path(path).name
        if name.startswith(".") and name.count(".") == 1:
            return ""
        return Path(name).suffix.lower()

    def _classify_tree(self, value: Mapping[str, Any]) -> Dict[str, Any]:
        canonical = self.registry["formats"]
        observed = self.registry.get("observed_nonexecuting_formats") or {}
        extensions: Counter[str] = Counter()
        families: Counter[str] = Counter()
        unknown: Counter[str] = Counter()
        canonical_files = 0
        observed_files = 0
        total_files = 0
        custom_files = 0

        for item in value.get("tree", []):
            if not isinstance(item, dict) or item.get("type") != "blob":
                continue
            total_files += 1
            ext = self._extension(str(item.get("path") or ""))
            if not ext:
                unknown["<no_extension>"] += 1
                continue
            extensions[ext] += 1
            if ext in canonical:
                row = canonical[ext]
                families[str(row.get("family") or "UNKNOWN")] += 1
                canonical_files += 1
                if row.get("family") == "CUSTOM":
                    custom_files += 1
            elif ext in observed:
                families["OBSERVED_NONEXECUTING"] += 1
                observed_files += 1
            else:
                unknown[ext] += 1

        return {
            "total_files": total_files,
            "canonical_tissue_files": canonical_files,
            "observed_nonexecuting_files": observed_files,
            "custom_tissue_files": custom_files,
            "extension_counts": dict(sorted(extensions.items())),
            "family_counts": dict(sorted(families.items())),
            "unknown_extension_counts": dict(sorted(unknown.items())),
            "tree_truncated": bool(value.get("truncated")),
        }

    def compile(self, model_lock: Mapping[str, Any]) -> Dict[str, Any]:
        if not isinstance(model_lock, Mapping):
            raise FileFabricError("MODEL_LOCK_NOT_OBJECT")
        if model_lock.get("ready") is not True:
            raise FileFabricError("MODEL_LOCK_MUST_BE_READY_BEFORE_FILE_FABRIC")
        model_digest = str(model_lock.get("model_digest") or "")
        if len(model_digest) != 64:
            raise FileFabricError("MODEL_DIGEST_REQUIRED")
        members = model_lock.get("members")
        if not isinstance(members, dict) or not members:
            raise FileFabricError("MODEL_LOCK_MEMBERS_REQUIRED")

        member_tissues: Dict[str, Any] = {}
        extension_totals: Counter[str] = Counter()
        family_totals: Counter[str] = Counter()
        required_failures: list[str] = []
        bounded_unknown: list[str] = []
        scanned = 0

        for key, member in sorted(members.items()):
            if not isinstance(member, dict):
                continue
            repo = member.get("repository")
            sha = member.get("head_sha")
            required = bool(member.get("required"))
            base = {
                "member_key": key,
                "kind": member.get("kind"),
                "repository": repo,
                "locked_head_sha": sha,
                "required": required,
                "load_mode": member.get("load_mode"),
                "execution_authority_granted": False,
                "external_effect_authorized": False,
                "physical_runtime_effect_authorized": False,
            }
            if not repo or not sha:
                base["scan_status"] = "NOT_RESOLVABLE_FROM_MODEL_LOCK"
                member_tissues[key] = base
                continue
            try:
                tree = self.reader.recursive_tree(str(repo), str(sha))
            except Exception as exc:
                tree = None
                base["scan_error"] = type(exc).__name__
            if tree is None:
                base["scan_status"] = "REQUIRED_TREE_UNAVAILABLE" if required else "OPTIONAL_TREE_UNAVAILABLE"
                if required:
                    required_failures.append(key)
                else:
                    bounded_unknown.append(key)
                member_tissues[key] = base
                continue

            scan = self._classify_tree(tree)
            scanned += 1
            base.update(scan)
            if scan["tree_truncated"]:
                base["scan_status"] = "UNKNOWN_RESOURCE_LIMIT"
                bounded_unknown.append(key)
                if required:
                    required_failures.append(key)
            else:
                base["scan_status"] = "EXACT_SHA_TREE_CLASSIFIED"
            member_tissues[key] = base
            extension_totals.update(scan["extension_counts"])
            family_totals.update(scan["family_counts"])

        ready = not required_failures
        coverage_complete = ready and not bounded_unknown
        terminal = (
            "JANUS_POLYGLOT_FILE_FABRIC_LOCKED"
            if coverage_complete
            else "JANUS_POLYGLOT_FILE_FABRIC_LOCKED_WITH_BOUNDED_UNKNOWN"
            if ready
            else "JANUS_POLYGLOT_FILE_FABRIC_FAIL_CLOSED"
        )
        result = {
            "schema": "janus.file_fabric_lock.v1",
            "model_id": "JANUS",
            "model_digest": model_digest,
            "model_lock_hash": canonical_hash(dict(model_lock)),
            "registry_hash": canonical_hash(self.registry),
            "member_count": len(members),
            "scanned_member_count": scanned,
            "member_tissues": member_tissues,
            "extension_totals": dict(sorted(extension_totals.items())),
            "family_totals": dict(sorted(family_totals.items())),
            "required_failures": sorted(set(required_failures)),
            "bounded_unknown": sorted(set(bounded_unknown)),
            "ready": ready,
            "coverage_complete": coverage_complete,
            "execution_authority_granted": False,
            "command_authority_granted": False,
            "claim_authority_granted": False,
            "scientific_evidence_authority_granted": False,
            "external_effect_authorized": False,
            "physical_runtime_effect_authorized": False,
            "terminal": terminal,
            "laws": [
                "FILE_EXTENSION != EXECUTION_AUTHORITY",
                "DISCOVERY != ADMISSION",
                "ADMISSION != EXECUTION",
                "ARBITRARY_EVAL_EXEC_IS_FORBIDDEN",
                "PHYSICAL_EDGE_SOURCE_INSIDE_GITHUB != PHYSICAL_RUNTIME_EXECUTION",
            ],
        }
        result["file_fabric_digest"] = canonical_hash(result)
        return result


__all__ = ["FileFabricCompiler", "FileFabricError", "GitHubTreeReader"]
