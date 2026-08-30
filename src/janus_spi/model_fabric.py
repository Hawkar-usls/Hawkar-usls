from __future__ import annotations

import base64
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Mapping, Optional

from .activator import canonical_hash


class ModelFabricError(RuntimeError):
    pass


class GitHubRepositoryReader:
    """Minimal read-only GitHub reader used by the JANUS model loader.

    The loader never writes across repositories. Public repositories can be read
    without a token; GitHub Actions may provide GITHUB_TOKEN for a larger rate
    budget. The token is never persisted into the model lock.
    """

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

    def _request_json(self, url: str, *, allow_missing: bool = False) -> Any:
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "JANUS-Model-Fabric/1.0",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        request = urllib.request.Request(url, headers=headers)
        try:
            response = self.opener(request, timeout=20.0)
            return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if allow_missing and exc.code == 404:
                return None
            raise ModelFabricError(f"GITHUB_HTTP_{exc.code}:{url}") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise ModelFabricError(f"GITHUB_READ_UNAVAILABLE:{url}:{type(exc).__name__}") from exc

    def branch_head(self, repository: str, branch: str = "main") -> str | None:
        owner, name = repository.split("/", 1)
        ref = urllib.parse.quote(branch, safe="")
        value = self._request_json(
            f"{self.api_base}/repos/{urllib.parse.quote(owner)}/{urllib.parse.quote(name)}/branches/{ref}",
            allow_missing=True,
        )
        if value is None:
            return None
        sha = str(((value or {}).get("commit") or {}).get("sha") or "")
        return sha if len(sha) == 40 else None

    def json_file(
        self,
        repository: str,
        path: str,
        *,
        ref: str = "main",
        allow_missing: bool = False,
    ) -> Dict[str, Any] | None:
        owner, name = repository.split("/", 1)
        encoded_path = "/".join(urllib.parse.quote(part, safe="") for part in path.split("/"))
        url = (
            f"{self.api_base}/repos/{urllib.parse.quote(owner)}/{urllib.parse.quote(name)}"
            f"/contents/{encoded_path}?ref={urllib.parse.quote(ref, safe='')}"
        )
        value = self._request_json(url, allow_missing=allow_missing)
        if value is None:
            return None
        if not isinstance(value, dict) or value.get("encoding") != "base64":
            raise ModelFabricError(f"GITHUB_CONTENT_NOT_BASE64:{repository}:{path}@{ref}")
        try:
            raw = base64.b64decode(str(value.get("content") or ""), validate=False)
            parsed = json.loads(raw.decode("utf-8"))
        except Exception as exc:
            raise ModelFabricError(f"JSON_DECODE_FAILED:{repository}:{path}@{ref}") from exc
        if not isinstance(parsed, dict):
            raise ModelFabricError(f"JSON_OBJECT_REQUIRED:{repository}:{path}@{ref}")
        return parsed


