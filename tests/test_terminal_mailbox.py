from __future__ import annotations

import copy

import pytest

from janus_spi.terminal_conversation import build_terminal_message
from janus_spi.terminal_mailbox import (
    HOME_REPOSITORY,
    HOME_RESPONSE_BRANCH,
    HOME_RESPONSE_PREFIX,
    TERMINAL_MAILBOX_BRANCH,
    TERMINAL_REPOSITORY,
    TERMINAL_REQUEST_PREFIX,
    TerminalMailboxError,
    next_unanswered_request,
    responded_message_ids,
    terminal_requests,
)


class FakeReader:
    def __init__(self, requests, response_ids=()):
        self.request_values = {
            f"{TERMINAL_REQUEST_PREFIX}{row['message_id']}.json": row
            for row in requests
        }
        self.response_paths = [
            f"{HOME_RESPONSE_PREFIX}{message_id}.response.json"
            for message_id in response_ids
        ]

    def paths(self, repository, branch, prefix):
        if repository == TERMINAL_REPOSITORY and branch == TERMINAL_MAILBOX_BRANCH:
            return sorted(self.request_values)
        if repository == HOME_REPOSITORY and branch == HOME_RESPONSE_BRANCH:
            return sorted(self.response_paths)
        return []

    def json_file(self, repository, path, *, ref):
        return copy.deepcopy(self.request_values[path])


def msg(index, created_at):
    return build_terminal_message(
        conversation_id="issue-1",
        human_actor="Hawkar-usls",
        message_text=f"message {index}",
        source_ref=f"Hawkar-usls/-Terminal-for-Janus#1:comment:{index}",
        created_at=created_at,
    )


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


def test_no_unanswered_request_returns_none():
    first = msg(1, 10.0)
    reader = FakeReader([first], response_ids=[first["message_id"]])
    assert next_unanswered_request(reader) is None


def test_invalid_public_message_fails_closed_instead_of_becoming_prompt():
    value = msg(1, 10.0)
    value["message_text"] = "tampered"
    with pytest.raises(TerminalMailboxError, match="INVALID_TERMINAL_MESSAGE"):
        terminal_requests(FakeReader([value]))
