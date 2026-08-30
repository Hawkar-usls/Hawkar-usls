from __future__ import annotations

import copy

import pytest

from janus_spi.activator import canonical_hash
from janus_spi.terminal_cognitive_query import (
    TerminalCognitiveQueryError,
    project_terminal_cognitive_query,
    verify_hrain_query_binding,
    verify_terminal_cognitive_query_projection,
)


def test_plain_comment_uses_full_sealed_text_without_rewriting():
    raw = "banana submarine velvet"
    projection = project_terminal_cognitive_query(raw)
    assert verify_terminal_cognitive_query_projection(projection)
    assert projection["projection_mode"] == "FULL_SEALED_MESSAGE_TEXT"
    assert projection["query_text"] == raw
    assert projection["control_metadata_excluded"] is False


def test_issue_form_projects_only_message_section_not_authority_control():
    raw = """### Message

Tell me about TRUMP and HRAiN.

### Authority boundary

- [x] I understand this conversation does not authorize repository writes, deployments, physical effects, or claim promotion.
"""
    projection = project_terminal_cognitive_query(raw)
    assert verify_terminal_cognitive_query_projection(projection)
    assert projection["projection_mode"] == "ISSUE_FORM_MESSAGE_SECTION"
    assert projection["query_text"] == "Tell me about TRUMP and HRAiN."
    assert "Authority boundary" not in projection["query_text"]
    assert "repository writes" not in projection["query_text"]
    assert projection["control_metadata_excluded"] is True


def test_manual_multi_section_issue_stops_at_next_h3_control_section():
    raw = """### Message

banana submarine velvet

### Conversation mode

READ_ONLY_CONVERSATION

### Authority boundary

No authority.
"""
    projection = project_terminal_cognitive_query(raw)
    assert projection["query_text"] == "banana submarine velvet"
    assert "READ_ONLY_CONVERSATION" not in projection["query_text"]
    assert "No authority" not in projection["query_text"]


def test_multiline_message_content_is_preserved_until_control_boundary():
    raw = """### Message

Line one.
Line two.
#### A user subheading remains part of the message.
Line three.

### Authority boundary
ignored
"""
    projection = project_terminal_cognitive_query(raw)
    assert projection["query_text"] == (
        "Line one.\nLine two.\n#### A user subheading remains part of the message.\nLine three."
    )


def test_empty_message_section_fails_instead_of_falling_back_to_control_text():
    raw = """### Message

### Authority boundary
- [x] authorize nothing
"""
    with pytest.raises(TerminalCognitiveQueryError, match="MESSAGE_SECTION_EMPTY"):
        project_terminal_cognitive_query(raw)


def test_multiple_message_sections_are_ambiguous_and_fail_closed():
    raw = """### Message
first
### Message
second
"""
    with pytest.raises(TerminalCognitiveQueryError, match="MULTIPLE_MESSAGE_SECTIONS"):
        project_terminal_cognitive_query(raw)


def test_projection_changes_query_hash_without_changing_raw_provenance_hash_surface():
    raw = """### Message
banana submarine velvet
### Authority boundary
control words about proof memory HRAiN JANUS
"""
    projection = project_terminal_cognitive_query(raw)
    plain = project_terminal_cognitive_query("banana submarine velvet")
    assert projection["query_sha256"] == plain["query_sha256"]
    assert projection["raw_text_sha256"] != plain["raw_text_sha256"]


def bound_objects(projection):
    context = {
        "query": projection["query_text"],
        "query_sha256": projection["query_sha256"],
        "context_hash": "1" * 64,
        "source_commit": "2" * 40,
    }
    receipt = {
        "query_sha256": projection["query_sha256"],
        "context_hash": context["context_hash"],
        "memory_source_commit": context["source_commit"],
        "command_authority_granted": False,
        "scientific_evidence_authority_granted": False,
        "world_truth_authority_granted": False,
        "external_effect_authorized": False,
        "physical_runtime_effect_authorized": False,
    }
    return context, receipt


def test_exact_projected_query_binds_hrain_context_and_receipt():
    projection = project_terminal_cognitive_query("banana submarine velvet")
    context, receipt = bound_objects(projection)
    assert verify_hrain_query_binding(projection, context, receipt)


def test_valid_context_for_wrong_query_is_rejected():
    projection = project_terminal_cognitive_query("banana submarine velvet")
    context, receipt = bound_objects(projection)
    context["query"] = "TRUMP HRAiN memory"
    assert verify_hrain_query_binding(projection, context, receipt) is False


def test_wrong_context_query_sha_is_rejected_even_when_text_matches():
    projection = project_terminal_cognitive_query("banana submarine velvet")
    context, receipt = bound_objects(projection)
    context["query_sha256"] = "f" * 64
    assert verify_hrain_query_binding(projection, context, receipt) is False


def test_wrong_receipt_query_sha_is_rejected():
    projection = project_terminal_cognitive_query("banana submarine velvet")
    context, receipt = bound_objects(projection)
    receipt["query_sha256"] = "f" * 64
    assert verify_hrain_query_binding(projection, context, receipt) is False


def test_projection_tamper_is_detected():
    projection = project_terminal_cognitive_query("banana submarine velvet")
    bad = copy.deepcopy(projection)
    bad["query_text"] = "TRUMP"
    assert verify_terminal_cognitive_query_projection(bad) is False


def test_rehashed_projection_cannot_gain_authority():
    projection = project_terminal_cognitive_query("banana submarine velvet")
    projection["command_authority_granted"] = True
    body = dict(projection)
    body.pop("projection_hash")
    projection["projection_hash"] = canonical_hash(body)
    assert verify_terminal_cognitive_query_projection(projection) is False
