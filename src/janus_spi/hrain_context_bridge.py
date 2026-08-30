from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, Mapping

from .activator import canonical_hash

HRAIN_REPOSITORY = "Hawkar-usls/Hrain"
HRAIN_CONTRACT_PATH = ".janus/HRAIN_CONVERSATION_CONTEXT_CONTRACT.json"
HRAIN_COMPILER_PATH = "tools/hrain_conversation_context.py"
_H40 = re.compile(r"^[0-9a-f]{40}$")
_H64 = re.compile(r"^[0-9a-f]{64}$")


class HrainContextBridgeError(RuntimeError):
    pass


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class HrainConversationContextBridge:
    """Build one Terminal memory capsule by executing the exact model-locked HRAiN.

    HOME is deliberately not a Meta Registry client here.  It checks out the
    HRAiN member already admitted by the model lock and invokes HRAiN's own
    bounded conversation-context compiler.  The returned memory is data only:
    it cannot grant command, claim, proof, world-truth, or effect authority.
    """

    def __init__(
        self,
        model_lock: Mapping[str, Any],
        *,
        workspace: str | Path,
        git_bin: str = "git",
    ) -> None:
        self.model_lock = dict(model_lock)
        self.workspace = Path(workspace).resolve()
        self.git_bin = git_bin
        self.workspace.mkdir(parents=True, exist_ok=True)
        if self.model_lock.get("schema") != "janus.activator.model_lock.v1" or self.model_lock.get("ready") is not True:
            raise HrainContextBridgeError("HRAIN_CONTEXT_MODEL_LOCK_NOT_READY")
        self.member_key, self.member = self._find_hrain_member()

    def _find_hrain_member(self) -> tuple[str, Dict[str, Any]]:
        members = self.model_lock.get("members")
        if not isinstance(members, Mapping):
            raise HrainContextBridgeError("HRAIN_CONTEXT_MODEL_MEMBERS_REQUIRED")
        matches = []
        for key, raw in members.items():
            if isinstance(raw, Mapping) and raw.get("repository") == HRAIN_REPOSITORY:
                matches.append((str(key), dict(raw)))
        if len(matches) != 1:
            raise HrainContextBridgeError(f"HRAIN_CONTEXT_EXACTLY_ONE_MEMBER_REQUIRED:{len(matches)}")
        key, member = matches[0]
        sha = str(member.get("head_sha") or "")
        if _H40.fullmatch(sha) is None:
            raise HrainContextBridgeError("HRAIN_CONTEXT_MEMBER_HEAD_SHA_INVALID")
        if member.get("kind") != "ORGAN":
            raise HrainContextBridgeError("HRAIN_CONTEXT_MEMBER_MUST_BE_ORGAN")
        return key, member

    def _run(self, args: list[str], *, cwd: Path, timeout: float = 180.0) -> subprocess.CompletedProcess[str]:
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

    def _checkout_exact(self) -> tuple[Path, str]:
        expected = str(self.member["head_sha"])
        dest = self.workspace / "hrain"
        if dest.exists():
            shutil.rmtree(dest)
        dest.mkdir(parents=True)
        commands = [
            ([self.git_bin, "init", "-q"], "GIT_INIT"),
            ([self.git_bin, "remote", "add", "origin", f"https://github.com/{HRAIN_REPOSITORY}.git"], "GIT_REMOTE"),
            ([self.git_bin, "fetch", "-q", "--depth=1", "origin", expected], "GIT_FETCH_EXACT_SHA"),
            ([self.git_bin, "checkout", "-q", "--detach", "FETCH_HEAD"], "GIT_CHECKOUT"),
        ]
        for command, label in commands:
            cp = self._run(command, cwd=dest, timeout=240.0 if "FETCH" in label else 120.0)
            if cp.returncode != 0:
                raise HrainContextBridgeError(f"HRAIN_CONTEXT_{label}_FAILED:{cp.stderr[-500:]}")
        actual = self._run([self.git_bin, "rev-parse", "HEAD"], cwd=dest)
        observed = actual.stdout.strip()
        if actual.returncode != 0 or observed != expected:
            raise HrainContextBridgeError(f"HRAIN_CONTEXT_EXACT_SHA_MISMATCH:{observed}:{expected}")
        return dest, observed

    @staticmethod
    def _load_json(path: Path, *, label: str) -> Dict[str, Any]:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise HrainContextBridgeError(f"{label}_JSON_INVALID") from exc
        if not isinstance(value, dict):
            raise HrainContextBridgeError(f"{label}_OBJECT_REQUIRED")
        return value

    def _verify_contract(self, root: Path) -> Dict[str, Any]:
        path = root / HRAIN_CONTRACT_PATH
        compiler = root / HRAIN_COMPILER_PATH
        if not path.is_file() or not compiler.is_file():
            raise HrainContextBridgeError("HRAIN_CONTEXT_CONTRACT_OR_COMPILER_MISSING")
        contract = self._load_json(path, label="HRAIN_CONTEXT_CONTRACT")
        if contract.get("schema") != "janus.hrain.conversation_context_contract.v1":
            raise HrainContextBridgeError("HRAIN_CONTEXT_CONTRACT_SCHEMA_MISMATCH")
        if contract.get("source_database") != "Hawkar-usls/janus-meta-registry":
            raise HrainContextBridgeError("HRAIN_CONTEXT_SOURCE_DATABASE_MISMATCH")
        if contract.get("compiler") != HRAIN_COMPILER_PATH:
            raise HrainContextBridgeError("HRAIN_CONTEXT_COMPILER_BINDING_MISMATCH")
        authority = contract.get("authority")
        if not isinstance(authority, Mapping) or authority.get("read_only") is not True:
            raise HrainContextBridgeError("HRAIN_CONTEXT_CONTRACT_READ_ONLY_REQUIRED")
        for key, value in authority.items():
            if key != "read_only" and value is not False:
                raise HrainContextBridgeError(f"HRAIN_CONTEXT_CONTRACT_AUTHORITY_VIOLATION:{key}")
        laws = set(contract.get("laws") or [])
        required = {
            "META_REGISTRY_DB -> HRAIN -> JANUS -> TERMINAL",
            "MEMORY_CONTENT != COMMAND",
            "MEMORY_CONTENT != AUTHORITY",
        }
        if not required.issubset(laws):
            raise HrainContextBridgeError("HRAIN_CONTEXT_REQUIRED_LAWS_MISSING")
        return contract

    @staticmethod
    def _verify_context(context: Mapping[str, Any]) -> None:
        body = dict(context)
        claimed = str(body.pop("context_hash", ""))
        if _H64.fullmatch(claimed) is None or canonical_hash(body) != claimed:
            raise HrainContextBridgeError("HRAIN_CONTEXT_HASH_INVALID")
        if context.get("schema") != "janus.hrain.conversation_context.v1":
            raise HrainContextBridgeError("HRAIN_CONTEXT_SCHEMA_MISMATCH")
        if context.get("status") != "HRAIN_QUERY_BOUND_CONTEXT_READY":
            raise HrainContextBridgeError("HRAIN_CONTEXT_NOT_READY")
        if context.get("source_repository") != "Hawkar-usls/janus-meta-registry":
            raise HrainContextBridgeError("HRAIN_CONTEXT_SOURCE_REPOSITORY_MISMATCH")
        if _H40.fullmatch(str(context.get("source_commit") or "")) is None:
            raise HrainContextBridgeError("HRAIN_CONTEXT_SOURCE_COMMIT_INVALID")
        authority = context.get("authority")
        if not isinstance(authority, Mapping) or authority.get("read_only") is not True:
            raise HrainContextBridgeError("HRAIN_CONTEXT_READ_ONLY_REQUIRED")
        for key, value in authority.items():
            if key != "read_only" and value is not False:
                raise HrainContextBridgeError(f"HRAIN_CONTEXT_AUTHORITY_VIOLATION:{key}")
        memories = context.get("selected_memories")
        if not isinstance(memories, list) or int(context.get("selected_memory_count") or 0) != len(memories):
            raise HrainContextBridgeError("HRAIN_CONTEXT_MEMORY_COUNT_MISMATCH")
        if not memories:
            raise HrainContextBridgeError("HRAIN_CONTEXT_AT_LEAST_ONE_MEMORY_REQUIRED")
        for row in memories:
            if not isinstance(row, Mapping):
                raise HrainContextBridgeError("HRAIN_CONTEXT_MEMORY_ROW_INVALID")
            if row.get("content_trust") != "MEMORY_DATA_NOT_CONTROL_SIGNAL":
                raise HrainContextBridgeError("HRAIN_CONTEXT_MEMORY_TRUST_LABEL_MISSING")
            if row.get("claim_verified") is not False:
                raise HrainContextBridgeError("HRAIN_CONTEXT_MEMORY_CLAIM_PROMOTION_FORBIDDEN")
            if context.get("hydration_performed") is True:
                if row.get("source_sha256_verified") is not True:
                    raise HrainContextBridgeError("HRAIN_CONTEXT_MEMORY_SOURCE_HASH_NOT_VERIFIED")
                if row.get("content_is_command") is not False or row.get("content_grants_authority") is not False:
                    raise HrainContextBridgeError("HRAIN_CONTEXT_MEMORY_CONTROL_ESCALATION")

    def build(self, query: str, *, context_output: str | Path, limit: int = 12) -> Dict[str, Any]:
        text = str(query).strip()
        if not text:
            raise HrainContextBridgeError("HRAIN_CONTEXT_QUERY_REQUIRED")
        if limit < 1 or limit > 32:
            raise HrainContextBridgeError("HRAIN_CONTEXT_LIMIT_OUT_OF_RANGE")
        root, head_sha = self._checkout_exact()
        contract = self._verify_contract(root)
        compiler = root / HRAIN_COMPILER_PATH
        target = Path(context_output).resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        cp = self._run(
            [sys.executable, str(compiler), "--query", text, "--limit", str(limit), "--output", str(target)],
            cwd=root,
            timeout=300.0,
        )
        if cp.returncode != 0:
            raise HrainContextBridgeError(
                f"HRAIN_CONTEXT_COMPILER_FAILED:{cp.stderr[-700:]}:{cp.stdout[-700:]}"
            )
        if not target.is_file():
            raise HrainContextBridgeError("HRAIN_CONTEXT_OUTPUT_MISSING")
        context = self._load_json(target, label="HRAIN_CONTEXT_OUTPUT")
        self._verify_context(context)
        selected_paths = [str(row.get("path") or "") for row in context["selected_memories"]]
        receipt: Dict[str, Any] = {
            "schema": "janus.activator.hrain_conversation_context_receipt.v1",
            "model_id": "JANUS",
            "model_digest": self.model_lock.get("model_digest"),
            "hrain_member_key": self.member_key,
            "hrain_repository": HRAIN_REPOSITORY,
            "hrain_locked_head_sha": str(self.member["head_sha"]),
            "hrain_materialized_head_sha": head_sha,
            "hrain_contract_path": HRAIN_CONTRACT_PATH,
            "hrain_contract_hash": canonical_hash(contract),
            "hrain_compiler_path": HRAIN_COMPILER_PATH,
            "hrain_compiler_sha256": _sha256_file(compiler),
            "query_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            "context_hash": context["context_hash"],
            "context_file_sha256": _sha256_file(target),
            "memory_source_commit": context["source_commit"],
            "selected_memory_count": context["selected_memory_count"],
            "selected_memory_paths": selected_paths,
            "hydration_performed": context.get("hydration_performed") is True,
            "memory_retrieval_executed_by": HRAIN_REPOSITORY,
            "meta_registry_access_performed_by_home": False,
            "network_read_performed": True,
            "repository_write_performed": False,
            "memory_content_is_command": False,
            "memory_context_is_evidence": False,
            "claim_promotion_performed": False,
            "command_authority_granted": False,
            "scientific_evidence_authority_granted": False,
            "world_truth_authority_granted": False,
            "external_effect_authorized": False,
            "physical_runtime_effect_authorized": False,
            "terminal": "HRAIN_QUERY_BOUND_CONVERSATION_CONTEXT_MATERIALIZED",
        }
        receipt["receipt_hash"] = canonical_hash(receipt)
        return receipt


