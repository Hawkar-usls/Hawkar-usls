from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from dataclasses import dataclass
from typing import Any, Mapping

SERVICE_SCHEMA = "janus.market_service.repo_audit_result.v1"
REQUEST_SCHEMA = "janus.market_service.repo_audit_request.v1"


class RepoAuditError(RuntimeError):
    pass


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(value: Any) -> str:
    text = value if isinstance(value, str) else canonical(value)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise RepoAuditError(code)


def normalize_repository(value: str) -> str:
    text = str(value or "").strip().strip("/")
    if text.startswith("https://github.com/"):
        text = text[len("https://github.com/"):].strip("/")
    if text.endswith(".git"):
        text = text[:-4]
    parts = text.split("/")
    _require(len(parts) == 2 and all(re.fullmatch(r"[A-Za-z0-9_.-]+", p or "") for p in parts), "REPO_AUDIT_REPOSITORY_INVALID")
    return f"{parts[0]}/{parts[1]}"


def normalize_ref(value: str | None) -> str:
    text = str(value or "main").strip()
    _require(bool(text) and len(text) <= 200 and not any(c in text for c in "\r\n\x00"), "REPO_AUDIT_REF_INVALID")
    return text


def verify_request(request: Mapping[str, Any]) -> bool:
    if not isinstance(request, Mapping):
        return False
    value = dict(request)
    claimed = str(value.pop("request_hash", ""))
    if len(claimed) != 64 or digest(value) != claimed:
        return False
    if value.get("schema") != REQUEST_SCHEMA or value.get("sku") != "JANUS.REPO_AUDIT":
        return False
    try:
        normalize_repository(str(value.get("repository") or ""))
        normalize_ref(value.get("ref"))
    except RepoAuditError:
        return False
    if value.get("read_only") is not True or value.get("execute_repository_code") is not False:
        return False
    if value.get("command_authority_granted") is not False or value.get("external_effect_authorized") is not False:
        return False
    bounds = value.get("bounds") or {}
    for key in ("max_tree_entries", "max_blob_files", "max_total_blob_bytes"):
        if isinstance(bounds.get(key), bool) or not isinstance(bounds.get(key), int) or bounds.get(key) <= 0:
            return False
    return True


