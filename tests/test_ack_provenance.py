from __future__ import annotations

import io
import json
import stat
import urllib.parse
import zipfile
from pathlib import Path

import pytest

from janus_spi.ack import JanusAckReconciler
from janus_spi.ack_provenance import (
    HANDLER_BLOB_SHA,
    HANDLER_PATH,
    PROTOCOL_BLOB_SHA,
    PROTOCOL_PATH,
    REPOSITORY,
    WORKFLOW_BLOB_SHA,
    WORKFLOW_ID,
    WORKFLOW_PATH,
    GitHubAckProvenanceVerifier,
    JanusAuthenticatedAckFinalizer,
)
from janus_spi.activator import ActivationEvent, JanusActivator, canonical_hash
from janus_spi.dispatch import JanusDispatchBroker
from janus_spi.transport import JanusTransportBroker


RUN_ID = 424242
HEAD_SHA = "1" * 40


class FakeResponse:
    def __init__(self, status=204):
        self.status = status


class FakeOpener:
    def __init__(self, *, status=204, error=None):
        self.status = status
        self.error = error

    def __call__(self, request, timeout=20.0):
        if self.error is not None:
            raise self.error
        return FakeResponse(self.status)


class FakeGitHubReader:
    def __init__(self, *, run=None, blobs=None, artifacts=None, archive=None, error_url_contains=None):
        self.run = run or valid_run()
        self.blobs = blobs or {
            WORKFLOW_PATH: WORKFLOW_BLOB_SHA,
            PROTOCOL_PATH: PROTOCOL_BLOB_SHA,
            HANDLER_PATH: HANDLER_BLOB_SHA,
        }
        self.artifacts = artifacts if artifacts is not None else valid_artifacts()
        self.archive = archive if archive is not None else make_zip(make_ack({"packet_id": "dsp-" + "a" * 64, "packet_hash": "b" * 64}))
        self.error_url_contains = error_url_contains
        self.calls = []

    def _maybe_error(self, url):
        self.calls.append(url)
        if self.error_url_contains and self.error_url_contains in url:
            raise OSError("synthetic provenance fetch failure")

    def get_json(self, url):
        self._maybe_error(url)
        parsed = urllib.parse.urlparse(url)
        path = parsed.path
        if path.endswith(f"/actions/runs/{RUN_ID}"):
            return self.run
        if "/contents/" in path:
            repo_prefix = f"/repos/{REPOSITORY}/contents/"
            rel = urllib.parse.unquote(path.split(repo_prefix, 1)[1])
            return {"type": "file", "sha": self.blobs.get(rel)}
        if path.endswith(f"/actions/runs/{RUN_ID}/artifacts"):
            return {"total_count": len(self.artifacts), "artifacts": self.artifacts}
        raise AssertionError(f"Unexpected JSON URL: {url}")

    def get_bytes(self, url):
        self._maybe_error(url)
        return self.archive


def valid_run(**overrides):
    run = {
        "id": RUN_ID,
        "repository": {"full_name": REPOSITORY},
        "head_repository": {"full_name": REPOSITORY},
        "workflow_id": WORKFLOW_ID,
        "path": WORKFLOW_PATH,
        "head_sha": HEAD_SHA,
        "head_branch": "main",
        "event": "repository_dispatch",
        "status": "completed",
        "conclusion": "success",
    }
    run.update(overrides)
    return run


def valid_artifacts(**artifact_overrides):
    artifact = {
        "id": 777,
        "name": f"janus-activator-dispatch-ack-{RUN_ID}",
        "expired": False,
        "workflow_run": {"id": RUN_ID},
    }
    artifact.update(artifact_overrides)
    return [artifact]


