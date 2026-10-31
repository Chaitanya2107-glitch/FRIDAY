"""Run affected prediction/conversation checks with source-bound local evidence."""
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def sources():
    files = [ROOT / 'train_friday.py', ROOT / 'train_friday.bat', Path(__file__)]
    for folder in ('core', 'services', 'interfaces', 'providers', 'tests'):
        files.extend((ROOT / folder).rglob('*.py'))
    return {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(set(files))}


def main():
    scratch = ROOT / 'tasks' / 'prediction-training-checks'
    scratch.mkdir(exist_ok=True)
    os.environ['MEMORY_DB_PATH'] = str(scratch / 'import-chat.db')
    from core.config import config
    config.MEMORY_DIR = scratch / 'import-memory'
    config.MEMORY_DIR.mkdir(exist_ok=True)
    before = sources()
    import pytest
    selected = [
        'training_interview', 'training_review', 'training_upgrades', 'foresight', 'predict',
        'learning_dataset', 'learning_sources', 'learning_learner', 'learning_service', 'learning_catalog',
        'learning_reports', 'learning_origin', 'learning_telegram', 'brain', 'brain_memory', 'brain_crosscheck',
        'talk', 'evening', 'mind', 'life_state', 'inquiry', 'curiosity', 'dialogue_lifecycle',
        'cognition', 'habits', 'ai_assistance', 'personal_model', 'command_action_coverage',
    ]
    selected = ['tests/test_' + name + '.py' for name in selected if (ROOT / 'tests' / ('test_' + name + '.py')).exists()]
    evidence = ROOT / 'tasks' / 'prediction-training-integration.xml'
    started = time.monotonic()
    result = pytest.main([*selected, '-q', '--tb=short', '-p', 'no:cacheprovider',
                          '--basetemp=' + str(scratch / 'pytest-temp'), '--junitxml=' + str(evidence)])
    cases = ET.parse(evidence).getroot().findall('.//testcase')
    changed = before != sources()
    receipt = {
        'task': 'Prediction-only Train Friday with automatic owner-feedback learning',
        'authorization': 'Explicit user request; reversible local code/tests/docs only',
        'policy_mode': 'legacy', 'decision': 'allowed', 'writer': 'Codex /root',
        'read_only_review': 'prediction_flow; attribution and app-identity findings fixed',
        'source_sha256': before, 'source_unchanged_during_checks': not changed,
        'tests': len(cases), 'failures': sum(c.find('failure') is not None for c in cases),
        'errors': sum(c.find('error') is not None for c in cases),
        'skipped': sum(c.find('skipped') is not None for c in cases),
        'elapsed_seconds': round(time.monotonic() - started, 2),
        'pytest_exit': result, 'selected_files': selected,
        'evidence': str(evidence.relative_to(ROOT)),
        'evidence_sha256': hashlib.sha256(evidence.read_bytes()).hexdigest(),
        'limits': ['Affected-module suite; full repository suite not run',
                   'Synthetic owner feedback and isolated stores; live app not restarted',
                   'Chat model weights unchanged; nightly model needs eligible observed data'],
    }
    (ROOT / 'tasks' / 'prediction-training-verification.json').write_text(json.dumps(receipt, indent=2), encoding='utf-8')
    return int(bool(result or changed))


if __name__ == '__main__':
    raise SystemExit(main())