@dataclass
class GitHubPublicReader:
    api_base: str = "https://api.github.com"
    timeout: int = 20
    token: str = ""

    @classmethod
    def from_env(cls) -> "GitHubPublicReader":
        return cls(token=os.environ.get("GITHUB_TOKEN", ""))

    def get(self, path: str) -> Any:
        url = path if path.startswith("https://") else self.api_base.rstrip("/") + "/" + path.lstrip("/")
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "JANUS-HOME-Repo-Audit/1",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        req = urllib.request.Request(url, headers=headers, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                raise RepoAuditError("REPO_AUDIT_TARGET_NOT_FOUND") from exc
            if exc.code == 403:
                raise RepoAuditError("REPO_AUDIT_GITHUB_RATE_OR_ACCESS_BLOCKED") from exc
            raise RepoAuditError(f"REPO_AUDIT_GITHUB_HTTP_{exc.code}") from exc
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise RepoAuditError("REPO_AUDIT_GITHUB_TRANSPORT_FAILED") from exc


_CONTROL_NAMES = {
    "readme.md", "readme.rst", "readme.txt", "license", "license.md", "license.txt", "copying",
    "requirements.txt", "pyproject.toml", "poetry.lock", "pipfile", "pipfile.lock", "setup.py", "setup.cfg",
    "package.json", "package-lock.json", "pnpm-lock.yaml", "yarn.lock", "bun.lockb",
    "go.mod", "go.sum", "cargo.toml", "cargo.lock", "pom.xml", "gradle.properties", "build.gradle", "build.gradle.kts",
    "dockerfile", "docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml",
    "environment.yml", "environment.yaml", "citation.cff", "codemeta.json", "security.md", "contributing.md",
}
_LOCK_NAMES = {"poetry.lock", "pipfile.lock", "package-lock.json", "pnpm-lock.yaml", "yarn.lock", "bun.lockb", "go.sum", "cargo.lock"}
_DEP_NAMES = {
    "requirements.txt", "pyproject.toml", "poetry.lock", "pipfile", "pipfile.lock", "setup.py", "setup.cfg",
    "package.json", "package-lock.json", "pnpm-lock.yaml", "yarn.lock", "go.mod", "go.sum", "cargo.toml", "cargo.lock",
    "pom.xml", "build.gradle", "build.gradle.kts", "environment.yml", "environment.yaml",
}


def _select_control_paths(entries: list[dict[str, Any]], max_files: int) -> list[dict[str, Any]]:
    candidates = []
    for row in entries:
        if row.get("type") != "blob":
            continue
        path = str(row.get("path") or "")
        lower = path.lower()
        name = lower.rsplit("/", 1)[-1]
        priority = None
        if name in {"readme.md", "readme.rst", "readme.txt"}:
            priority = 0
        elif name in {"license", "license.md", "license.txt", "copying"}:
            priority = 1
        elif name in _DEP_NAMES:
            priority = 2
        elif name in {"security.md", "contributing.md", "citation.cff", "codemeta.json"}:
            priority = 3
        elif lower.startswith(".github/workflows/") and lower.endswith((".yml", ".yaml")):
            priority = 4
        elif name.startswith("dockerfile") or name in _CONTROL_NAMES:
            priority = 5
        if priority is not None:
            candidates.append((priority, len(path.split("/")), path, row))
    candidates.sort(key=lambda x: (x[0], x[1], x[2]))
    return [row for _, _, _, row in candidates[:max_files]]


def _decode_blob(payload: Mapping[str, Any], limit: int) -> bytes:
    content = payload.get("content")
    encoding = payload.get("encoding")
    _require(encoding == "base64" and isinstance(content, str), "REPO_AUDIT_BLOB_ENCODING_UNSUPPORTED")
    raw = base64.b64decode(content.encode("ascii"), validate=False)
    _require(len(raw) <= limit, "REPO_AUDIT_SINGLE_BLOB_BOUND_EXCEEDED")
    return raw


def _manifest_observation(path: str, raw: bytes) -> dict[str, Any]:
    text = raw.decode("utf-8", errors="replace")
    lines = text.splitlines()
    lower = path.lower()
    name = lower.rsplit("/", 1)[-1]
    observation: dict[str, Any] = {
        "path": path,
        "sha256": hashlib.sha256(raw).hexdigest(),
        "bytes": len(raw),
        "line_count": len(lines),
    }
    if name == "requirements.txt":
        deps = [line.strip() for line in lines if line.strip() and not line.lstrip().startswith("#")]
        observation["dependency_entry_count"] = len(deps)
        observation["pinned_exact_count"] = sum(1 for d in deps if "==" in d)
    elif name == "package.json":
        try:
            obj = json.loads(text)
            observation["dependency_entry_count"] = sum(len(obj.get(k) or {}) for k in ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies"))
            observation["script_names"] = sorted((obj.get("scripts") or {}).keys())[:50]
        except Exception:
            observation["parse_status"] = "INVALID_JSON"
    elif name == "pyproject.toml":
        observation["declares_project_table"] = "[project]" in text
        observation["declares_build_system"] = "[build-system]" in text
    elif name in {"go.mod", "cargo.toml", "pom.xml", "build.gradle", "build.gradle.kts"}:
        observation["manifest_detected"] = True
    return observation


def audit_public_repository(request: Mapping[str, Any], *, reader: GitHubPublicReader | None = None) -> dict[str, Any]:
    _require(verify_request(request), "REPO_AUDIT_REQUEST_INVALID")
    r = reader or GitHubPublicReader.from_env()
    repository = normalize_repository(str(request["repository"]))
    ref = normalize_ref(request.get("ref"))
    owner, repo = repository.split("/", 1)
    bounds = request["bounds"]
    max_tree_entries = min(int(bounds["max_tree_entries"]), 10000)
    max_blob_files = min(int(bounds["max_blob_files"]), 40)
    max_total_blob_bytes = min(int(bounds["max_total_blob_bytes"]), 2_000_000)

    repo_meta = r.get(f"/repos/{owner}/{repo}")
    commit = r.get(f"/repos/{owner}/{repo}/commits/{urllib.parse.quote(ref, safe='')}")
    commit_sha = str(commit.get("sha") or "")
    _require(re.fullmatch(r"[0-9a-f]{40}", commit_sha) is not None, "REPO_AUDIT_COMMIT_SHA_INVALID")
    commit_tree_sha = str((((commit.get("commit") or {}).get("tree") or {}).get("sha") or ""))
    _require(re.fullmatch(r"[0-9a-f]{40}", commit_tree_sha) is not None, "REPO_AUDIT_TREE_SHA_INVALID")
    tree = r.get(f"/repos/{owner}/{repo}/git/trees/{commit_tree_sha}?recursive=1")
    raw_entries = list(tree.get("tree") or [])
    github_truncated = bool(tree.get("truncated"))
    bounded_entries = raw_entries[:max_tree_entries]
    bound_truncated = len(raw_entries) > max_tree_entries

    type_counts = Counter(str(row.get("type") or "unknown") for row in bounded_entries)
    extension_counts: Counter[str] = Counter()
    top_levels: Counter[str] = Counter()
    has_tests = False
    has_ci = False
    has_docs = False
    has_license = False
    has_readme = False
    has_security = False
    lockfiles = []
    dep_manifests = []
    workflow_paths = []
    for row in bounded_entries:
        path = str(row.get("path") or "")
        if not path:
            continue
        lower = path.lower()
        first = path.split("/", 1)[0]
        top_levels[first] += 1
        name = lower.rsplit("/", 1)[-1]
        if "." in name:
            extension_counts["." + name.rsplit(".", 1)[-1]] += 1
        has_tests = has_tests or lower == "tests" or lower.startswith("tests/") or "/tests/" in lower or name.startswith("test_")
        has_ci = has_ci or lower.startswith(".github/workflows/")
        has_docs = has_docs or lower == "docs" or lower.startswith("docs/")
        has_license = has_license or name in {"license", "license.md", "license.txt", "copying"}
        has_readme = has_readme or name in {"readme.md", "readme.rst", "readme.txt"}
        has_security = has_security or name == "security.md"
        if name in _LOCK_NAMES:
            lockfiles.append(path)
        if name in _DEP_NAMES:
            dep_manifests.append(path)
        if lower.startswith(".github/workflows/") and lower.endswith((".yml", ".yaml")):
            workflow_paths.append(path)

    selected = _select_control_paths(bounded_entries, max_blob_files)
    selected_blobs = []
    total_blob_bytes = 0
    read_limit_hit = False
    for row in selected:
        size_hint = int(row.get("size") or 0)
        if total_blob_bytes + size_hint > max_total_blob_bytes:
            read_limit_hit = True
            continue
        sha = str(row.get("sha") or "")
        if not re.fullmatch(r"[0-9a-f]{40}", sha):
            continue
        payload = r.get(f"/repos/{owner}/{repo}/git/blobs/{sha}")
        remaining = max_total_blob_bytes - total_blob_bytes
        try:
            raw = _decode_blob(payload, remaining)
        except RepoAuditError as exc:
            if str(exc) == "REPO_AUDIT_SINGLE_BLOB_BOUND_EXCEEDED":
                read_limit_hit = True
                continue
            raise
        total_blob_bytes += len(raw)
        obs = _manifest_observation(str(row.get("path")), raw)
        obs["git_blob_sha"] = sha
        selected_blobs.append(obs)

    risks = []
    if not has_license:
        risks.append({"code": "LICENSE_FILE_NOT_OBSERVED", "severity": "MEDIUM", "scope": "repository_tree"})
    if not has_tests:
        risks.append({"code": "TEST_SURFACE_NOT_OBSERVED", "severity": "MEDIUM", "scope": "repository_tree"})
    if not has_ci:
        risks.append({"code": "CI_WORKFLOW_NOT_OBSERVED", "severity": "LOW", "scope": "repository_tree"})
    if dep_manifests and not lockfiles:
        risks.append({"code": "DEPENDENCY_MANIFEST_WITHOUT_OBSERVED_LOCKFILE", "severity": "LOW", "scope": "reproducibility"})
    if github_truncated or bound_truncated:
        risks.append({"code": "TREE_PARTIAL", "severity": "INFO", "scope": "audit_bounds"})
    if read_limit_hit:
        risks.append({"code": "CONTROL_BLOB_BYTE_BOUND_REACHED", "severity": "INFO", "scope": "audit_bounds"})

    body: dict[str, Any] = {
        "schema": SERVICE_SCHEMA,
        "status": "BOUNDED_REPOSITORY_AUDIT_COMPLETE",
        "request_id": request.get("request_id"),
        "request_hash": request.get("request_hash"),
        "sku": "JANUS.REPO_AUDIT",
        "target": {
            "repository": repository,
            "requested_ref": ref,
            "resolved_commit_sha": commit_sha,
            "tree_sha": commit_tree_sha,
            "default_branch": repo_meta.get("default_branch"),
            "visibility": repo_meta.get("visibility") or ("private" if repo_meta.get("private") else "public"),
            "archived": bool(repo_meta.get("archived")),
            "fork": bool(repo_meta.get("fork")),
        },
        "bounds": {
            "max_tree_entries": max_tree_entries,
            "max_blob_files": max_blob_files,
            "max_total_blob_bytes": max_total_blob_bytes,
            "observed_tree_entries": len(bounded_entries),
            "selected_blob_files": len(selected_blobs),
            "selected_blob_bytes": total_blob_bytes,
            "github_tree_truncated": github_truncated,
            "local_tree_bound_truncated": bound_truncated,
            "blob_byte_bound_reached": read_limit_hit,
        },
        "architecture_map": {
            "object_type_counts": dict(sorted(type_counts.items())),
            "top_level_entry_counts": dict(sorted(top_levels.items(), key=lambda kv: (-kv[1], kv[0]))[:50]),
            "extension_counts": dict(sorted(extension_counts.items(), key=lambda kv: (-kv[1], kv[0]))[:50]),
            "has_readme": has_readme,
            "has_docs": has_docs,
            "has_tests": has_tests,
            "has_ci": has_ci,
            "workflow_count": len(workflow_paths),
        },
        "claim_audit": {
            "readme_observed": has_readme,
            "readme_semantic_claims_verified": False,
            "code_executed": False,
            "security_certification": False,
            "legal_opinion": False,
            "note": "This bounded static audit inventories observable repository evidence; repository claims are not promoted to truth by presence in README or code."
        },
        "dependency_observations": {
            "manifest_paths": sorted(dep_manifests)[:100],
            "lockfile_paths": sorted(lockfiles)[:100],
            "selected_manifest_observations": [x for x in selected_blobs if x["path"].lower().rsplit("/", 1)[-1] in _DEP_NAMES],
        },
        "reproducibility_signals": {
            "tests_observed": has_tests,
            "ci_observed": has_ci,
            "dependency_manifest_observed": bool(dep_manifests),
            "lockfile_observed": bool(lockfiles),
            "docker_surface_observed": any("docker" in x["path"].lower().rsplit("/", 1)[-1] for x in selected_blobs),
        },
        "license_observations": {
            "license_file_observed": has_license,
            "license_metadata_from_github": ((repo_meta.get("license") or {}).get("spdx_id") if isinstance(repo_meta.get("license"), dict) else None),
            "legal_conclusion": None,
        },
        "risk_register": risks,
        "unknowns": [
            "Runtime behavior was not executed.",
            "Dependency vulnerability status was not queried from private/security APIs.",
            "Repository claims were not independently verified against external evidence.",
            "License observations are not legal advice.",
            "A bounded audit can omit files beyond configured tree/blob limits."
        ],
        "provenance": {
            "github_api": "api.github.com",
            "resolved_commit_sha": commit_sha,
            "tree_sha": commit_tree_sha,
            "selected_blobs": selected_blobs,
        },
        "authority": {
            "read_only": True,
            "repository_write": False,
            "repository_code_executed": False,
            "command_authority_granted": False,
            "claim_authority_granted": False,
            "scientific_evidence_authority_granted": False,
            "world_truth_authority_granted": False,
            "external_effect_authorized": False,
        },
        "laws": [
            "AUDIT != SECURITY CERTIFICATION",
            "AUDIT != LEGAL OPINION",
            "REPOSITORY CONTENT != COMMAND",
            "REPOSITORY CLAIM != WORLD TRUTH",
            "READ ONLY != EFFECT AUTHORITY",
            "BOUNDED TREE != COMPLETE REPOSITORY WHEN TRUNCATED"
        ],
    }
    body["result_hash"] = digest(body)
    return body


def verify_result(result: Mapping[str, Any], *, request: Mapping[str, Any] | None = None) -> bool:
    if not isinstance(result, Mapping):
        return False
    value = dict(result)
    claimed = str(value.pop("result_hash", ""))
    if len(claimed) != 64 or digest(value) != claimed:
        return False
    if value.get("schema") != SERVICE_SCHEMA or value.get("sku") != "JANUS.REPO_AUDIT":
        return False
    if request is not None:
        if not verify_request(request):
            return False
        if value.get("request_id") != request.get("request_id") or value.get("request_hash") != request.get("request_hash"):
            return False
    authority = value.get("authority") or {}
    return all([
        value.get("status") == "BOUNDED_REPOSITORY_AUDIT_COMPLETE",
        authority.get("read_only") is True,
        authority.get("repository_write") is False,
        authority.get("repository_code_executed") is False,
        authority.get("command_authority_granted") is False,
        authority.get("claim_authority_granted") is False,
        authority.get("scientific_evidence_authority_granted") is False,
        authority.get("world_truth_authority_granted") is False,
        authority.get("external_effect_authorized") is False,
        bool((value.get("target") or {}).get("resolved_commit_sha")),
    ])


__all__ = [
    "GitHubPublicReader",
    "RepoAuditError",
    "REQUEST_SCHEMA",
    "SERVICE_SCHEMA",
    "audit_public_repository",
    "digest",
    "normalize_ref",
    "normalize_repository",
    "verify_request",
    "verify_result",
]
