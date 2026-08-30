from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

from .activator import canonical_hash

_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_HASH64 = re.compile(r"^[0-9a-f]{64}$")


class OrganMaterializationError(RuntimeError):
    pass


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json_file(path: Path) -> Dict[str, Any] | None:
    if not path.is_file():
        return None
    value = json.loads(path.read_text(encoding="utf-8"))
    return value if isinstance(value, dict) else None


class OrganMaterializer:
    def __init__(
        self,
        model_lock: Mapping[str, Any],
        runtime_receipt: Mapping[str, Any],
        *,
        workspace: str | Path,
        constitution: Mapping[str, Any],
        now_fn=time.time,
        git_bin: str = "git",
    ) -> None:
        self.model_lock = dict(model_lock)
        self.runtime_receipt = dict(runtime_receipt)
        self.workspace = Path(workspace).resolve()
        self.constitution = dict(constitution)
        self.now_fn = now_fn
        self.git_bin = git_bin
        self.workspace.mkdir(parents=True, exist_ok=True)
        self._validate_root_bindings()

    @classmethod
    def from_files(
        cls,
        *,
        model_lock_path: str | Path,
        runtime_receipt_path: str | Path,
        constitution_path: str | Path = ".janus/activator/ORGAN_MATERIALIZATION_CONSTITUTION.json",
        workspace: str | Path = "runtime/organs",
    ) -> "OrganMaterializer":
        lock = json.loads(Path(model_lock_path).read_text(encoding="utf-8"))
        receipt = json.loads(Path(runtime_receipt_path).read_text(encoding="utf-8"))
        constitution = json.loads(Path(constitution_path).read_text(encoding="utf-8"))
        if not all(isinstance(x, dict) for x in (lock, receipt, constitution)):
            raise OrganMaterializationError("MATERIALIZER_INPUT_OBJECT_REQUIRED")
        return cls(lock, receipt, workspace=workspace, constitution=constitution)

    def _validate_root_bindings(self) -> None:
        if self.constitution.get("schema") != "janus.activator.organ_materialization_constitution.v1":
            raise OrganMaterializationError("ORGAN_MATERIALIZATION_CONSTITUTION_SCHEMA_MISMATCH")
        if self.model_lock.get("schema") != "janus.activator.model_lock.v1" or self.model_lock.get("ready") is not True:
            raise OrganMaterializationError("MODEL_LOCK_NOT_READY")
        if self.runtime_receipt.get("schema") != "janus.activator.model_runtime_receipt.v1":
            raise OrganMaterializationError("MODEL_RUNTIME_RECEIPT_SCHEMA_MISMATCH")
        if self.runtime_receipt.get("model_digest") != self.model_lock.get("model_digest"):
            raise OrganMaterializationError("MODEL_DIGEST_BINDING_MISMATCH")
        if self.runtime_receipt.get("model_lock_hash") != canonical_hash(self.model_lock):
            raise OrganMaterializationError("MODEL_LOCK_HASH_BINDING_MISMATCH")
        if self.runtime_receipt.get("routing_selects_activity_not_membership") is not True:
            raise OrganMaterializationError("ROUTING_MEMBERSHIP_LAW_MISSING")
        if self.runtime_receipt.get("membership_was_locked_before_activation") is not True:
            raise OrganMaterializationError("MEMBERSHIP_NOT_LOCKED_BEFORE_ACTIVATION")
        for key in ("dispatch_authorized", "command_authority_granted", "world_truth_authority_granted", "external_effect_authorized", "physical_runtime_effect_authorized"):
            if self.runtime_receipt.get(key) is not False:
                raise OrganMaterializationError(f"RUNTIME_AUTHORITY_CEILING_VIOLATION:{key}")

    @property
    def members(self) -> Dict[str, Dict[str, Any]]:
        value = self.model_lock.get("members")
        if not isinstance(value, dict):
            raise OrganMaterializationError("MODEL_MEMBERS_MISSING")
        return value

    def _active_member_keys(self) -> list[str]:
        keys = self.runtime_receipt.get("active_members") or []
        if not isinstance(keys, list):
            raise OrganMaterializationError("ACTIVE_MEMBERS_NOT_LIST")
        out: list[str] = []
        for raw in keys:
            key = str(raw)
            if key not in self.members:
                raise OrganMaterializationError(f"ACTIVE_MEMBER_OUTSIDE_MODEL:{key}")
            if key not in out:
                out.append(key)
        return out

    def _run(self, args: list[str], *, cwd: Path, timeout: float = 120.0) -> subprocess.CompletedProcess[str]:
        env = {
            "PATH": os.environ.get("PATH", ""),
            "HOME": os.environ.get("HOME", ""),
            "LANG": os.environ.get("LANG", "C.UTF-8"),
            "LC_ALL": os.environ.get("LC_ALL", "C.UTF-8"),
            "PYTHONIOENCODING": "utf-8",
            "GIT_TERMINAL_PROMPT": "0",
        }
        return subprocess.run(
            args,
            cwd=cwd,
            text=True,
            capture_output=True,
            timeout=timeout,
            env=env,
            check=False,
        )

    def _checkout_exact(self, key: str, member: Mapping[str, Any]) -> tuple[Path, str]:
        repo = str(member.get("repository") or "")
        sha = str(member.get("head_sha") or "")
        if not repo or _SHA40.fullmatch(sha) is None:
            raise OrganMaterializationError(f"LOCKED_REPOSITORY_OR_SHA_REQUIRED:{key}")
        dest = self.workspace / key.replace(":", "__")
        if dest.exists():
            shutil.rmtree(dest)
        dest.mkdir(parents=True)
        init = self._run([self.git_bin, "init", "-q"], cwd=dest)
        if init.returncode != 0:
            raise OrganMaterializationError(f"GIT_INIT_FAILED:{key}:{init.stderr[-300:]}")
        remote = self._run([self.git_bin, "remote", "add", "origin", f"https://github.com/{repo}.git"], cwd=dest)
        if remote.returncode != 0:
            raise OrganMaterializationError(f"GIT_REMOTE_FAILED:{key}:{remote.stderr[-300:]}")
        fetched = self._run([self.git_bin, "fetch", "-q", "--depth=1", "origin", sha], cwd=dest, timeout=180.0)
        if fetched.returncode != 0:
            raise OrganMaterializationError(f"GIT_FETCH_EXACT_SHA_FAILED:{key}:{fetched.stderr[-500:]}")
        checkout = self._run([self.git_bin, "checkout", "-q", "--detach", "FETCH_HEAD"], cwd=dest)
        if checkout.returncode != 0:
            raise OrganMaterializationError(f"GIT_CHECKOUT_FAILED:{key}:{checkout.stderr[-300:]}")
        actual = self._run([self.git_bin, "rev-parse", "HEAD"], cwd=dest)
        actual_sha = actual.stdout.strip()
        if actual.returncode != 0 or actual_sha != sha:
            raise OrganMaterializationError(f"MATERIALIZED_SHA_MISMATCH:{key}:{actual_sha}:{sha}")
        return dest, actual_sha

    def _descriptor(self, root: Path, key: str, repo: str) -> Dict[str, Any]:
        descriptor = _json_file(root / ".janus" / "JANUS_ORGANISM_LINK.json")
        if descriptor is None:
            return {
                "status": "CENTRAL_MODEL_LOCK_FALLBACK",
                "descriptor_hash": None,
                "organ_key": key,
                "repository": repo,
            }
        if descriptor.get("organism_id") != "JANUS_FEDERATED_ORGANISM":
            raise OrganMaterializationError(f"ORGAN_DESCRIPTOR_WRONG_ORGANISM:{key}")
        if descriptor.get("organ_key") not in {None, key}:
            raise OrganMaterializationError(f"ORGAN_DESCRIPTOR_KEY_MISMATCH:{key}")
        if descriptor.get("member_repository") not in {None, repo}:
            raise OrganMaterializationError(f"ORGAN_DESCRIPTOR_REPOSITORY_MISMATCH:{key}")
        return {
            "status": "SELF_DECLARED",
            "descriptor_hash": canonical_hash(descriptor),
            "organ_key": key,
            "repository": repo,
            "role": descriptor.get("role"),
            "authority": descriptor.get("authority"),
            "evidence_authority": descriptor.get("evidence_authority"),
        }

    def _selected_file_capsule(self, root: Path, paths: list[str], *, schema: str, repository: str, sha: str) -> Dict[str, Any]:
        hashes: Dict[str, str] = {}
        sizes: Dict[str, int] = {}
        for rel in paths:
            path = (root / rel).resolve()
            try:
                path.relative_to(root.resolve())
            except ValueError as exc:
                raise OrganMaterializationError("CONTEXT_PATH_ESCAPES_REPOSITORY") from exc
            if path.is_file():
                hashes[rel] = _file_sha256(path)
                sizes[rel] = path.stat().st_size
        capsule = {
            "schema": schema,
            "repository": repository,
            "target_head_sha": sha,
            "selected_file_sha256": dict(sorted(hashes.items())),
            "selected_file_sizes": dict(sorted(sizes.items())),
            "source_scope": "EXACT_CHECKED_OUT_REPOSITORY_ONLY",
            "repository_write_performed": False,
            "command_authority_granted": False,
            "scientific_evidence_authority_granted": False,
            "world_truth_authority_granted": False,
            "external_effect_authorized": False,
            "external_effect_performed": False,
            "physical_runtime_effect_authorized": False,
        }
        capsule["capsule_hash"] = canonical_hash(capsule)
        return capsule

    def _topa_adapter(self, root: Path, sha: str, spec: Mapping[str, Any]) -> Dict[str, Any]:
        entrypoint = root / str(spec["admitted_entrypoint"])
        if not entrypoint.is_file():
            raise OrganMaterializationError("TOPA_ADMITTED_ENTRYPOINT_MISSING")
        argv = [sys.executable, str(entrypoint), *[str(x) for x in spec.get("argv") or []]]
        cp = self._run(argv, cwd=root, timeout=180.0)
        try:
            payload = json.loads(cp.stdout)
        except Exception as exc:
            raise OrganMaterializationError(f"TOPA_RECEIPT_NOT_JSON:{cp.stderr[-300:]}") from exc
        if cp.returncode != 0 or not isinstance(payload, dict) or payload.get("status") != "PASS":
            raise OrganMaterializationError(f"TOPA_DETECTIVE_SELF_TEST_FAILED:{payload if isinstance(payload, dict) else cp.stderr[-300:]}")
        activated = payload.get("activated") or {}
        if payload.get("identity") != spec.get("expected_identity"):
            raise OrganMaterializationError("TOPA_IDENTITY_MISMATCH")
        if activated.get("topa_core") is not True or activated.get("spider") is not True:
            raise OrganMaterializationError("TOPA_DETECTIVE_MUST_INCLUDE_CORE_AND_SPIDER")
        result = {
            "adapter": "TOPA_DETECTIVE_SELF_TEST",
            "repository": "Hawkar-usls/TOPA",
            "target_head_sha": sha,
            "entrypoint": str(spec["admitted_entrypoint"]),
            "mode": payload.get("mode"),
            "identity": payload.get("identity"),
            "activated": activated,
            "component_checks": payload.get("checks") or [],
            "component_receipt_hash": canonical_hash(payload),
            "execution_scope": "REPOSITORY_LOCAL_CANONICAL_SELF_TEST",
            "model_access_authorized": False,
            "repository_write_authorized": False,
            "external_effect_authorized": False,
            "physical_runtime_effect_authorized": False,
            "terminal": "TOPA_DETECTIVE_SPIDER_MATERIALIZED_AND_SELF_TESTED",
        }
        result["adapter_result_hash"] = canonical_hash(result)
        return result

    def _hrain_adapter(self, root: Path, sha: str, spec: Mapping[str, Any]) -> Dict[str, Any]:
        capsule = self._selected_file_capsule(
            root,
            [str(x) for x in spec.get("read_only_paths") or []],
            schema="janus.hrain.readonly_structural_context_capsule.v1",
            repository="Hawkar-usls/Hrain",
            sha=sha,
        )
        link = _json_file(root / ".janus" / "TOPA_SPIDER_LINK.json")
        home = _json_file(root / ".janus" / "SPIDER_HOME.json")
        if not isinstance(link, dict) or not isinstance(home, dict):
            raise OrganMaterializationError("HRAIN_SPIDER_CONTEXT_CONTRACT_MISSING")
        if link.get("writeback") is not False:
            raise OrganMaterializationError("HRAIN_CONTEXT_WRITEBACK_MUST_BE_FALSE")
        laws = set(link.get("laws") or [])
        required_laws = {
            "REPLAY_IS_NOT_NEW_EVIDENCE",
            "CONTEXT_COMPLETENESS_IS_NOT_CLAIM_STRENGTH",
            "ATTENTION_WEIGHT_IS_NOT_EVIDENCE_WEIGHT",
            "TOPA_DETECTIVE_DEFAULT_INCLUDES_SPIDER",
        }
        if not required_laws.issubset(laws):
            raise OrganMaterializationError("HRAIN_REQUIRED_CONTEXT_LAWS_MISSING")
        if home.get("status") != "ACTIVE_RESIDENT":
            raise OrganMaterializationError("HRAIN_SPIDER_NOT_ACTIVE_RESIDENT")
        result = {
            "adapter": "HRAIN_READ_ONLY_CONTEXT_CAPSULE",
            "repository": "Hawkar-usls/Hrain",
            "target_head_sha": sha,
            "capsule": capsule,
            "spider_resident": True,
            "writeback": False,
            "required_laws_verified": sorted(required_laws),
            "context_fur_bound": bool(((link.get("hrain_components") or {}).get("context_fur_panel"))),
            "attention_ecosystem_bound": bool(((link.get("hrain_components") or {}).get("attention_ecosystem"))),
            "execution_performed": False,
            "external_effect_authorized": False,
            "physical_runtime_effect_authorized": False,
            "terminal": "HRAIN_STRUCTURAL_CONTEXT_MATERIALIZED_READ_ONLY",
        }
        result["adapter_result_hash"] = canonical_hash(result)
        return result

    def _demiurge_adapter(self, root: Path, sha: str, spec: Mapping[str, Any]) -> Dict[str, Any]:
        capsule = self._selected_file_capsule(
            root,
            [str(x) for x in spec.get("read_only_paths") or []],
            schema="janus.demiurge.readonly_control_context_capsule.v1",
            repository="Hawkar-usls/Janus-Demiurge",
            sha=sha,
        )
        executor = root / "tools" / "activator_readonly_execution.py"
        workflow = root / ".github" / "workflows" / "janus-activator-readonly-execution.yml"
        if not executor.is_file() or not workflow.is_file():
            raise OrganMaterializationError("DEMIURGE_BOUNDED_EXECUTOR_CONTRACT_MISSING")
        result = {
            "adapter": "DEMIURGE_READ_ONLY_CONTROL_CAPSULE",
            "repository": "Hawkar-usls/Janus-Demiurge",
            "target_head_sha": sha,
            "capsule": capsule,
            "bounded_executor_present": True,
            "execution_grant_required": True,
            "target_executor_invoked": False,
            "execution_performed": False,
            "dispatch_authority_granted": False,
            "external_effect_authorized": False,
            "physical_runtime_effect_authorized": False,
            "terminal": "DEMIURGE_CONTROL_PLANE_MATERIALIZED_NO_EXECUTION",
        }
        result["adapter_result_hash"] = canonical_hash(result)
        return result

    def _fallback_adapter(self, root: Path, key: str, repo: str, sha: str) -> Dict[str, Any]:
        descriptor_path = root / ".janus" / "JANUS_ORGANISM_LINK.json"
        selected = [str(descriptor_path.relative_to(root))] if descriptor_path.is_file() else []
        capsule = self._selected_file_capsule(
            root,
            selected,
            schema="janus.organ.locked_repository_context_capsule.v1",
            repository=repo,
            sha=sha,
        )
        result = {
            "adapter": "LOCKED_REPOSITORY_CONTEXT_ONLY",
            "member_key": key,
            "repository": repo,
            "target_head_sha": sha,
            "capsule": capsule,
            "execution_performed": False,
            "external_effect_authorized": False,
            "physical_runtime_effect_authorized": False,
            "terminal": "LOCKED_MEMBER_CONTEXT_MATERIALIZED_NO_EXECUTION",
        }
        result["adapter_result_hash"] = canonical_hash(result)
        return result

    def materialize(self) -> Dict[str, Any]:
        active = self._active_member_keys()
        adapters = self.constitution.get("initial_adapters") or {}
        results: list[Dict[str, Any]] = []
        for key in active:
            member = self.members[key]
            repo = str(member.get("repository") or "")
            if not repo:
                raise OrganMaterializationError(f"ACTIVE_MEMBER_HAS_NO_REPOSITORY:{key}")
            root, sha = self._checkout_exact(key, member)
            descriptor = self._descriptor(root, key, repo)
            spec = adapters.get(key) if isinstance(adapters, dict) else None
            if isinstance(spec, dict):
                if spec.get("repository") != repo:
                    raise OrganMaterializationError(f"ADAPTER_REPOSITORY_MISMATCH:{key}")
                adapter_name = spec.get("adapter")
                if adapter_name == "TOPA_DETECTIVE_SELF_TEST":
                    adapter = self._topa_adapter(root, sha, spec)
                elif adapter_name == "HRAIN_READ_ONLY_CONTEXT_CAPSULE":
                    adapter = self._hrain_adapter(root, sha, spec)
                elif adapter_name == "DEMIURGE_READ_ONLY_CONTROL_CAPSULE":
                    adapter = self._demiurge_adapter(root, sha, spec)
                else:
                    raise OrganMaterializationError(f"UNKNOWN_EXPLICIT_ADAPTER:{key}:{adapter_name}")
            else:
                adapter = self._fallback_adapter(root, key, repo, sha)
            results.append({
                "member_key": key,
                "kind": member.get("kind"),
                "repository": repo,
                "locked_head_sha": str(member.get("head_sha")),
                "materialized_head_sha": sha,
                "descriptor": descriptor,
                "adapter_result": adapter,
            })

        receipt = {
            "schema": "janus.activator.organ_materialization_receipt.v1",
            "created_at": float(self.now_fn()),
            "model_id": "JANUS",
            "model_digest": self.model_lock["model_digest"],
            "model_lock_hash": canonical_hash(self.model_lock),
            "model_runtime_receipt_hash": str(self.runtime_receipt.get("runtime_receipt_hash") or ""),
            "activation_id": self.runtime_receipt.get("activation_id"),
            "active_members": active,
            "materialized": results,
            "materialized_member_count": len(results),
            "executed_adapters": [
                row["member_key"] for row in results
                if bool((row.get("adapter_result") or {}).get("execution_performed"))
                or (row.get("adapter_result") or {}).get("adapter") == "TOPA_DETECTIVE_SELF_TEST"
            ],
            "repository_write_authorized": False,
            "command_authority_granted": False,
            "scientific_evidence_authority_granted": False,
            "world_truth_authority_granted": False,
            "external_effect_authorized": False,
            "physical_runtime_effect_authorized": False,
            "terminal": self.constitution["terminal_success"],
            "next_gate": "REINTEGRATE_TYPED_ORGAN_OUTPUTS_INTO_HOME_CHECKPOINT",
        }
        receipt["materialization_receipt_hash"] = canonical_hash(receipt)
        return receipt


__all__ = ["OrganMaterializer", "OrganMaterializationError"]
