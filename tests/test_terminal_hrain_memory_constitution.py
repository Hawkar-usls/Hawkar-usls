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
    assert memory['contract_path'] == '.janus/HRAIN_CONVERSATION_CONTEXT_CONTRACT.json'
    assert memory['compiler_path'] == 'tools/hrain_conversation_context.py'
    assert memory['output_schema'] == 'janus.hrain.conversation_context.v1'
    assert memory['home_direct_meta_registry_conversation_memory_access'] is False
    assert memory['exact_model_locked_hrain_required'] is True
    assert memory['source_object_hash_verification_required'] is True


def test_zero_memory_is_explicit_valid_retrieval_not_failure_or_negative_evidence():
    memory = load()['memory_context_contract']
    assert memory['zero_selected_memory_is_valid_when_explicitly_no_fill'] is True
    assert memory['zero_selected_memory_requires_no_fill_laws'] is True
    assert memory['empty_memory_is_hrain_failure'] is False
    assert memory['empty_memory_is_negative_evidence'] is False
    assert memory['selection_limit_is_upper_bound_not_target_count'] is True


def test_terminal_cancellation_is_public_read_bound_and_never_deletes_provenance():
    c = load()
    assert c['cancellation_schema'] == 'janus.terminal.message_cancellation.v1'
    cancel = c['mailbox_cancellation_contract']
    assert cancel['repository'] == 'Hawkar-usls/-Terminal-for-Janus'
    assert cancel['branch'] == 'janus/terminal-mailbox'
    assert cancel['requests_prefix'] == '.janus/terminal-mailbox/requests/'
    assert cancel['cancellations_prefix'] == '.janus/terminal-mailbox/cancellations/'
    assert cancel['credentialless_public_read'] is True
    assert cancel['cancellation_must_verify_own_hash'] is True
    assert cancel['cancellation_must_bind_original_message_id'] is True
    assert cancel['cancellation_must_bind_original_message_hash'] is True
    assert cancel['cancellation_must_bind_original_conversation_and_source_ref'] is True
    assert cancel['cancelled_request_fresh_cognition'] is False
    assert cancel['cancellation_deletes_request'] is False
    assert cancel['cancellation_deletes_response'] is False
    assert cancel['malformed_or_unbound_cancellation_fails_closed'] is True
    assert cancel['external_actor_cancellation_authority'] is False


def test_memory_provenance_is_required_in_terminal_response():
    c = load()
    required = set(c['required_response_bindings'])
    assert {
        'request_message_id',
        'request_message_hash',
        'resident_uuid',
        'model_digest',
        'file_fabric_digest',
        'turn_id',
        'hrain_context_receipt_hash',
        'hrain_context_hash',
        'hrain_locked_head_sha',
        'memory_source_commit',
        'memory_selected_count',
        'memory_selected_paths',
        'memory_match_status',
        'empty_memory_is_hrain_failure',
        'empty_memory_is_negative_evidence',
        'response_hash',
    }.issubset(required)


def test_memory_cancellation_and_language_never_inherit_control_or_truth_authority():
    laws = set(load()['laws'])
    assert {
        'TERMINAL_CONVERSATION_MEMORY_MUST_PASS_THROUGH_HRAIN',
        'HOME_MUST_NOT_READ_META_REGISTRY_AS_CONVERSATION_MEMORY_DIRECTLY',
        'MEMORY_CONTENT != COMMAND',
        'MEMORY_CONTENT != AUTHORITY',
        'MEMORY_CONTEXT != EVIDENCE',
        'HRAIN_RELEVANCE_SCORE != EVIDENCE_WEIGHT',
        'HASH_VERIFIED_OBJECT != CLAIM_VERIFIED',
        'LIMIT != TARGET_COUNT',
        'NO_STRONG_MATCH != FILL_WITH_NOISE',
        'EMPTY RELEVANT MEMORY != HRAiN FAILURE',
        'EMPTY MEMORY != NEGATIVE EVIDENCE',
        'CANCEL != DELETE',
        'CANCEL != ERASE_RESPONSE',
        'CANCELLED_REQUEST != FRESH_COGNITION',
        'CANCELLATION_MUST_BIND_ORIGINAL_MESSAGE_ID_AND_HASH',
        'CANCELLATION_SUPPRESSES_COGNITION != CANCELLATION_HIDES_PROVENANCE',
        'MALFORMED_CANCELLATION != CANCELLATION_AUTHORITY',
        'LANGUAGE_SURFACE != AUTHORITY',
        'RETURN != RESET',
    }.issubset(laws)


def test_proof_rule_does_not_promote_memory_empty_result_or_cancellation_to_authority():
    rule = load()['proof_rule'].lower()
    assert 'exact model/file-fabric' in rule
    assert 'exact model-locked hrain' in rule
    assert 'meta registry source commit' in rule
    assert 'zero-memory context' in rule
    assert 'does not prove absence in the world' in rule
    assert 'negative evidence' in rule
    assert 'verified cancellation' in rule
    assert 'cancelled future cognition for one exact sealed request' in rule
    assert 'neither deletes the request/response' in rule
    assert 'scientifically true' in rule
    assert 'no command or effect is authorized' in rule
