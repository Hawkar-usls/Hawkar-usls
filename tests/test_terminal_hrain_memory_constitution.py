from __future__ import annotations

import json
from pathlib import Path


CONSTITUTION = Path('.janus/activator/TERMINAL_CONVERSATION_CONSTITUTION.json')


def load():
    return json.loads(CONSTITUTION.read_text(encoding='utf-8'))


def test_terminal_conversation_memory_path_is_hrain_mediated():
    c = load()
    assert c['schema'] == 'janus.activator.terminal_conversation_constitution.v1'
    assert c['status'] == 'READ_ONLY_HRAIN_MEMORY_BOUND_HUMAN_CONVERSATION_PROOF_CONTRACT'
    assert c['memory_path'] == 'META_REGISTRY_DB -> HRAIN -> JANUS -> TERMINAL'
    memory = c['memory_context_contract']
    assert memory['repository'] == 'Hawkar-usls/Hrain'
    assert memory['home_direct_meta_registry_conversation_memory_access'] is False
    assert memory['exact_model_locked_hrain_required'] is True
    assert memory['source_object_hash_verification_required'] is True


def test_control_metadata_is_not_cognitive_query_and_projection_binds_hrain():
    c = load()
    assert c['cognitive_query_projection_schema'] == 'janus.terminal.cognitive_query_projection.v1'
    query = c['cognitive_query_contract']
    assert query['projection_owner'] == 'JANUS_HOME_COGNITIVE_GATEWAY'
    assert query['sealed_request_is_mutated'] is False
    assert query['plain_message_mode'] == 'FULL_SEALED_MESSAGE_TEXT'
    assert query['issue_form_mode'] == 'ISSUE_FORM_MESSAGE_SECTION'
    assert query['issue_form_message_heading'] == '### Message'
    assert query['issue_form_control_boundary'] == 'NEXT_H3_SECTION'
    assert query['empty_message_section_falls_back_to_control_text'] is False
    assert query['multiple_message_sections_allowed'] is False
    assert query['projection_hash_required'] is True
    assert query['query_sha256_required'] is True
    assert query['hrain_context_query_text_must_match_projection'] is True
    assert query['hrain_context_query_sha256_must_match_projection'] is True
    assert query['hrain_receipt_query_sha256_must_match_projection'] is True
    assert query['projection_grants_authority'] is False
    assert query['historical_sealed_response_replay_requires_reprojection'] is False


def test_zero_memory_is_explicit_valid_retrieval_not_failure_or_negative_evidence():
    memory = load()['memory_context_contract']
    assert memory['zero_selected_memory_is_valid_when_explicitly_no_fill'] is True
    assert memory['empty_memory_is_hrain_failure'] is False
    assert memory['empty_memory_is_negative_evidence'] is False
    assert memory['selection_limit_is_upper_bound_not_target_count'] is True


def test_terminal_cancellation_is_public_read_bound_and_never_deletes_provenance():
    cancel = load()['mailbox_cancellation_contract']
    assert cancel['credentialless_public_read'] is True
    assert cancel['cancellation_must_verify_own_hash'] is True
    assert cancel['cancellation_must_bind_original_message_id'] is True
    assert cancel['cancellation_must_bind_original_message_hash'] is True
    assert cancel['cancelled_request_fresh_cognition'] is False
    assert cancel['cancellation_deletes_request'] is False
    assert cancel['cancellation_deletes_response'] is False
    assert cancel['malformed_or_unbound_cancellation_fails_closed'] is True
    assert cancel['external_actor_cancellation_authority'] is False


def test_memory_and_query_provenance_are_required_in_terminal_response():
    required = set(load()['required_response_bindings'])
    assert {
        'request_message_id',
        'request_message_hash',
        'resident_uuid',
        'model_digest',
        'file_fabric_digest',
        'turn_id',
        'cognitive_query_projection_hash',
        'cognitive_query_sha256',
        'cognitive_query_projection_mode',
        'control_metadata_excluded_from_cognitive_query',
        'hrain_context_receipt_hash',
        'hrain_context_hash',
        'hrain_locked_head_sha',
        'memory_source_commit',
        'memory_selected_count',
        'memory_selected_paths',
        'memory_match_status',
        'response_hash',
    }.issubset(required)


def test_query_memory_cancellation_and_language_laws_are_frozen():
    laws = set(load()['laws'])
    assert 'CONTROL_METADATA != COGNITIVE_QUERY' in laws
    assert 'SEALED_REQUEST_PROVENANCE != COGNITIVE_QUERY_SURFACE' in laws
    assert 'EMPTY_MESSAGE_SECTION != FALLBACK_TO_CONTROL_TEXT' in laws
    assert 'COGNITIVE_PROJECTION != AUTHORITY' in laws
    assert 'VALID_CONTEXT_FOR_WRONG_QUERY != VALID_TURN' in laws
    assert 'NEW_INPUT_GRAMMAR != INVALIDATE_OLD_RESPONSE' in laws
    assert 'TERMINAL_CONVERSATION_MEMORY_MUST_PASS_THROUGH_HRAIN' in laws
    assert 'HOME_MUST_NOT_READ_META_REGISTRY_AS_CONVERSATION_MEMORY_DIRECTLY' in laws
    assert 'EMPTY RELEVANT MEMORY != HRAiN FAILURE' in laws
    assert 'EMPTY MEMORY != NEGATIVE EVIDENCE' in laws
    assert 'CANCEL != DELETE' in laws
    assert 'CANCELLED_REQUEST != FRESH_COGNITION' in laws
    assert 'MALFORMED_CANCELLATION != CANCELLATION_AUTHORITY' in laws
    assert 'RETURN != RESET' in laws


def test_proof_rule_binds_projected_query_without_promoting_it_to_authority():
    rule = load()['proof_rule'].lower()
    assert 'preserved the sealed request as provenance' in rule
    assert 'bounded cognitive query' in rule
    assert 'exact model-locked hrain context and receipt to bind that exact query sha' in rule
    assert 'control metadata excluded by the projection' in rule
    assert 'meta registry source commit' in rule
    assert 'zero-memory context' in rule
    assert 'verified cancellation' in rule
    assert 'scientifically true' in rule
    assert 'no command or effect is authorized' in rule