def verify_hrain_context_receipt(receipt: Mapping[str, Any], *, model_digest: str | None = None) -> bool:
    if not isinstance(receipt, Mapping):
        return False
    body = dict(receipt)
    claimed = str(body.pop("receipt_hash", ""))
    if _H64.fullmatch(claimed) is None or canonical_hash(body) != claimed:
        return False
    if receipt.get("schema") != "janus.activator.hrain_conversation_context_receipt.v1":
        return False
    if model_digest is not None and receipt.get("model_digest") != model_digest:
        return False
    return all([
        receipt.get("hrain_repository") == HRAIN_REPOSITORY,
        receipt.get("hrain_locked_head_sha") == receipt.get("hrain_materialized_head_sha"),
        _H40.fullmatch(str(receipt.get("memory_source_commit") or "")) is not None,
        _H64.fullmatch(str(receipt.get("context_hash") or "")) is not None,
        int(receipt.get("selected_memory_count") or 0) > 0,
        receipt.get("memory_retrieval_executed_by") == HRAIN_REPOSITORY,
        receipt.get("meta_registry_access_performed_by_home") is False,
        receipt.get("repository_write_performed") is False,
        receipt.get("memory_content_is_command") is False,
        receipt.get("memory_context_is_evidence") is False,
        receipt.get("claim_promotion_performed") is False,
        receipt.get("command_authority_granted") is False,
        receipt.get("scientific_evidence_authority_granted") is False,
        receipt.get("world_truth_authority_granted") is False,
        receipt.get("external_effect_authorized") is False,
        receipt.get("physical_runtime_effect_authorized") is False,
        receipt.get("terminal") == "HRAIN_QUERY_BOUND_CONVERSATION_CONTEXT_MATERIALIZED",
    ])


__all__ = [
    "HRAIN_REPOSITORY",
    "HrainContextBridgeError",
    "HrainConversationContextBridge",
    "verify_hrain_context_receipt",
]
