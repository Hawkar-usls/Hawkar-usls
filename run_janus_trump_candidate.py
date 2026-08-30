#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / 'src'
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from janus_spi.trump_candidate import resolve_trump_candidate


def main() -> int:
    parser = argparse.ArgumentParser(description='Resolve bounded TRUMP candidate tissue for JANUS.')
    parser.add_argument('--output', default='runtime/trump-candidate/context.json')
    args = parser.parse_args()

    context = resolve_trump_candidate()
    path = Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(context, ensure_ascii=False, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    print(json.dumps({
        'terminal':'JANUS_TRUMP_CANDIDATE_RUNTIME_AVAILABLE',
        'state':context['state'],
        'candidate':context['candidate_name'],
        'claim_state':context['claim_state'],
        'future_manifest_state':context['future_runtime']['state'],
        'improvement_proposal_allowed':context['improvement_proposal_allowed'],
        'repository_write_authorized':context['repository_write_authorized'],
        'theorem_authority':context['theorem_authority'],
        'context_hash':context['context_hash'],
    }, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
