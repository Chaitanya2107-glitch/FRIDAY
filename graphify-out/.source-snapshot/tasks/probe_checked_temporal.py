"""Replay frozen synthetic date reports through the real local executive/critic."""
import argparse
import asyncio
from contextlib import redirect_stdout
import hashlib
import io
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from probe_relevance_recall import hashes
import probe_temporal_memory as probe


async def run(fixture):
    captured = io.StringIO()
    try:
        async with asyncio.timeout(150):
            with redirect_stdout(captured):
                await probe.main(initial=fixture['initial'], correction=fixture['correction'], followup=fixture.get('followup'))
        result = json.loads(captured.getvalue())
        phases = {row['phase']: row for row in result['results']}
        checks = {}
        for phase in ('initial', 'correction', 'followup'):
            if phase not in fixture:
                continue
            value = phases.get(phase, {})
            group = fixture.get(f'expected_{phase}_group', 'upcoming')
            rows = value.get('situation', {}).get(group, [])
            expected = fixture[f'expected_{phase}']
            checks[phase] = bool(value.get('result', {}).get('status') == 'completed' and len(rows) == 1
                and rows[0]['start'] == rows[0]['end'] == expected and rows[0]['quote'] == fixture[phase])
            if phase != 'initial':
                history = value.get('history', [])
                checks[phase] = bool(checks[phase] and len(history) == (3 if phase == 'followup' else 2)
                    and history[1]['superseded_by'] == history[0]['id'])
        result['phase_expectations'] = checks
        result['expectations_met'] = all(checks.values())
        return result
    finally:
        await probe.runtime.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fixture', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    fixture = json.loads(args.fixture.read_text(encoding='utf-8'))
    before = hashes()
    result = asyncio.run(run(fixture))
    result.update(sources=before, sources_unchanged=before == hashes(),
                  fixture_sha256=hashlib.sha256(args.fixture.read_bytes()).hexdigest())
    args.output.write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps({k: v for k, v in result.items() if k not in {'sources', 'results', 'generations'}}))
    sys.exit(0 if result['expectations_met'] and result['sources_unchanged'] else 1)
