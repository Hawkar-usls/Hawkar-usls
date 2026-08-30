from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from .activator import canonical_hash
from .trump_candidate import TrumpCandidateError, resolve_trump_candidate

DEFAULT_ROUTING = Path('.janus/activator/ROUTING_TABLE.json')


class TrumpRuntimeError(RuntimeError):
    pass


def _formal_trump_route(routing_path: str | Path = DEFAULT_ROUTING) -> dict[str, Any]:
    table = json.loads(Path(routing_path).read_text(encoding='utf-8'))
    if not isinstance(table, dict):
        raise TrumpRuntimeError('ROUTING_TABLE_OBJECT_REQUIRED')
    for route in table.get('routes') or []:
        if isinstance(route, dict) and route.get('match') == 'formal_or_theorem_claim':
            tissues = route.get('candidate_tissues') or []
            if 'TRUMP' not in tissues:
                raise TrumpRuntimeError('FORMAL_ROUTE_MISSING_TRUMP_CANDIDATE_TISSUE')
            if route.get('candidate_use_allowed') is not True:
                raise TrumpRuntimeError('FORMAL_ROUTE_TRUMP_USE_NOT_ALLOWED')
            if route.get('candidate_proof_authority') is not False:
                raise TrumpRuntimeError('FORMAL_ROUTE_CANDIDATE_PROOF_AUTHORITY_INVALID')
            return dict(route)
    raise TrumpRuntimeError('FORMAL_ROUTE_NOT_FOUND')


def attach_trump_candidate(
    runtime_receipt: Mapping[str, Any],
    *,
    routing_path: str | Path = DEFAULT_ROUTING,
    candidate_context: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Attach bounded TRUMP candidate tissue to an admitted formal JANUS turn.

    This does not mutate the base runtime receipt and does not create a new
    repository member. It only adds a sealed candidate-context overlay for
    internal reasoning / replay / improvement proposal generation.
    """
    if runtime_receipt.get('schema') != 'janus.activator.model_runtime_receipt.v1':
        raise TrumpRuntimeError('MODEL_RUNTIME_RECEIPT_SCHEMA_REQUIRED')
    if runtime_receipt.get('external_effect_authorized') is not False:
        raise TrumpRuntimeError('BASE_RUNTIME_EXTERNAL_EFFECT_AUTHORITY_INVALID')
    if runtime_receipt.get('physical_runtime_effect_authorized') is not False:
        raise TrumpRuntimeError('BASE_RUNTIME_PHYSICAL_EFFECT_AUTHORITY_INVALID')

    matches = {
        str(route.get('match'))
        for route in runtime_receipt.get('route_bindings') or []
        if isinstance(route, dict)
    }
    if 'formal_or_theorem_claim' not in matches:
        return {
            'schema': 'janus.activator.trump_candidate_overlay.v1',
            'attached': False,
            'reason': 'FORMAL_ROUTE_NOT_ACTIVE',
            'base_runtime_receipt_hash': runtime_receipt.get('runtime_receipt_hash'),
            'proof_authority': False,
            'repository_write_authorized': False,
            'external_effect_authorized': False,
            'physical_runtime_effect_authorized': False,
        }

    route = _formal_trump_route(routing_path)
    context = dict(candidate_context or resolve_trump_candidate())
    if context.get('state') != 'CANDIDATE_BOUNDED_RUNTIME_AVAILABLE':
        raise TrumpRuntimeError('TRUMP_CANDIDATE_CONTEXT_NOT_AVAILABLE')
    for key in (
        'repository_write_authorized',
        'claim_promotion_authority',
        'theorem_authority',
        'scientific_evidence_authority',
        'external_effect_authorized',
        'physical_runtime_effect_authorized',
    ):
        if context.get(key) is not False:
            raise TrumpRuntimeError(f'TRUMP_CANDIDATE_AUTHORITY_CEILING_INVALID:{key}')

    overlay = {
        'schema': 'janus.activator.trump_candidate_overlay.v1',
        'attached': True,
        'component': 'TRUMP',
        'mode': 'CANDIDATE_BOUNDED_RUNTIME',
        'base_runtime_receipt_hash': runtime_receipt.get('runtime_receipt_hash'),
        'base_model_digest': runtime_receipt.get('model_digest'),
        'route_match': 'formal_or_theorem_claim',
        'route_organs': list(route.get('organs') or []),
        'candidate_context_hash': context.get('context_hash'),
        'candidate_name': context.get('candidate_name'),
        'research_source': context.get('research_source'),
        'future_runtime': context.get('future_runtime'),
        'allowed_operations': list(context.get('allowed_operations') or []),
        'improvement_proposal_allowed': route.get('candidate_improvement_proposal_allowed') is True,
        'proof_authority': False,
        'repository_write_authorized': False,
        'self_authorized_code_mutation': False,
        'claim_promotion_authority': False,
        'theorem_authority': False,
        'scientific_evidence_authority': False,
        'external_effect_authorized': False,
        'physical_runtime_effect_authorized': False,
        'P_VS_NP': 'OPEN',
        'next_gate': 'TRUMP_CANDIDATE_INTERNAL_REASONING_OR_IMPROVEMENT_PROPOSAL_TO_FUNDAMENTUM',
    }
    overlay['overlay_hash'] = canonical_hash(overlay)
    return overlay


__all__ = ['TrumpRuntimeError', 'attach_trump_candidate']
