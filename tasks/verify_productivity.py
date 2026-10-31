"""Source-bound local receipt and a synthetic read-cost measurement."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import statistics
import sys
import tempfile
import time
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.mind.cognition import Cognition
from services.mind.workspace import Workspace
from services.productivity.store import Tracker


def main():
    files = sorted([*ROOT.glob('interfaces/productivity/*.*'), *ROOT.glob('services/productivity/*.py'),
                    ROOT / 'services/mind/workspace.py', ROOT / 'services/mind/cognition_context.py',
                    ROOT / 'services/automation/intent.py', ROOT / 'interfaces/tray/tray.py',
                    ROOT / 'tests/test_productivity.py', ROOT / 'tests/test_productivity_window.py',
                    ROOT / 'docs/HABITS_AND_TODO.md', ROOT / 'docs/specs/2026-10-30-productivity-desktop.md'])
    sources = {str(p.relative_to(ROOT)).replace('\\', '/'): hashlib.sha256(p.read_bytes()).hexdigest() for p in files if p.is_file()}
    source_digest = hashlib.sha256(json.dumps(sources, sort_keys=True).encode()).hexdigest()
    suite = ET.parse(ROOT / 'tasks/productivity-validation.xml').getroot().find('testsuite')
    with tempfile.TemporaryDirectory(prefix='tracker-benchmark-', dir=ROOT / 'tasks') as temp:
        work = Workspace(Cognition(Path(temp) / 'benchmark.db'))
        store = Tracker(work)
        # Seed only a disposable database, without waking cognitive events.
        with store.db() as conn:
            conn.executemany("INSERT INTO workspace_tasks(title,status,updated) VALUES(?,'active',?)",
                             [(f'Synthetic task {n}', float(n)) for n in range(100)])
            conn.executemany('INSERT INTO tracker_habits(name,weekdays,created) VALUES(?,?,?)',
                             [(f'Synthetic habit {n}', '[0,1,2,3,4,5,6]', '2026-10-30') for n in range(50)])
        def median_read(operation):
            samples = []
            for _ in range(9):
                start = time.perf_counter()
                operation()
                samples.append((time.perf_counter() - start) * 1000)
            return round(statistics.median(samples), 3)
        benchmark = {'baseline_workspace_tasks_ms': median_read(lambda: work.tasks(True)),
                     'candidate_tracker_snapshot_ms': median_read(store.snapshot),
                     'baseline_tasks': 100, 'candidate_tasks': 100, 'candidate_habits': 50,
                     'note': 'Added read cost: candidate also reads habits/history/metadata. No speedup claim.'}
    receipt = {'at': datetime.now(timezone.utc).isoformat(), 'source_sha256': source_digest,
               'sources': sources, 'regression': dict(suite.attrib),
               'preview': json.loads((ROOT / 'tasks/productivity-preview/result.json').read_text()),
               'benchmark': benchmark, 'policy': {'authorization': 'Owner requested local desktop implementation',
               'coordination': 'Read-only research/review; root sole writer',
               'ruflo': 'Swarm ledger unavailable: policy-ledger-anchor-missing; not modified'},
               'limits': ['No full-repository test run', 'FRIDAY restart required for new tray/menu commands',
                          'Finished tasks retain existing read-only workspace semantics']}
    (ROOT / 'tasks/productivity-receipt.json').write_text(json.dumps(receipt, indent=2), encoding='utf-8')
    print(json.dumps({'tests': suite.get('tests'), 'failures': suite.get('failures'), 'errors': suite.get('errors'),
                      'benchmark': benchmark, 'source_sha256': source_digest}))


if __name__ == '__main__':
    main()