def make_ack(packet, *, accepted=True, terminal="ACK_ACCEPTED_NO_EXECUTION"):
    ack = {
        "schema": "janus.demiurge.activator_dispatch_ack.v0.1",
        "created_at": 1.0,
        "packet_id": packet["packet_id"],
        "packet_hash": packet["packet_hash"],
        "accepted": accepted,
        "terminal": terminal,
        "reasons": ["receiver test ACK"],
        "execution_authorized": False,
        "execution_performed": False,
        "claim_authority_granted": False,
        "external_effect_authorized": False,
    }
    ack["ack_hash"] = canonical_hash(ack)
    return ack


def reseal_ack(ack):
    ack = dict(ack)
    ack.pop("ack_hash", None)
    ack["ack_hash"] = canonical_hash(ack)
    return ack


def make_zip(ack, *, name="ack.json", second_ack=False, symlink=False):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        if symlink:
            info = zipfile.ZipInfo(name)
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            zf.writestr(info, json.dumps(ack))
        else:
            zf.writestr(name, json.dumps(ack))
        if second_ack:
            zf.writestr("nested/ack.json", json.dumps(ack))
    return output.getvalue()


def make_home_lineage(tmp_path: Path, *, accepted=True, rejected_terminal="ACK_REJECTED_POLICY", ambiguous=False):
    state = tmp_path / "state"
    activation = JanusActivator(state_dir=state).activate(
        ActivationEvent.build(
            source_kind="GITHUB_COMMIT",
            source_ref="Hawkar-usls/janus-meta-registry@provenance-test",
            payload={"kind": "registry_change"},
            classifications=["research_or_anomaly_investigation"],
            fresh=True,
        )
    )
    dispatch = JanusDispatchBroker(state_dir=state).dispatch(
        activation,
        target_organ="Hawkar-usls/Janus-Demiurge",
    )
    packet = json.loads(Path(dispatch["packet_path"]).read_text(encoding="utf-8"))
    transport = JanusTransportBroker(
        state_dir=state,
        opener=FakeOpener(error=TimeoutError("ambiguous") if ambiguous else None),
    ).send(packet, token="unit-test-token")
    ack = make_ack(
        packet,
        accepted=accepted,
        terminal="ACK_ACCEPTED_NO_EXECUTION" if accepted else rejected_terminal,
    )
    structural = JanusAckReconciler(state_dir=state).reconcile(packet, transport, ack)
    return state, packet, transport, ack, structural


def reader_for_ack(ack, **kwargs):
    return FakeGitHubReader(archive=make_zip(ack), **kwargs)


def test_valid_exact_run_artifact_authenticates_source_under_github_trust_model(tmp_path):
    state, packet, transport, ack, structural = make_home_lineage(tmp_path)
    reader = reader_for_ack(ack)
    verifier = GitHubAckProvenanceVerifier(state_dir=state, reader=reader)

    receipt, artifact_ack = verifier.verify_run(RUN_ID, token="test-secret")

    assert receipt["terminal"] == "ACK_SOURCE_AUTHENTICATED_GITHUB_ACTIONS_TRUST_MODEL"
    assert receipt["source_authenticated"] is True
    assert receipt["workflow_blob_sha"] == WORKFLOW_BLOB_SHA
    assert receipt["protocol_blob_sha"] == PROTOCOL_BLOB_SHA
    assert receipt["handler_blob_sha"] == HANDLER_BLOB_SHA
    assert receipt["artifact_id"] == 777
    assert receipt["ack_hash"] == ack["ack_hash"]
    assert artifact_ack == ack
    assert receipt["target_execution_authorized"] is False
    assert receipt["target_execution_inferred"] is False
    assert receipt["scientific_evidence_authority_granted"] is False
    assert "test-secret" not in (state / "ack_provenance_ledger.jsonl").read_text(encoding="utf-8")
    assert verifier.ledger.verify() is True


def test_missing_credential_is_pre_network_and_unauthed(tmp_path):
    reader = reader_for_ack(make_ack({"packet_id": "dsp-" + "a" * 64, "packet_hash": "b" * 64}))
    verifier = GitHubAckProvenanceVerifier(state_dir=tmp_path / "state", reader=reader)
    receipt, ack = verifier.verify_run(RUN_ID, token="")
    assert receipt["terminal"] == "ACK_PROVENANCE_BLOCKED_NO_CREDENTIAL"
    assert receipt["source_authenticated"] is False
    assert ack is None
    assert reader.calls == []


