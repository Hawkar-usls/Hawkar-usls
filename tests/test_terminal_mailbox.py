from __future__ import annotations

import copy

import pytest

from janus_spi.activator import canonical_hash
from janus_spi.terminal_conversation import build_terminal_message
from janus_spi.terminal_mailbox import (
    HOME_REPOSITORY,
    HOME_RESPONSE_BRANCH,
    HOME_RESPONSE_PREFIX,
    TERMINAL_CANCELLATION_PREFIX,
    TERMINAL_MAILBOX_BRANCH,
    TERMINAL_REPOSITORY,
    TERMINAL_REQUEST_PREFIX,
    TerminalMailboxError,
    mailbox_selection,
    next_unanswered_request,
    responded_message_ids,
    terminal_cancellations,
    terminal_requests,
    verify_terminal_cancellation,
)


class FakeReader:
    def __init__(self, requests, response_ids=(), cancellations=(), cancellation_path_overrides=None):
        self.request_values = {
            f"{TERMINAL_REQUEST_PREFIX}{row['message_id']}.json": copy.deepcopy(row)
            for row in requests
        }
        self.response_paths = [
            f"{HOME_RESPONSE_PREFIX}{message_id}.response.json"
            for message_id in response_ids
        ]
        self.cancellation_values = {}
        overrides = dict(cancellation_path_overrides or {})
        for row in cancellations:
            message_id = row["message_id"]
            path = overrides.get(message_id, f"{TERMINAL_CANCELLATION_PREFIX}{message_id}.json")
            self.cancellation_values[path] = copy.deepcopy(row)

    def paths(self, repository, branch, prefix):
        if repository == TERMINAL_REPOSITORY and branch == TERMINAL_MAILBOX_BRANCH:
            if prefix == TERMINAL_REQUEST_PREFIX:
                return sorted(self.request_values)
            if prefix == TERMINAL_CANCELLATION_PREFIX:
                return sorted(self.cancellation_values)
        if repository == HOME_REPOSITORY and branch == HOME_RESPONSE_BRANCH:
            return sorted(self.response_paths)
        return []

    def json_file(self, repository, path, *, ref):
        if path in self.request_values:
            return copy.deepcopy(self.request_values[path])
        if path in self.cancellation_values:
            return copy.deepcopy(self.cancellation_values[path])
        raise KeyError(path)


def msg(index, created_at):
    return build_terminal_message(
        conversation_id="issue-1",
        human_actor="Hawkar-usls",
        message_text=f"message {index}",
        source_ref=f"Hawkar-usls/-Terminal-for-Janus#1:comment:{index}",
        created_at=created_at,
    )


def cancellation(request, *, cancelled_at=30.0, actor="Hawkar-usls", message_hash=None):
    identity = {
        "terminal_repository": TERMINAL_REPOSITORY,
        "message_id": request["message_id"],
        "message_hash": request["message_hash"] if message_hash is None else message_hash,
        "conversation_id": request["conversation_id"],
        "source_ref": request["source_ref"],
        "cancelled_by": actor,
        "cancelled_at": cancelled_at,
        "reason": "ISSUE_CLOSED_BY_ADMITTED_HUMAN",
    }
    value = {
        "schema": "janus.terminal.message_cancellation.v1",
        "cancellation_id": "tc-" + canonical_hash(identity),
        **identity,
        "request_deleted": False,
        "response_deleted": False,
        "cognition_authorized": False,
        "command_authority_granted": False,
        "claim_authority_granted": False,
        "scientific_evidence_authority_granted": False,
        "world_truth_authority_granted": False,
        "external_effect_authorized": False,
        "physical_runtime_effect_authorized": False,
        "terminal": "TERMINAL_MESSAGE_CANCELLATION_TOMBSTONE_READY",
        "laws": [
            "CANCEL != DELETE",
            "CANCEL != ERASE_RESPONSE",
            "CANCELLED_REQUEST != FRESH_COGNITION",
            "CANCELLATION != COMMAND_AUTHORITY",
        ],
    }
    value["cancellation_hash"] = canonical_hash(value)
    return value


def test_requests_are_verified_and_ordered_by_created_at():
    later = msg(2, 20.0)
    earlier = msg(1, 10.0)
    rows = terminal_requests(FakeReader([later, earlier]))
    assert [row["message_id"] for row in rows] == [earlier["message_id"], later["message_id"]]


