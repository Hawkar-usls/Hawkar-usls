from __future__ import annotations

import json
from pathlib import Path

import pytest

from janus_spi.trump_candidate import TrumpCandidateError, resolve_trump_candidate
from janus_spi.trump_runtime import TrumpRuntimeError, attach_trump_candidate

ROOT = Path(__file__).resolve().parents[1]


def no_manifest(_url: str):
    return 404, b''


def candidate_manifest(_url: str):
    return 200, json.dumps({'schema':'trump.manifest.test','status':'CANDIDATE_ONLY'}).encode()


def test_missing_release_manifest_does_not_block_candidate_runtime():
    ctx = resolve_trump_candidate(fetch=no_manifest)
    assert ctx['state'] == 'CANDIDATE_BOUNDED_RUNTIME_AVAILABLE'
    assert ctx['future_runtime']['state'] == 'FUTURE_RELEASE_MANIFEST_ABSENT'
    assert ctx['improvement_proposal_allowed'] is True
    assert ctx['repository_write_authorized'] is False
    assert ctx['theorem_authority'] is False
    assert ctx['P_VS_NP'] if 'P_VS_NP' in ctx else ctx['claim_state'] == 'OPEN'


def test_manifest_presence_alone_never_upgrades_proof_authority():
    ctx = resolve_trump_candidate(fetch=candidate_manifest)
    assert ctx['future_runtime']['manifest_present'] is True
    assert ctx['future_runtime']['proof_authorized_release'] is False
    assert ctx['theorem_authority'] is False
    assert ctx['claim_promotion_authority'] is False


def test_candidate_link_must_preserve_open_scientific_boundary(tmp_path):
    link = json.loads((ROOT / '.janus/activator/JANUS_PNP_BOUNDARY_CERTIFICATE_ELIMINATION_CANDIDATE_LINK.json').read_text())
    link['claim_state'] = 'PROVED'
    path = tmp_path / 'bad.json'
    path.write_text(json.dumps(link), encoding='utf-8')
    with pytest.raises(TrumpCandidateError, match='P_VS_NP_BOUNDARY_MISMATCH'):
        resolve_trump_candidate(candidate_link_path=path, fetch=no_manifest)


def runtime_receipt(match='formal_or_theorem_claim'):
    return {
        'schema':'janus.activator.model_runtime_receipt.v1',
        'runtime_receipt_hash':'a'*64,
        'model_digest':'b'*64,
        'route_bindings':[{'match':match,'bindings':[]}],
        'external_effect_authorized':False,
        'physical_runtime_effect_authorized':False,
    }


def test_formal_turn_attaches_trump_as_candidate_overlay_not_member():
    ctx = resolve_trump_candidate(fetch=no_manifest)
    overlay = attach_trump_candidate(runtime_receipt(), candidate_context=ctx)
    assert overlay['attached'] is True
    assert overlay['component'] == 'TRUMP'
    assert overlay['mode'] == 'CANDIDATE_BOUNDED_RUNTIME'
    assert overlay['improvement_proposal_allowed'] is True
    assert overlay['proof_authority'] is False
    assert overlay['repository_write_authorized'] is False
    assert overlay['P_VS_NP'] == 'OPEN'
    assert overlay['overlay_hash']


def test_nonformal_turn_does_not_attach_trump():
    overlay = attach_trump_candidate(runtime_receipt('human_read_only_conversation'), candidate_context={})
    assert overlay['attached'] is False
    assert overlay['reason'] == 'FORMAL_ROUTE_NOT_ACTIVE'


def test_candidate_context_cannot_smuggle_authority():
    ctx = resolve_trump_candidate(fetch=no_manifest)
    ctx['repository_write_authorized'] = True
    with pytest.raises(TrumpRuntimeError, match='TRUMP_CANDIDATE_AUTHORITY_CEILING_INVALID'):
        attach_trump_candidate(runtime_receipt(), candidate_context=ctx)