@pytest.mark.parametrize(
    "overrides",
    [
        {"repository": {"full_name": "Other/Repo"}},
        {"workflow_id": WORKFLOW_ID + 1},
        {"path": ".github/workflows/other.yml"},
        {"status": "in_progress", "conclusion": None},
        {"status": "completed", "conclusion": "failure"},
        {"head_sha": "short"},
    ],
)
def test_wrong_run_metadata_is_blocked(tmp_path, overrides):
    reader = reader_for_ack(make_ack({"packet_id": "dsp-" + "a" * 64, "packet_hash": "b" * 64}), run=valid_run(**overrides))
    receipt, _ = GitHubAckProvenanceVerifier(state_dir=tmp_path / "state", reader=reader).verify_run(RUN_ID, token="t")
    assert receipt["terminal"] == "ACK_PROVENANCE_BLOCKED_RUN_METADATA"
    assert receipt["source_authenticated"] is False


def test_push_event_is_not_admitted_as_ack_source(tmp_path):
    reader = reader_for_ack(make_ack({"packet_id": "dsp-" + "a" * 64, "packet_hash": "b" * 64}), run=valid_run(event="push"))
    receipt, _ = GitHubAckProvenanceVerifier(state_dir=tmp_path / "state", reader=reader).verify_run(RUN_ID, token="t")
    assert receipt["terminal"] == "ACK_PROVENANCE_BLOCKED_UNADMITTED_EVENT"


@pytest.mark.parametrize("path", [WORKFLOW_PATH, PROTOCOL_PATH, HANDLER_PATH])
def test_any_pinned_receiver_blob_mismatch_blocks_provenance(tmp_path, path):
    blobs = {
        WORKFLOW_PATH: WORKFLOW_BLOB_SHA,
        PROTOCOL_PATH: PROTOCOL_BLOB_SHA,
        HANDLER_PATH: HANDLER_BLOB_SHA,
    }
    blobs[path] = "0" * 40
    reader = reader_for_ack(make_ack({"packet_id": "dsp-" + "a" * 64, "packet_hash": "b" * 64}), blobs=blobs)
    receipt, _ = GitHubAckProvenanceVerifier(state_dir=tmp_path / "state", reader=reader).verify_run(RUN_ID, token="t")
    assert receipt["terminal"] == "ACK_PROVENANCE_BLOCKED_PIN_MISMATCH"


@pytest.mark.parametrize(
    "artifacts",
    [
        [],
        valid_artifacts() + valid_artifacts(id=778),
        valid_artifacts(expired=True),
        valid_artifacts(workflow_run={"id": RUN_ID + 1}),
    ],
)
def test_missing_duplicate_expired_or_wrong_run_artifact_is_blocked(tmp_path, artifacts):
    reader = reader_for_ack(make_ack({"packet_id": "dsp-" + "a" * 64, "packet_hash": "b" * 64}), artifacts=artifacts)
    receipt, _ = GitHubAckProvenanceVerifier(state_dir=tmp_path / "state", reader=reader).verify_run(RUN_ID, token="t")
    assert receipt["terminal"] == "ACK_PROVENANCE_BLOCKED_ARTIFACT"


@pytest.mark.parametrize(
    "archive",
    [
        b"not-a-zip",
        make_zip(make_ack({"packet_id": "dsp-" + "a" * 64, "packet_hash": "b" * 64}), name="../ack.json"),
        make_zip(make_ack({"packet_id": "dsp-" + "a" * 64, "packet_hash": "b" * 64}), second_ack=True),
        make_zip(make_ack({"packet_id": "dsp-" + "a" * 64, "packet_hash": "b" * 64}), symlink=True),
    ],
)
def test_unsafe_or_ambiguous_ack_archive_is_blocked(tmp_path, archive):
    reader = FakeGitHubReader(archive=archive)
    receipt, _ = GitHubAckProvenanceVerifier(state_dir=tmp_path / "state", reader=reader).verify_run(RUN_ID, token="t")
    assert receipt["terminal"] == "ACK_PROVENANCE_BLOCKED_ARCHIVE"


