from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Mapping

from .activator import canonical_hash
from .organ_materializer import OrganMaterializationError, OrganMaterializer, _json_file


class CandidateTissueMaterializationError(OrganMaterializationError):
    pass


class CandidateAwareOrganMaterializer(OrganMaterializer):
    """Extend exact-SHA organ materialization with admitted child candidate tissues.

    A candidate tissue is not model membership and is never arbitrary code.  It
    can run only when:
      * the model lock admitted it;
      * its parent organ is active and materialized on the exact locked SHA;
      * the current route is allowlisted by the materialization constitution;
      * the manifest hash at that exact parent checkout equals the model lock;
      * authority and scientific boundaries remain candidate-only.

    v1.3 initially admits only TRUMP `status` + `selftest`.
    """

    @staticmethod
    def _json_suffix(stdout: str) -> Dict[str, Any]:
        start = stdout.find("{")
        if start < 0:
            raise CandidateTissueMaterializationError("CANDIDATE_RECEIPT_JSON_MISSING")
        try:
            value = json.loads(stdout[start:])
        except Exception as exc:
            raise CandidateTissueMaterializationError("CANDIDATE_RECEIPT_JSON_INVALID") from exc
        if not isinstance(value, dict):
            raise CandidateTissueMaterializationError("CANDIDATE_RECEIPT_OBJECT_REQUIRED")
        return value

    @staticmethod
    def _verify_candidate_receipt(receipt: Mapping[str, Any], *, expected_terminal: str, execution_performed: bool) -> None:
        body = dict(receipt)
        claimed = str(body.pop("receipt_hash", ""))
        if not claimed or canonical_hash(body) != claimed:
            raise CandidateTissueMaterializationError("CANDIDATE_RECEIPT_HASH_INVALID")
        if receipt.get("terminal") != expected_terminal:
            raise CandidateTissueMaterializationError(f"CANDIDATE_TERMINAL_MISMATCH:{receipt.get('terminal')}")
        if receipt.get("mode") != "CANDIDATE_RUNTIME_TISSUE":
            raise CandidateTissueMaterializationError("CANDIDATE_MODE_MISMATCH")
        if receipt.get("execution_performed") is not execution_performed:
            raise CandidateTissueMaterializationError("CANDIDATE_EXECUTION_FLAG_MISMATCH")
        authority = receipt.get("authority") or {}
        for key in (
            "proof_authority",
            "scientific_claim_promotion_authority",
            "command_authority",
            "external_effect_authority",
            "physical_runtime_effect_authority",
        ):
            if authority.get(key) is not False:
                raise CandidateTissueMaterializationError(f"CANDIDATE_AUTHORITY_CEILING_VIOLATION:{key}")
        boundary = receipt.get("scientific_boundary") or {}
        if boundary.get("TRUMP_finished") is not False:
            raise CandidateTissueMaterializationError("CANDIDATE_TRUMP_FINISHED_FALSE_REQUIRED")
        if boundary.get("P_equals_NP_proved") is not False or boundary.get("P_VS_NP") != "OPEN":
            raise CandidateTissueMaterializationError("CANDIDATE_SCIENTIFIC_BOUNDARY_VIOLATION")

    def _route_matches(self) -> set[str]:
        matches: set[str] = set()
        for route in self.runtime_receipt.get("route_bindings") or []:
            if isinstance(route, Mapping) and route.get("match"):
                matches.add(str(route["match"]))
        return matches

    def _active_candidate_tissue_keys(self) -> list[str]:
        configured = self.constitution.get("candidate_tissue_adapters") or {}
        locked = self.model_lock.get("candidate_runtime_tissues") or {}
        active_members = set(self._active_member_keys())
        matches = self._route_matches()
        out: list[str] = []
        if not isinstance(configured, Mapping) or not isinstance(locked, Mapping):
            return out
        for key, spec in configured.items():
            if not isinstance(spec, Mapping):
                continue
            routes = {str(x) for x in spec.get("activate_on_routes") or []}
            if routes and routes.isdisjoint(matches):
                continue
            parent = str(spec.get("parent_member_key") or "")
            if parent not in active_members:
                continue
            row = locked.get(key)
            if not isinstance(row, Mapping):
                raise CandidateTissueMaterializationError(f"CANDIDATE_TISSUE_NOT_IN_MODEL_LOCK:{key}")
            if row.get("admission_status") != "ADMITTED_CANDIDATE_RUNTIME":
                raise CandidateTissueMaterializationError(f"CANDIDATE_TISSUE_NOT_ADMITTED:{key}")
            if row.get("wake_allowed") is not True or row.get("use_allowed") is not True:
                raise CandidateTissueMaterializationError(f"CANDIDATE_TISSUE_WAKE_OR_USE_BLOCKED:{key}")
            out.append(str(key))
        return sorted(set(out))

    def _trump_adapter(self, root: Path, sha: str, spec: Mapping[str, Any], tissue: Mapping[str, Any]) -> Dict[str, Any]:
        if tissue.get("repository") != spec.get("repository"):
            raise CandidateTissueMaterializationError("TRUMP_TISSUE_REPOSITORY_MISMATCH")
        if tissue.get("parent_head_sha") != sha:
            raise CandidateTissueMaterializationError("TRUMP_PARENT_SHA_BINDING_MISMATCH")
        manifest_path = root / str(spec.get("manifest_path") or "")
        entrypoint = root / str(spec.get("admitted_entrypoint") or "")
        manifest = _json_file(manifest_path)
        if manifest is None or not entrypoint.is_file():
            raise CandidateTissueMaterializationError("TRUMP_MANIFEST_OR_ENTRYPOINT_MISSING")
        if canonical_hash(manifest) != tissue.get("manifest_hash"):
            raise CandidateTissueMaterializationError("TRUMP_MANIFEST_HASH_BINDING_MISMATCH")
        if manifest.get("status") != spec.get("expected_manifest_status"):
            raise CandidateTissueMaterializationError("TRUMP_MANIFEST_STATUS_MISMATCH")

        status_cp = self._run([str(Path(__import__('sys').executable)), str(entrypoint), "status"], cwd=root, timeout=120.0)
        if status_cp.returncode != 0:
            raise CandidateTissueMaterializationError(f"TRUMP_STATUS_FAILED:{status_cp.stderr[-400:]}")
        status_receipt = self._json_suffix(status_cp.stdout)
        self._verify_candidate_receipt(
            status_receipt,
            expected_terminal=str(spec.get("expected_status_terminal")),
            execution_performed=False,
        )

        selftest_cp = self._run([str(Path(__import__('sys').executable)), str(entrypoint), "selftest"], cwd=root, timeout=240.0)
        if selftest_cp.returncode != 0:
            raise CandidateTissueMaterializationError(f"TRUMP_SELFTEST_FAILED:{selftest_cp.stderr[-500:]}:{selftest_cp.stdout[-500:]}")
        if "PASS: C025 unified exact-cap Akinator/JEC selftest" not in selftest_cp.stdout:
            raise CandidateTissueMaterializationError("TRUMP_NATIVE_SELFTEST_PASS_MARKER_MISSING")
        if "P_VS_NP = OPEN" not in selftest_cp.stdout:
            raise CandidateTissueMaterializationError("TRUMP_NATIVE_OPEN_BOUNDARY_MARKER_MISSING")
        selftest_receipt = self._json_suffix(selftest_cp.stdout)
        self._verify_candidate_receipt(
            selftest_receipt,
            expected_terminal=str(spec.get("expected_selftest_terminal")),
            execution_performed=True,
        )
        if selftest_receipt.get("candidate_result_promoted") is not False:
            raise CandidateTissueMaterializationError("TRUMP_CANDIDATE_RESULT_PROMOTION_FORBIDDEN")

        result = {
            "adapter": "TRUMP_CANDIDATE_SELFTEST",
            "component": "TRUMP",
            "candidate_tissue_key": "trump",
            "repository": str(spec.get("repository")),
            "parent_member_key": str(spec.get("parent_member_key")),
            "target_head_sha": sha,
            "manifest_path": str(spec.get("manifest_path")),
            "manifest_hash": str(tissue.get("manifest_hash")),
            "entrypoint": str(spec.get("admitted_entrypoint")),
            "status_receipt_hash": status_receipt["receipt_hash"],
            "selftest_receipt_hash": selftest_receipt["receipt_hash"],
            "native_selftest_pass": True,
            "candidate_execution_performed": True,
            "candidate_result_promoted": False,
            "network_read_performed": True,
            "repository_write_authorized": False,
            "repository_write_performed": False,
            "proof_authority": False,
            "scientific_claim_promotion_authority": False,
            "command_authority_granted": False,
            "world_truth_authority_granted": False,
            "external_effect_authorized": False,
            "physical_runtime_effect_authorized": False,
            "scientific_boundary": dict(selftest_receipt.get("scientific_boundary") or {}),
            "terminal": "TRUMP_CANDIDATE_TISSUE_MATERIALIZED_AND_SELF_TESTED",
        }
        result["adapter_result_hash"] = canonical_hash(result)
        return result

    def materialize(self) -> Dict[str, Any]:
        receipt = super().materialize()
        candidate_results: list[Dict[str, Any]] = []
        specs = self.constitution.get("candidate_tissue_adapters") or {}
        locked = self.model_lock.get("candidate_runtime_tissues") or {}
        materialized = {row["member_key"]: row for row in receipt.get("materialized") or []}

        for key in self._active_candidate_tissue_keys():
            spec = specs.get(key)
            tissue = locked.get(key)
            if not isinstance(spec, Mapping) or not isinstance(tissue, Mapping):
                raise CandidateTissueMaterializationError(f"CANDIDATE_TISSUE_SPEC_OR_LOCK_MISSING:{key}")
            parent = str(spec.get("parent_member_key") or "")
            parent_row = materialized.get(parent)
            if not isinstance(parent_row, Mapping):
                raise CandidateTissueMaterializationError(f"CANDIDATE_PARENT_NOT_MATERIALIZED:{key}:{parent}")
            parent_sha = str(parent_row.get("materialized_head_sha") or "")
            if parent_sha != str(tissue.get("parent_head_sha") or ""):
                raise CandidateTissueMaterializationError(f"CANDIDATE_PARENT_SHA_MISMATCH:{key}")
            root = self.workspace / parent.replace(":", "__")
            adapter_name = spec.get("adapter")
            if adapter_name == "TRUMP_CANDIDATE_SELFTEST":
                adapter = self._trump_adapter(root, parent_sha, spec, tissue)
            else:
                raise CandidateTissueMaterializationError(f"UNKNOWN_CANDIDATE_TISSUE_ADAPTER:{key}:{adapter_name}")
            candidate_results.append({
                "candidate_tissue_key": key,
                "parent_member_key": parent,
                "repository": tissue.get("repository"),
                "parent_head_sha": parent_sha,
                "manifest_hash": tissue.get("manifest_hash"),
                "adapter_result": adapter,
            })

        body = dict(receipt)
        body.pop("materialization_receipt_hash", None)
        body["materialized_candidate_tissues"] = candidate_results
        body["materialized_candidate_tissue_count"] = len(candidate_results)
        body["executed_candidate_tissues"] = [
            row["candidate_tissue_key"]
            for row in candidate_results
            if (row.get("adapter_result") or {}).get("candidate_execution_performed") is True
        ]
        body["candidate_result_promotion_performed"] = False
        body["proof_authority_granted"] = False
        body["scientific_claim_promotion_authority_granted"] = False
        body["next_gate"] = "REINTEGRATE_TYPED_ORGAN_AND_CANDIDATE_OUTPUTS_INTO_HOME_CHECKPOINT"
        body["materialization_receipt_hash"] = canonical_hash(body)
        return body


__all__ = ["CandidateAwareOrganMaterializer", "CandidateTissueMaterializationError"]
