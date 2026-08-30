from __future__ import annotations

import json
from pathlib import Path


def test_terminal_conversation_route_is_read_only_activity_selection():
    routing = json.loads(Path('.janus/activator/ROUTING_TABLE.json').read_text(encoding='utf-8'))
    rows = [row for row in routing['routes'] if row.get('match') == 'human_read_only_conversation']
    assert len(rows) == 1
    route = rows[0]
    assert route['organs'] == [
        'Hawkar-usls/-Terminal-for-Janus',
        'Hawkar-usls/Janus',
        'Hawkar-usls/Hrain',
        'Hawkar-usls/Demi_Head',
    ]
    assert route['conversation_authority_mode'] == 'READ_ONLY_CONVERSATION'
    assert route['activation_implies_dispatch'] is False
    assert route['external_effect_authorized'] is False
    assert 'read_only_authority_ceiling' in route['required_gates']
    assert 'TERMINAL_MESSAGE != COMMAND' in routing['global_guards']
    assert 'CONVERSATION != HUMAN_AUTHORIZED_WRITE' in routing['global_guards']