def test_tampered_ack_inside_exact_artifact_is_blocked(tmp_path):
    ack = make_ack({"packet_id": "dsp-" + "a" * 64, "packet_hash": "b" * 64})
    ack["terminal"] = "TAMPERED"
    reader = FakeGitHubReader(archive=make_zip(ack))
    receipt, _ = GitHubAckProvenanceVerifier(state_dir=tmp_path / "state", reader=reader).verify_run(RUN_ID, token="t")
    assert receipt["terminal"] == "ACK_PROVENANCE_BLOCKED_INVALID_ACK"


def test_fetch_error_stays_unresolved_not_authenticated(tmp_path):
    reader = FakeGitHubReader(error_url_contains="/artifacts")
    receipt, ack = GitHubAckProvenanceVerifier(state_dir=tmp_path / "state", reader=reader).verify_run(RUN_ID, token="t")
    assert receipt["terminal"] == "ACK_PROVENANCE_UNRESOLVED_FETCH_ERROR"
    assert receipt["source_authenticated"] is False
    assert ack is None


def test_authenticated_accepted_ack_finalizes_delivery_not_execution(tmp_path):
    state, packet, transport, ack, structural = make_home_lineage(tmp_path)
    provenance, artifact_ack = GitHubAckProvenanceVerifier(state_dir=state, reader=reader_for_ack(ack)).verify_run(RUN_ID, token="t")
    finalizer = JanusAuthenticatedAckFinalizer(state_dir=state)

    final = finalizer.finalize(structural, provenance)

    assert final["terminal"] == "ACK_AUTHENTICATED_DELIVERY_CONFIRMED_NO_EXECUTION"
    assert final["source_authenticated_under_github_trust_model"] is True
    assert final["delivery_confirmed_under_github_trust_model"] is True
    assert final["target_execution_authorized"] is False
    assert final["target_execution_inferred"] is False
    assert final["target_execution_observed"] is False
    assert final["claim_authority_granted"] is False
    assert final["scientific_evidence_authority_granted"] is False
    assert final["external_effect_authorized"] is False
    assert finalizer.final_ledger.verify() is True


def test_authenticated_rejection_confirms_delivery_and_rejection_not_execution(tmp_path):
    state, packet, transport, ack, structural = make_home_lineage(tmp_path, accepted=False)
    provenance, _ = GitHubAckProvenanceVerifier(state_dir=state, reader=reader_for_ack(ack)).verify_run(RUN_ID, token="t")
    final = JanusAuthenticatedAckFinalizer(state_dir=state).finalize(structural, provenance)
    assert final["terminal"] == "ACK_AUTHENTICATED_REJECTION_CONFIRMED_NO_EXECUTION"
    assert final["delivery_confirmed_under_github_trust_model"] is True
    assert final["target_execution_observed"] is False


def test_authenticated_ack_resolves_prior_transport_delivery_ambiguity_without_replay(tmp_path):
    state, packet, transport, ack, structural = make_home_lineage(tmp_path, ambiguous=True)
    assert transport["terminal"] == "TRANSPORT_OUTCOME_UNDETERMINED"
    assert structural["transport_ambiguity_resolved"] is False
    provenance, _ = GitHubAckProvenanceVerifier(state_dir=state, reader=reader_for_ack(ack)).verify_run(RUN_ID, token="t")
    final = JanusAuthenticatedAckFinalizer(state_dir=state).finalize(structural, provenance)
    assert final["terminal"] == "ACK_AUTHENTICATED_DELIVERY_CONFIRMED_NO_EXECUTION"
    assert final["transport_ambiguity_resolved"] is True
    assert final["target_execution_observed"] is False