class ModelFabricCompiler:
    def __init__(
        self,
        manifest: Mapping[str, Any],
        *,
        reader: Any,
        now_fn: Callable[[], float] = time.time,
    ) -> None:
        self.manifest = dict(manifest)
        self.reader = reader
        self.now_fn = now_fn
        self._validate_manifest()

    @classmethod
    def from_file(
        cls,
        path: str | Path,
        *,
        reader: Any | None = None,
        now_fn: Callable[[], float] = time.time,
    ) -> "ModelFabricCompiler":
        manifest = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(manifest, dict):
            raise ModelFabricError("MODEL_MANIFEST_NOT_OBJECT")
        return cls(manifest, reader=reader or GitHubRepositoryReader(), now_fn=now_fn)

    def _validate_manifest(self) -> None:
        if self.manifest.get("schema") != "janus.activator.model_manifest.v1":
            raise ModelFabricError("MODEL_MANIFEST_SCHEMA_MISMATCH")
        if self.manifest.get("model_id") != "JANUS":
            raise ModelFabricError("MODEL_ID_MUST_BE_JANUS")
        if self.manifest.get("model_loading", {}).get("routing_selects") != "ACTIVITY_NOT_MEMBERSHIP":
            raise ModelFabricError("ROUTING_MUST_SELECT_ACTIVITY_NOT_MEMBERSHIP")
        if self.manifest.get("bootstrap_root", {}).get("external_effect_authority") is not False:
            raise ModelFabricError("BOOTSTRAP_ROOT_MUST_NOT_GAIN_EXTERNAL_EFFECT_AUTHORITY")

    def _load_topology(self) -> tuple[Dict[str, Dict[str, Any]], Dict[str, str]]:
        config = self.manifest["canonical_topology"]
        repository = str(config["repository"])
        branch = str(config.get("branch") or "main")
        loaded: Dict[str, Dict[str, Any]] = {}
        hashes: Dict[str, str] = {}
        for source in config.get("sources", []):
            key = str(source["key"])
            path = str(source["path"])
            try:
                value = self.reader.json_file(repository, path, ref=branch, allow_missing=not bool(source.get("required")))
            except Exception as exc:
                if source.get("required"):
                    raise ModelFabricError(f"REQUIRED_TOPOLOGY_SOURCE_UNAVAILABLE:{key}:{type(exc).__name__}") from exc
                continue
            if value is None:
                if source.get("required"):
                    raise ModelFabricError(f"REQUIRED_TOPOLOGY_SOURCE_MISSING:{key}")
                continue
            loaded[key] = value
            hashes[key] = canonical_hash(value)
        required_keys = {str(x["key"]) for x in config.get("sources", []) if x.get("required")}
        if not required_keys.issubset(loaded):
            raise ModelFabricError("REQUIRED_TOPOLOGY_SET_INCOMPLETE")
        return loaded, hashes

    def _load_mode(self, member_class: str) -> str:
        return str(self.manifest.get("load_policy", {}).get(member_class, "REFERENCE_ONLY"))

    @staticmethod
    def _entry_key(prefix: str, key: str) -> str:
        return key if prefix == "organ" else f"{prefix}:{key}"

    def _compile_members(self, topology: Mapping[str, Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
        organism = topology["organism"]
        ecology = topology["ecology_baseline"]
        ecology_delta = topology["ecology_delta"]
        entries: Dict[str, Dict[str, Any]] = {}
        seen_repos: Dict[str, str] = {}

        root = dict(self.manifest["bootstrap_root"])
        entries["bootstrap_root"] = {
            "key": "bootstrap_root",
            "kind": "BOOTSTRAP_ROOT",
            "repository": root["repository"],
            "branch": root.get("branch", "main"),
            "member_class": "BOOTSTRAP_ROOT",
            "role": root["role"],
            "authority": root["authority"],
            "evidence_authority": False,
            "required": True,
            "load_mode": "REQUIRED_BOOT_PRESENCE",
            "consumes": [],
            "emits": ["MODEL_LOCK", "ACTIVATION_RECEIPT"],
            "source": "LOCAL_BOOTSTRAP_MANIFEST",
        }
        seen_repos[str(root["repository"])] = "bootstrap_root"

        def add_entry(key: str, entry: Dict[str, Any], *, allow_repo_duplicate: bool = False) -> None:
            if key in entries:
                raise ModelFabricError(f"DUPLICATE_MODEL_MEMBER_KEY:{key}")
            repo = entry.get("repository")
            if repo and repo in seen_repos and not allow_repo_duplicate:
                # HOME appears in historical ecology as PROFILE_NAVIGATION; the
                # bootstrap-root identity supersedes that non-organ duplicate.
                if entry.get("kind") == "PROFILE_NAVIGATION" and repo == root["repository"]:
                    return
                raise ModelFabricError(f"DUPLICATE_MODEL_MEMBER_REPOSITORY:{repo}:{seen_repos[repo]}:{key}")
            entries[key] = entry
            if repo:
                seen_repos[str(repo)] = key

        for key, row in (organism.get("members") or {}).items():
            if not isinstance(row, dict):
                continue
            repo = row.get("repo")
            member_class = str(row.get("class") or "CORE")
            entry = {
                "key": str(key),
                "kind": "ORGAN",
                "repository": repo,
                "branch": "main",
                "member_class": member_class,
                "role": row.get("role"),
                "authority": row.get("authority"),
                "evidence_authority": bool(row.get("evidence_authority", False)),
                "required": member_class == "CORE" and bool(repo),
                "load_mode": self._load_mode(member_class),
                "consumes": list(row.get("consumes") or []),
                "emits": list(row.get("emits") or []),
                "source": "JANUS_ORGANISM_v1",
                "private_locator_env": row.get("private_locator_env"),
            }
            add_entry(str(key), entry)

        promoted_repos = {str(x.get("repository")) for x in self.manifest.get("promoted_organs", []) if x.get("repository")}
        promotion = ecology_delta.get("promotion") if isinstance(ecology_delta.get("promotion"), dict) else None
        if promotion and promotion.get("repository"):
            promoted_repos.add(str(promotion["repository"]))

        for row in self.manifest.get("promoted_organs", []):
            key = str(row["organ_key"])
            if key in entries:
                continue
            add_entry(key, {
                "key": key,
                "kind": "ORGAN",
                "repository": row["repository"],
                "branch": "main",
                "member_class": row["class"],
                "role": row["role"],
                "authority": "DECLARED_BY_ORGAN_LINK",
                "evidence_authority": False,
                "required": False,
                "load_mode": row.get("load_mode", self._load_mode(str(row["class"]))),
                "consumes": [],
                "emits": [],
                "source": "MODEL_MANIFEST_PROMOTION_OVERLAY",
                "organ_link": row.get("organ_link", ".janus/JANUS_ORGANISM_LINK.json"),
            })

        sections = (
            ("public_subtissues", "SUBTISSUE", "subtissue"),
            ("private_subtissues", "PRIVATE_SUBTISSUE", "private_subtissue"),
            ("legacy_archives", "LEGACY_ARCHIVE", "legacy"),
            ("toolchain_dependencies", "TOOLCHAIN_DEPENDENCY", "toolchain"),
            ("external_research_instruments", "EXTERNAL_RESEARCH_INSTRUMENT", "external"),
        )
        for section, default_class, prefix in sections:
            for key, row in (ecology.get(section) or {}).items():
                if not isinstance(row, dict):
                    continue
                repo = row.get("repo")
                if repo and str(repo) in promoted_repos:
                    continue
                member_class = str(row.get("class") or default_class)
                add_entry(self._entry_key(prefix, str(key)), {
                    "key": self._entry_key(prefix, str(key)),
                    "kind": member_class,
                    "repository": repo,
                    "branch": "main",
                    "member_class": member_class,
                    "role": row.get("role") or row.get("former_scope") or member_class,
                    "authority": row.get("authority") or "NO_INHERITED_AUTHORITY",
                    "evidence_authority": False,
                    "required": False,
                    "load_mode": self._load_mode(member_class),
                    "consumes": list(row.get("consumes") or []),
                    "emits": list(row.get("emits") or []),
                    "parent_organ": row.get("parent_organ"),
                    "source": f"REPOSITORY_ECOLOGY:{section}",
                    "locator_env": row.get("locator_env"),
                })

        profile = ecology.get("profile_navigation")
        if isinstance(profile, dict) and profile.get("repo"):
            add_entry("profile_navigation", {
                "key": "profile_navigation",
                "kind": "PROFILE_NAVIGATION",
                "repository": profile["repo"],
                "branch": "main",
                "member_class": "PROFILE_NAVIGATION",
                "role": "PROFILE_NAVIGATION",
                "authority": "NONE",
                "evidence_authority": False,
                "required": False,
                "load_mode": self._load_mode("PROFILE_NAVIGATION"),
                "consumes": [],
                "emits": [],
                "source": "REPOSITORY_ECOLOGY:profile_navigation",
            })

        for key, row in (organism.get("external_dependencies") or {}).items():
            if not isinstance(row, dict) or not row.get("repo"):
                continue
            repo = str(row["repo"])
            if repo in seen_repos:
                continue
            member_class = str(row.get("classification") or "EXTERNAL_RESEARCH_INSTRUMENT")
            add_entry(self._entry_key("external", str(key)), {
                "key": self._entry_key("external", str(key)),
                "kind": member_class,
                "repository": repo,
                "branch": "main",
                "member_class": member_class,
                "role": row.get("reason") or member_class,
                "authority": "INDEPENDENT_PROVENANCE_ONLY",
                "evidence_authority": False,
                "required": False,
                "load_mode": self._load_mode(member_class),
                "consumes": [],
                "emits": [],
                "source": "JANUS_ORGANISM:external_dependencies",
            })
        return entries

    def _resolve_heads(self, entries: Dict[str, Dict[str, Any]]) -> tuple[list[str], list[str]]:
        required_missing: list[str] = []
        optional_unavailable: list[str] = []
        cache: Dict[tuple[str, str], str | None] = {}
        for key, row in entries.items():
            repo = row.get("repository")
            if not repo:
                row["head_status"] = "PRIVATE_OR_UNBOUND_SLOT"
                row["head_sha"] = None
                continue
            branch = str(row.get("branch") or "main")
            cache_key = (str(repo), branch)
            try:
                if cache_key not in cache:
                    cache[cache_key] = self.reader.branch_head(str(repo), branch)
                head = cache[cache_key]
            except Exception as exc:
                head = None
                row["head_error"] = type(exc).__name__
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

    def _verify_organ_descriptors(self, entries: Dict[str, Dict[str, Any]]) -> list[str]:
        conflicts: list[str] = []
        policy = self.manifest.get("organ_descriptor_policy", {})
        path_default = str(policy.get("preferred_path") or ".janus/JANUS_ORGANISM_LINK.json")
        for key, row in entries.items():
            if row.get("kind") != "ORGAN" or not row.get("repository") or not row.get("head_sha"):
                continue
            path = str(row.get("organ_link") or path_default)
            try:
                descriptor = self.reader.json_file(
                    str(row["repository"]), path, ref=str(row.get("branch") or "main"), allow_missing=True
                )
            except Exception as exc:
                descriptor = None
                row["descriptor_error"] = type(exc).__name__
            if descriptor is None:
                row["descriptor_status"] = "CENTRAL_MANIFEST_FALLBACK"
                continue
            mismatch = []
            if descriptor.get("organism_id") != "JANUS_FEDERATED_ORGANISM":
                mismatch.append("organism_id")
            if descriptor.get("member_repository") not in {None, row["repository"]}:
                mismatch.append("member_repository")
            if descriptor.get("organ_key") not in {None, key}:
                mismatch.append("organ_key")
            if mismatch:
                row["descriptor_status"] = "CONFLICT"
                row["descriptor_conflicts"] = mismatch
                if row.get("required"):
                    conflicts.append(key)
                continue
            row["descriptor_status"] = "SELF_DECLARED"
            row["descriptor_hash"] = canonical_hash(descriptor)
            if descriptor.get("role"):
                row["self_declared_role"] = descriptor["role"]
            if descriptor.get("consumes"):
                row["consumes"] = list(descriptor["consumes"])
            if descriptor.get("emits"):
                row["emits"] = list(descriptor["emits"])
            if descriptor.get("routes_to"):
                row["routes_to"] = list(descriptor["routes_to"])
            row["self_declared_authority"] = descriptor.get("authority")
            row["self_declared_evidence_authority"] = descriptor.get("evidence_authority")
        return conflicts

    @staticmethod
    def _capability_index(entries: Mapping[str, Dict[str, Any]]) -> Dict[str, Dict[str, list[str]]]:
        emitters: Dict[str, list[str]] = {}
        consumers: Dict[str, list[str]] = {}
        for key, row in entries.items():
            if row.get("kind") != "ORGAN":
                continue
            for payload in row.get("emits") or []:
                emitters.setdefault(str(payload), []).append(key)
            for payload in row.get("consumes") or []:
                consumers.setdefault(str(payload), []).append(key)
        for table in (emitters, consumers):
            for payload in table:
                table[payload] = sorted(set(table[payload]))
        return {"emitters": dict(sorted(emitters.items())), "consumers": dict(sorted(consumers.items()))}

    def _resolve_state_mounts(self) -> tuple[Dict[str, Dict[str, Any]], list[str]]:
        mounts: Dict[str, Dict[str, Any]] = {}
        missing: list[str] = []
        for row in self.manifest.get("persistent_state_mounts", []):
            key = str(row["key"])
            repo = str(row["repository"])
            branch = str(row["branch"])
            try:
                head = self.reader.branch_head(repo, branch)
            except Exception as exc:
                head = None
                error = type(exc).__name__
            else:
                error = None
            mounts[key] = {
                "repository": repo,
                "branch": branch,
                "role": row["role"],
                "required": bool(row.get("required")),
                "head_sha": head,
                "status": "LOCKED" if head else "UNAVAILABLE",
            }
            if error:
                mounts[key]["error"] = error
            if row.get("required") and not head:
                missing.append(key)
        return mounts, missing

    def compile(self) -> Dict[str, Any]:
        topology, topology_hashes = self._load_topology()
        entries = self._compile_members(topology)
        required_missing, optional_unavailable = self._resolve_heads(entries)
        descriptor_conflicts = self._verify_organ_descriptors(entries)
        state_mounts, missing_state_mounts = self._resolve_state_mounts()

        memory_repo = str(self.manifest["memory_database"]["repository"])
        memory_member = next((row for row in entries.values() if row.get("repository") == memory_repo), None)
        if memory_member is None or not memory_member.get("head_sha"):
            required_missing.append("memory_database")

        capability_index = self._capability_index(entries)
        required_missing = sorted(set(required_missing))
        descriptor_conflicts = sorted(set(descriptor_conflicts))
        missing_state_mounts = sorted(set(missing_state_mounts))
        failures = {
            "required_members_missing": required_missing,
            "required_descriptor_conflicts": descriptor_conflicts,
            "required_state_mounts_missing": missing_state_mounts,
        }
        fail_closed = any(failures.values())

        members_for_digest = {
            key: {
                "kind": row.get("kind"),
                "repository": row.get("repository"),
                "branch": row.get("branch"),
                "head_sha": row.get("head_sha"),
                "member_class": row.get("member_class"),
                "role": row.get("role"),
                "authority": row.get("authority"),
                "evidence_authority": row.get("evidence_authority"),
                "load_mode": row.get("load_mode"),
                "descriptor_status": row.get("descriptor_status"),
                "descriptor_hash": row.get("descriptor_hash"),
                "consumes": row.get("consumes") or [],
                "emits": row.get("emits") or [],
            }
            for key, row in sorted(entries.items())
        }
        lock_core = {
            "model_id": "JANUS",
            "bootstrap_root": self.manifest["bootstrap_root"]["repository"],
            "topology_hashes": dict(sorted(topology_hashes.items())),
            "members": members_for_digest,
            "state_mounts": state_mounts,
            "capability_index": capability_index,
            "memory_database": {
                "repository": memory_repo,
                "head_sha": None if memory_member is None else memory_member.get("head_sha"),
                "role": self.manifest["memory_database"]["role"],
            },
            "authority_ceiling": {
                "external_effect_authorized": False,
                "physical_runtime_effect_authorized": False,
                "world_truth_authority_granted": False,
                "command_authority_granted": False,
            },
        }
        model_digest = canonical_hash(lock_core)
        lock = {
            "schema": "janus.activator.model_lock.v1",
            "compiled_at": float(self.now_fn()),
            "model_id": "JANUS",
            "model_class": self.manifest["model_class"],
            "model_digest": model_digest,
            "terminal": self.manifest["boot_terminal_failure"] if fail_closed else self.manifest["boot_terminal_success"],
            "ready": not fail_closed,
            "routing_selects_activity_not_membership": True,
            "all_membership_compiled_before_routing": True,
            "external_effect_authorized": False,
            "physical_runtime_effect_authorized": False,
            "topology_versions": {
                key: value.get("version") or value.get("schema")
                for key, value in topology.items()
            },
            "topology_hashes": topology_hashes,
            "members": entries,
            "state_mounts": state_mounts,
            "memory_database": lock_core["memory_database"],
            "capability_index": capability_index,
            "optional_unavailable": sorted(set(optional_unavailable)),
            "failures": failures,
            "lock_core_hash": canonical_hash(lock_core),
        }
        if fail_closed:
            lock["next_gate"] = "REPAIR_REQUIRED_MODEL_FABRIC_DEPENDENCY"
        else:
            lock["next_gate"] = "BIND_COGNITIVE_RUNTIME_AND_WAIT_FOR_FRESH_STIMULUS"
        return lock


__all__ = ["GitHubRepositoryReader", "ModelFabricCompiler", "ModelFabricError"]
