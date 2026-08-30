from __future__ import annotations

import hashlib
from typing import Any, Dict

from .activator import canonical_hash

PROJECTION_SCHEMA = "janus.terminal.cognitive_query_projection.v1"
ISSUE_FORM_MESSAGE_HEADING = "### Message"


class TerminalCognitiveQueryError(RuntimeError):
    pass


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def project_terminal_cognitive_query(message_text: str) -> Dict[str, Any]:
    """Project one sealed Terminal text into the bounded HRAiN query surface.

    The sealed request remains the provenance object. For GitHub issue-form
    bodies, only the `### Message` section is cognitive input; subsequent H3
    form/control sections are excluded. Plain comments/messages without that
    marker remain fully cognitive text.
    """
    raw = str(message_text)
    if not raw.strip():
        raise TerminalCognitiveQueryError("TERMINAL_COGNITIVE_RAW_TEXT_REQUIRED")

    normalized = raw.replace("\r\n", "\n").replace("\r", "\n")
    lines = normalized.split("\n")
    message_markers = [index for index, line in enumerate(lines) if line.strip() == ISSUE_FORM_MESSAGE_HEADING]
    if len(message_markers) > 1:
        raise TerminalCognitiveQueryError("TERMINAL_COGNITIVE_MULTIPLE_MESSAGE_SECTIONS")

    if message_markers:
        start = message_markers[0] + 1
        end = len(lines)
        for index in range(start, len(lines)):
            candidate = lines[index].strip()
            if candidate.startswith("### "):
                end = index
                break
        query = "\n".join(lines[start:end]).strip()
        mode = "ISSUE_FORM_MESSAGE_SECTION"
        control_metadata_excluded = True
        if not query:
            raise TerminalCognitiveQueryError("TERMINAL_COGNITIVE_MESSAGE_SECTION_EMPTY")
    else:
        query = normalized.strip()
        mode = "FULL_SEALED_MESSAGE_TEXT"
        control_metadata_excluded = False

    body: Dict[str, Any] = {
        "schema": PROJECTION_SCHEMA,
        "projection_mode": mode,
        "raw_text_sha256": _sha256_text(raw),
        "query_text": query,
        "query_sha256": _sha256_text(query),
        "control_metadata_excluded": control_metadata_excluded,
        "command_authority_granted": False,
        "claim_authority_granted": False,
        "scientific_evidence_authority_granted": False,
        "world_truth_authority_granted": False,
        "external_effect_authorized": False,
        "physical_runtime_effect_authorized": False,
        "laws": [
            "CONTROL_METADATA != COGNITIVE_QUERY",
            "SEALED_REQUEST_PROVENANCE != COGNITIVE_QUERY_SURFACE",
            "EMPTY_MESSAGE_SECTION != FALLBACK_TO_CONTROL_TEXT",
            "COGNITIVE_PROJECTION != AUTHORITY",
        ],
    }
    body["projection_hash"] = canonical_hash(body)
    return body


def verify_terminal_cognitive_query_projection(projection: Dict[str, Any]) -> bool:
    if not isinstance(projection, dict):
        return False
    body = dict(projection)
    claimed = str(body.pop("projection_hash", ""))
    if len(claimed) != 64 or canonical_hash(body) != claimed:
        return False
    query = str(body.get("query_text") or "")
    raw_sha = str(body.get("raw_text_sha256") or "")
    query_sha = str(body.get("query_sha256") or "")
    mode = body.get("projection_mode")
    if not query.strip() or len(raw_sha) != 64 or len(query_sha) != 64:
        return False
    if _sha256_text(query) != query_sha:
        return False
    if mode not in {"ISSUE_FORM_MESSAGE_SECTION", "FULL_SEALED_MESSAGE_TEXT"}:
        return False
    if mode == "ISSUE_FORM_MESSAGE_SECTION" and body.get("control_metadata_excluded") is not True:
        return False
    if mode == "FULL_SEALED_MESSAGE_TEXT" and body.get("control_metadata_excluded") is not False:
        return False
    laws = set(body.get("laws") or [])
    return all([
        body.get("schema") == PROJECTION_SCHEMA,
        body.get("command_authority_granted") is False,
        body.get("claim_authority_granted") is False,
        body.get("scientific_evidence_authority_granted") is False,
        body.get("world_truth_authority_granted") is False,
        body.get("external_effect_authorized") is False,
        body.get("physical_runtime_effect_authorized") is False,
        "CONTROL_METADATA != COGNITIVE_QUERY" in laws,
        "EMPTY_MESSAGE_SECTION != FALLBACK_TO_CONTROL_TEXT" in laws,
    ])


__all__ = [
    "ISSUE_FORM_MESSAGE_HEADING",
    "PROJECTION_SCHEMA",
    "TerminalCognitiveQueryError",
    "project_terminal_cognitive_query",
    "verify_terminal_cognitive_query_projection",
]