def test_source_authenticated_artifact_for_other_ack_cannot_finalize_local_structural_lineage(tmp_path):
    state, packet, transport, ack, structural = make_home_lineage(tmp_path)
    other_ack = dict(ack)
    other_ack["packet_id"] = "dsp-" + "f" * 64
    other_ack = reseal_ack(other_ack)
    provenance, _ = GitHubAckProvenanceVerifier(state_dir=state, reader=reader_for_ack(other_ack)).verify_run(RUN_ID, token="t")
    assert provenance["source_authenticated"] is True
    final = JanusAuthenticatedAckFinalizer(state_dir=state).finalize(structural, provenance)
    assert final["terminal"] == "ACK_AUTHENTICATED_FINALIZATION_BLOCKED_LINEAGE_MISMATCH"
    assert final["delivery_confirmed_under_github_trust_model"] is False


def test_nonlocal_structural_receipt_cannot_finalize(tmp_path):
    state, packet, transport, ack, structural = make_home_lineage(tmp_path)
    provenance, _ = GitHubAckProvenanceVerifier(state_dir=state, reader=reader_for_ack(ack)).verify_run(RUN_ID, token="t")
    fabricated = dict(structural)
    fabricated["reasons"] = ["fabricated structurally valid receipt"]
    fabricated.pop("receipt_hash", None)
    fabricated["receipt_hash"] = canonical_hash(fabricated)
    final = JanusAuthenticatedAckFinalizer(state_dir=state).finalize(fabricated, provenance)
    assert final["terminal"] == "ACK_AUTHENTICATED_FINALIZATION_BLOCKED_STRUCTURAL_RECEIPT_NOT_LOCAL"


def test_nonlocal_provenance_receipt_cannot_finalize(tmp_path):
    state, packet, transport, ack, structural = make_home_lineage(tmp_path)
    provenance, _ = GitHubAckProvenanceVerifier(state_dir=state, reader=reader_for_ack(ack)).verify_run(RUN_ID, token="t")
    fabricated = dict(provenance)
    fabricated["reasons"] = ["fabricated provenance receipt"]
    fabricated.pop("receipt_hash", None)
    fabricated["receipt_hash"] = canonical_hash(fabricated)
    final = JanusAuthenticatedAckFinalizer(state_dir=state).finalize(structural, fabricated)
    assert final["terminal"] == "ACK_AUTHENTICATED_FINALIZATION_BLOCKED_PROVENANCE_RECEIPT_NOT_LOCAL"


def test_blocked_provenance_receipt_cannot_finalize(tmp_path):
    state, packet, transport, ack, structural = make_home_lineage(tmp_path)
    blocked, _ = GitHubAckProvenanceVerifier(state_dir=state, reader=reader_for_ack(ack, run=valid_run(event="push"))).verify_run(RUN_ID, token="t")
    final = JanusAuthenticatedAckFinalizer(state_dir=state).finalize(structural, blocked)
    assert final["terminal"] == "ACK_AUTHENTICATED_FINALIZATION_BLOCKED_SOURCE_UNAUTHENTICATED"


def test_duplicate_authenticated_finalization_is_idempotent(tmp_path):
    state, packet, transport, ack, structural = make_home_lineage(tmp_path)
    provenance, _ = GitHubAckProvenanceVerifier(state_dir=state, reader=reader_for_ack(ack)).verify_run(RUN_ID, token="t")
    finalizer = JanusAuthenticatedAckFinalizer(state_dir=state)
    first = finalizer.finalize(structural, provenance)
    second = finalizer.finalize(structural, provenance)
    assert first["terminal"] == "ACK_AUTHENTICATED_DELIVERY_CONFIRMED_NO_EXECUTION"
    assert second["terminal"] == "ACK_AUTHENTICATED_FINALIZATION_ALREADY_RECORDED"
    assert first["finalization_id"] == second["finalization_id"]
    assert second["target_execution_observed"] is False