def test_next_unanswered_skips_create_only_response_path():
    first = msg(1, 10.0)
    second = msg(2, 20.0)
    reader = FakeReader([first, second], response_ids=[first["message_id"]])
    assert responded_message_ids(reader) == {first["message_id"]}
    assert next_unanswered_request(reader)["message_id"] == second["message_id"]


def test_valid_cancellation_suppresses_cognition_but_request_remains_in_provenance():
    first = msg(1, 10.0)
    second = msg(2, 20.0)
    tombstone = cancellation(first)
    reader = FakeReader([first, second], cancellations=[tombstone])
    assert verify_terminal_cancellation(tombstone)
    assert [row["message_id"] for row in terminal_requests(reader)] == [first["message_id"], second["message_id"]]
    assert set(terminal_cancellations(reader)) == {first["message_id"]}
    assert next_unanswered_request(reader)["message_id"] == second["message_id"]
    selection = mailbox_selection(reader)
    assert selection["cancelled_message_ids"] == [first["message_id"]]
    assert selection["cancellation_count"] == 1
    assert "CANCELLED_REQUEST != FRESH_COGNITION" in selection["laws"]


def test_cancellation_after_existing_response_erases_neither_response_nor_request():
    first = msg(1, 10.0)
    second = msg(2, 20.0)
    reader = FakeReader(
        [first, second],
        response_ids=[first["message_id"]],
        cancellations=[cancellation(first)],
    )
    selection = mailbox_selection(reader)
    assert first["message_id"] in selection["responded_message_ids"]
    assert first["message_id"] in selection["cancelled_message_ids"]
    assert [row["message_id"] for row in terminal_requests(reader)][0] == first["message_id"]
    assert next_unanswered_request(reader)["message_id"] == second["message_id"]


def test_standalone_valid_but_wrong_message_hash_cancellation_fails_binding_gate():
    first = msg(1, 10.0)
    bad = cancellation(first, message_hash="f" * 64)
    assert verify_terminal_cancellation(bad)
    with pytest.raises(TerminalMailboxError, match="REQUEST_BINDING_MISMATCH"):
        mailbox_selection(FakeReader([first], cancellations=[bad]))


def test_unbound_cancellation_cannot_suppress_unrelated_request():
    first = msg(1, 10.0)
    unrelated = msg(99, 99.0)
    tombstone = cancellation(unrelated)
    with pytest.raises(TerminalMailboxError, match="UNBOUND_REQUEST"):
        mailbox_selection(FakeReader([first], cancellations=[tombstone]))


def test_cancellation_filename_must_bind_message_id():
    first = msg(1, 10.0)
    tombstone = cancellation(first)
    wrong_path = TERMINAL_CANCELLATION_PREFIX + "tm-wrong.json"
    reader = FakeReader(
        [first],
        cancellations=[tombstone],
        cancellation_path_overrides={first["message_id"]: wrong_path},
    )
    with pytest.raises(TerminalMailboxError, match="FILENAME_ID_MISMATCH"):
        mailbox_selection(reader)


def test_external_actor_tombstone_is_invalid_and_cannot_suppress_request():
    first = msg(1, 10.0)
    bad = cancellation(first, actor="external-user")
    assert verify_terminal_cancellation(bad) is False
    with pytest.raises(TerminalMailboxError, match="INVALID_TERMINAL_CANCELLATION"):
        mailbox_selection(FakeReader([first], cancellations=[bad]))


def test_rehashed_tombstone_cannot_gain_cognition_authority():
    first = msg(1, 10.0)
    bad = cancellation(first)
    bad["cognition_authorized"] = True
    body = dict(bad)
    body.pop("cancellation_hash")
    bad["cancellation_hash"] = canonical_hash(body)
    assert verify_terminal_cancellation(bad) is False


def test_no_unanswered_request_returns_none_when_responded_or_cancelled():
    first = msg(1, 10.0)
    reader = FakeReader([first], cancellations=[cancellation(first)])
    assert next_unanswered_request(reader) is None


def test_invalid_public_message_fails_closed_instead_of_becoming_prompt():
    value = msg(1, 10.0)
    value["message_text"] = "tampered"
    with pytest.raises(TerminalMailboxError, match="INVALID_TERMINAL_MESSAGE"):
        terminal_requests(FakeReader([value]))
