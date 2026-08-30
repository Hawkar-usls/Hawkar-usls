from __future__ import annotations

from typing import Any, Dict, Mapping

from .activator import canonical_hash
from .model_fabric_v11 import GitHubRepositoryReaderV11, ModelFabricCompilerV11


class CandidateRuntimeTissueError(RuntimeError):
    pass


class ModelFabricCompilerV12(ModelFabricCompilerV11):
    """JANUS model fabric v1.2 with exact parent-bound candidate runtime tissues.

    Candidate tissues are not duplicate repositories and are therefore not added
    to ``members``.  They are sub-tissues of an already locked organ.  Their
    manifest is loaded from the exact locked parent repository SHA, validated
    against a fail-closed authority ceiling, and folded into the model digest.

    This lets JANUS wake/use experimental computational tissue such as TRUMP
    without pretending that a candidate result has theorem/scientific authority.
    """

    @staticmethod
    def _authority_false(manifest: Mapping[str, Any]) -> bool:
        activation = manifest.get("activation")
        if not isinstance(activation, Mapping):
            return False
        keys = (
            "proof_authority",
            "scientific_claim_promotion_authority",
            "command_authority",
            "external_effect_authority",
            "physical_runtime_effect_authority",
        )
        return all(activation.get(key) is False for key in keys)

    @staticmethod
    def _candidate_scientific_boundary_open(manifest: Mapping[str, Any]) -> bool:
        boundary = manifest.get("scientific_boundary")
        if not isinstance(boundary, Mapping):
            return False
        return (
            boundary.get("TRUMP_finished") is False
            and boundary.get("polynomial_time_SAT_proved") is False
            and boundary.get("P_equals_NP_proved") is False
            and boundary.get("P_VS_NP") == "OPEN"
        )

    def _bind_candidate_runtime_tissues(self, lock: Mapping[str, Any]) -> tuple[Dict[str, Dict[str, Any]], list[str], list[str]]:
        members = lock.get("members")
        if not isinstance(members, Mapping):
            raise CandidateRuntimeTissueError("MODEL_MEMBERS_REQUIRED_FOR_CANDIDATE_TISSUES")

        tissues: Dict[str, Dict[str, Any]] = {}
        unavailable: list[str] = []
        required_failures: list[str] = []

        for configured in self.manifest.get("candidate_runtime_tissues", []):
            if not isinstance(configured, Mapping):
                continue
            tissue_key = str(configured.get("tissue_key") or "").strip()
            if not tissue_key:
                raise CandidateRuntimeTissueError("CANDIDATE_TISSUE_KEY_REQUIRED")
            if tissue_key in tissues:
                raise CandidateRuntimeTissueError(f"DUPLICATE_CANDIDATE_TISSUE:{tissue_key}")

            parent_key = str(configured.get("parent_organ") or "")
            parent = members.get(parent_key)
            required = bool(configured.get("required_for_model_ready", False))
            row: Dict[str, Any] = {
                "tissue_key": tissue_key,
                "component": configured.get("component"),
                "kind": "CANDIDATE_RUNTIME_TISSUE",
                "parent_organ": parent_key,
                "repository": configured.get("repository"),
                "manifest_path": configured.get("manifest_path"),
                "runtime_entrypoint": configured.get("runtime_entrypoint"),
                "load_mode": configured.get("load_mode", "LAZY_PARENT_BOUND"),
                "required_for_model_ready": required,
                "consumes": list(configured.get("consumes") or []),
                "emits": list(configured.get("emits") or []),
                "proof_authority": False,
                "scientific_claim_promotion_authority": False,
                "command_authority": False,
                "external_effect_authority": False,
                "physical_runtime_effect_authority": False,
            }

            reason: str | None = None
            manifest: Dict[str, Any] | None = None
            if not isinstance(parent, Mapping):
                reason = "PARENT_ORGAN_NOT_IN_MODEL"
            elif parent.get("kind") != "ORGAN":
                reason = "PARENT_NOT_ORGAN"
            elif parent.get("repository") != configured.get("repository"):
                reason = "PARENT_REPOSITORY_MISMATCH"
            elif not parent.get("head_sha"):
                reason = "PARENT_EXACT_HEAD_NOT_LOCKED"
            else:
                row["parent_head_sha"] = parent.get("head_sha")
                row["parent_branch"] = parent.get("branch")
                try:
                    manifest = self.reader.json_file(
                        str(parent["repository"]),
                        str(configured["manifest_path"]),
                        ref=str(parent["head_sha"]),
                        allow_missing=True,
                    )
                except Exception as exc:
                    reason = f"CANDIDATE_MANIFEST_READ_ERROR:{type(exc).__name__}"

            if reason is None and manifest is None:
                reason = "CANDIDATE_MANIFEST_MISSING_AT_LOCKED_PARENT_SHA"

            if reason is None and manifest is not None:
                expected_schema = configured.get("expected_schema")
                expected_status = configured.get("expected_status")
                if manifest.get("schema") != expected_schema:
                    reason = "CANDIDATE_MANIFEST_SCHEMA_MISMATCH"
                elif manifest.get("status") != expected_status:
                    reason = "CANDIDATE_MANIFEST_STATUS_MISMATCH"
                elif manifest.get("component") != configured.get("component"):
                    reason = "CANDIDATE_MANIFEST_COMPONENT_MISMATCH"
                elif manifest.get("canonical_runtime_location") != (
                    f"{configured.get('repository')}/{configured.get('manifest_path')}"
                ):
                    reason = "CANDIDATE_CANONICAL_LOCATION_MISMATCH"
                else:
                    activation = manifest.get("activation")
                    if not isinstance(activation, Mapping):
                        reason = "CANDIDATE_ACTIVATION_CONTRACT_MISSING"
                    elif activation.get("wake_allowed") is not True or activation.get("use_allowed") is not True:
                        reason = "CANDIDATE_WAKE_OR_USE_NOT_ALLOWED"
                    elif activation.get("self_improvement_allowed") is not True:
                        reason = "CANDIDATE_SELF_IMPROVEMENT_NOT_ALLOWED"
                    elif not self._authority_false(manifest):
                        reason = "CANDIDATE_AUTHORITY_CEILING_VIOLATION"
                    elif not self._candidate_scientific_boundary_open(manifest):
                        reason = "CANDIDATE_SCIENTIFIC_BOUNDARY_VIOLATION"

            if reason is not None:
                row["admission_status"] = "BLOCKED_FAIL_CLOSED"
                row["blocked_reason"] = reason
                row["wake_allowed"] = False
                row["use_allowed"] = False
                row["self_improvement_allowed"] = False
                row["manifest_hash"] = None
                unavailable.append(tissue_key)
                if required:
                    required_failures.append(tissue_key)
            else:
                assert manifest is not None
                activation = manifest["activation"]
                row.update({
                    "admission_status": "ADMITTED_CANDIDATE_RUNTIME",
                    "manifest_hash": canonical_hash(manifest),
                    "manifest_schema": manifest.get("schema"),
                    "manifest_status": manifest.get("status"),
                    "wake_allowed": True,
                    "use_allowed": True,
                    "self_improvement_allowed": True,
                    "candidate_experiment_allowed": activation.get("candidate_experiment_allowed") is True,
                    "source_count": len(manifest.get("candidate_sources") or []),
                    "algorithmic_spine": list(manifest.get("algorithmic_spine") or []),
                    "scientific_boundary": dict(manifest.get("scientific_boundary") or {}),
                    "law": configured.get("law"),
                })
            tissues[tissue_key] = row

        return tissues, sorted(set(unavailable)), sorted(set(required_failures))

    @staticmethod
    def _augment_capability_index(index: Mapping[str, Any], tissues: Mapping[str, Mapping[str, Any]]) -> Dict[str, Any]:
        emitters = {str(k): list(v) for k, v in (index.get("emitters") or {}).items()}
        consumers = {str(k): list(v) for k, v in (index.get("consumers") or {}).items()}
        for key, row in tissues.items():
            if row.get("admission_status") != "ADMITTED_CANDIDATE_RUNTIME":
                continue
            label = f"candidate_tissue:{key}"
            for payload in row.get("emits") or []:
                emitters.setdefault(str(payload), []).append(label)
            for payload in row.get("consumes") or []:
                consumers.setdefault(str(payload), []).append(label)
        for table in (emitters, consumers):
            for payload, values in table.items():
                table[payload] = sorted(set(values))
        return {
            "emitters": dict(sorted(emitters.items())),
            "consumers": dict(sorted(consumers.items())),
        }

    def compile(self) -> Dict[str, Any]:
        lock = super().compile()
        tissues, unavailable, required_failures = self._bind_candidate_runtime_tissues(lock)
        capability_index = self._augment_capability_index(lock.get("capability_index") or {}, tissues)

        base_model_digest = str(lock["model_digest"])
        digest_tissues = {
            key: {
                "component": row.get("component"),
                "kind": row.get("kind"),
                "parent_organ": row.get("parent_organ"),
                "repository": row.get("repository"),
                "parent_head_sha": row.get("parent_head_sha"),
                "manifest_path": row.get("manifest_path"),
                "manifest_hash": row.get("manifest_hash"),
                "runtime_entrypoint": row.get("runtime_entrypoint"),
                "load_mode": row.get("load_mode"),
                "admission_status": row.get("admission_status"),
                "wake_allowed": row.get("wake_allowed"),
                "use_allowed": row.get("use_allowed"),
                "self_improvement_allowed": row.get("self_improvement_allowed"),
                "proof_authority": False,
                "scientific_claim_promotion_authority": False,
                "command_authority": False,
                "external_effect_authority": False,
                "physical_runtime_effect_authority": False,
                "consumes": row.get("consumes") or [],
                "emits": row.get("emits") or [],
                "scientific_boundary": row.get("scientific_boundary"),
            }
            for key, row in sorted(tissues.items())
        }
        v12_core = {
            "base_model_digest": base_model_digest,
            "candidate_runtime_tissues": digest_tissues,
            "capability_index": capability_index,
            "laws": [
                "CANDIDATE_TRUMP != PROOF_AUTHORIZED_TRUMP",
                "WAKE != THEOREM_AUTHORITY",
                "CANDIDATE_RESULT != SCIENTIFIC_PROMOTION",
            ],
        }
        model_digest = canonical_hash(v12_core)

        failures = dict(lock.get("failures") or {})
        failures["required_candidate_runtime_tissues_invalid"] = required_failures
        fail_closed = bool(required_failures) or lock.get("ready") is not True

        lock.update({
            "model_fabric_version": "1.2",
            "base_model_digest": base_model_digest,
            "model_digest": model_digest,
            "capability_index": capability_index,
            "candidate_runtime_tissues": tissues,
            "candidate_runtime_tissue_count": len(tissues),
            "candidate_tissue_unavailable": unavailable,
            "failures": failures,
            "candidate_runtime_laws": v12_core["laws"],
            "ready": not fail_closed,
        })
        lock["lock_core_hash"] = canonical_hash(v12_core)
        if fail_closed:
            lock["terminal"] = self.manifest["boot_terminal_failure"]
            lock["next_gate"] = "REPAIR_REQUIRED_MODEL_OR_CANDIDATE_TISSUE_DEPENDENCY"
        elif unavailable:
            lock["next_gate"] = "MODEL_READY_WITH_BLOCKED_OPTIONAL_CANDIDATE_TISSUE"
        else:
            lock["next_gate"] = "BIND_COGNITIVE_RUNTIME_AND_WAIT_FOR_FRESH_STIMULUS"
        return lock


__all__ = ["CandidateRuntimeTissueError", "GitHubRepositoryReaderV11", "ModelFabricCompilerV12"]
