from __future__ import annotations

import json
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable, Mapping

from .activator import canonical_hash

CANDIDATE_LINK = Path('.janus/activator/JANUS_PNP_BOUNDARY_CERTIFICATE_ELIMINATION_CANDIDATE_LINK.json')
CONTRACT_PATH = Path('.janus/activator/TRUMP_CANDIDATE_RUNTIME_CONTRACT.json')
FUTURE_MANIFEST_URL = 'https://raw.githubusercontent.com/Hawkar-usls/Janus-Demiurge/main/trump/TRUMP_MANIFEST.json'


class TrumpCandidateError(RuntimeError):
    pass


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(value, dict):
        raise TrumpCandidateError(f'JSON_OBJECT_REQUIRED:{path}')
    return value


def _default_fetch(url: str) -> tuple[int, bytes]:
    try:
        with urllib.request.urlopen(url, timeout=15) as response:
            return int(getattr(response, 'status', 200)), response.read()
    except urllib.error.HTTPError as exc:
        return int(exc.code), b''
    except (TimeoutError, OSError, urllib.error.URLError) as exc:
        raise TrumpCandidateError(f'FUTURE_MANIFEST_READ_UNRESOLVED:{type(exc).__name__}') from exc


def _validate_candidate_link(link: Mapping[str, Any]) -> None:
    if link.get('schema') != 'janus.activator.theorem_candidate_link.v1.0':
        raise TrumpCandidateError('CANDIDATE_LINK_SCHEMA_MISMATCH')
    if link.get('status') != 'CANDIDATE_OPEN_NOT_AUTHORITY':
        raise TrumpCandidateError('CANDIDATE_LINK_STATUS_NOT_ADMITTED')
    if link.get('claim_target') != 'P_VS_NP' or link.get('claim_state') != 'OPEN':
        raise TrumpCandidateError('P_VS_NP_BOUNDARY_MISMATCH')
    source = link.get('source')
    if not isinstance(source, dict) or source.get('repository') != 'Hawkar-usls/Janus-Fundamentum':
        raise TrumpCandidateError('CANDIDATE_RESEARCH_SOURCE_MISMATCH')
    authority = link.get('authority')
    if not isinstance(authority, dict):
        raise TrumpCandidateError('CANDIDATE_AUTHORITY_REQUIRED')
    for key in ('activation_promotable', 'dispatch_authorized', 'effect_authorized', 'theorem_authority', 'model_output_is_proof'):
        if authority.get(key) is not False:
            raise TrumpCandidateError(f'CANDIDATE_AUTHORITY_CEILING_INVALID:{key}')


def _inspect_future_manifest(fetch: Callable[[str], tuple[int, bytes]]) -> dict[str, Any]:
    status, body = fetch(FUTURE_MANIFEST_URL)
    if status == 404:
        return {
            'state': 'FUTURE_RELEASE_MANIFEST_ABSENT',
            'manifest_present': False,
            'proof_authorized_release': False,
            'manifest_hash': None,
        }
    if status != 200:
        return {
            'state': 'FUTURE_RELEASE_MANIFEST_READ_UNRESOLVED',
            'manifest_present': False,
            'proof_authorized_release': False,
            'manifest_hash': None,
            'http_status': status,
        }
    try:
        manifest = json.loads(body.decode('utf-8'))
    except Exception as exc:
        raise TrumpCandidateError('FUTURE_MANIFEST_INVALID_JSON') from exc
    if not isinstance(manifest, dict):
        raise TrumpCandidateError('FUTURE_MANIFEST_OBJECT_REQUIRED')
    # Presence alone never upgrades authority. A separate release-proof reconciler
    # must validate exact Fundamentum receipts before a released runtime can exist.
    return {
        'state': 'FUTURE_RELEASE_MANIFEST_PRESENT_REQUIRES_PROOF_RECONCILIATION',
        'manifest_present': True,
        'proof_authorized_release': False,
        'manifest_hash': canonical_hash(manifest),
        'declared_status': manifest.get('status'),
    }


def resolve_trump_candidate(
    *,
    candidate_link_path: str | Path = CANDIDATE_LINK,
    contract_path: str | Path = CONTRACT_PATH,
    fetch: Callable[[str], tuple[int, bytes]] = _default_fetch,
) -> dict[str, Any]:
    contract = _read_json(Path(contract_path))
    link = _read_json(Path(candidate_link_path))
    _validate_candidate_link(link)

    if contract.get('status') != 'CANDIDATE_RUNTIME_ALLOWED__PROOF_AUTHORITY_SEPARATE':
        raise TrumpCandidateError('TRUMP_CANDIDATE_CONTRACT_NOT_ADMITTED')
    component = contract.get('component')
    if not isinstance(component, dict) or component.get('candidate_runtime_allowed') is not True:
        raise TrumpCandidateError('TRUMP_CANDIDATE_RUNTIME_NOT_ALLOWED')
    boundary = contract.get('scientific_boundary')
    if not isinstance(boundary, dict) or boundary.get('P_VS_NP') != 'OPEN' or boundary.get('P_equals_NP_proved') is not False:
        raise TrumpCandidateError('TRUMP_SCIENTIFIC_BOUNDARY_INVALID')

    future = _inspect_future_manifest(fetch)
    source = dict(link['source'])
    context = {
        'schema': 'janus.activator.trump_candidate_context.v1',
        'component': 'TRUMP',
        'state': 'CANDIDATE_BOUNDED_RUNTIME_AVAILABLE',
        'candidate_name': link.get('candidate'),
        'claim_target': 'P_VS_NP',
        'claim_state': 'OPEN',
        'research_source': {
            'repository': source.get('repository'),
            'branch': source.get('branch'),
            'candidate_commit': source.get('candidate_commit'),
            'result_receipt_commit': source.get('result_receipt_commit'),
            'process_journal_commit': source.get('process_journal_commit'),
            'workflow_run_id': source.get('workflow_run_id'),
            'artifact_id': source.get('artifact_id'),
            'artifact_sha256': source.get('artifact_sha256'),
        },
        'future_runtime': {
            'manifest_url': FUTURE_MANIFEST_URL,
            **future,
        },
        'allowed_operations': list(contract.get('candidate_operations') or []),
        'improvement_proposal_allowed': True,
        'repository_write_authorized': False,
        'self_authorized_code_mutation': False,
        'claim_promotion_authority': False,
        'theorem_authority': False,
        'scientific_evidence_authority': False,
        'external_effect_authorized': False,
        'physical_runtime_effect_authorized': False,
        'lineage_memory_repository': 'Hawkar-usls/janus-meta-registry',
        'lineage_memory_through_hrain': True,
        'next_gate': 'USE_CANDIDATE_FOR_INTERNAL_REASONING_AND_ROUTE_IMPROVEMENT_PROPOSALS_TO_FUNDAMENTUM',
        'laws': list(contract.get('laws') or []),
    }
    context['context_hash'] = canonical_hash(context)
    return context


__all__ = ['TrumpCandidateError', 'resolve_trump_candidate']
