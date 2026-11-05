"""Record checked Island inputs/artifacts. Never includes config or owner data.

Run only after the documented tests/native probes/build. The static test counts
are an execution record, not an independent test runner or release authority.
"""
import hashlib
import json
import platform
import subprocess
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    baseline = json.loads((ROOT / 'tasks/island-native-baseline/evidence.json').read_text())
    offline = json.loads((ROOT / 'tasks/island-native-release/evidence.json').read_text())
    online = json.loads((ROOT / 'tasks/island-native-online/evidence.json').read_text())
    binary = ROOT / 'island/src-tauri/target/release/friday-island.exe'
    checks = ['startup_passive', 'no_activate', 'tool_window', 'always_on_top', 'top_edge',
              'transparent_regions', 'hover_peek', 'hover_passive', 'expand_focus',
              'escape_restores_fixture', 'sneak_centered', 'click_elsewhere_keeps_focus', 'passive_escape']
    assert all(offline[c] and online[c] for c in checks)
    assert online['native_authenticated'] and online['native_command_result'].startswith('Next:')
    assert digest(binary) == offline['exe_sha256'] == online['exe_sha256']
    native_manifest = json.loads((ROOT / 'tasks/island-native-release/source.json').read_text())
    assert all(digest(ROOT / name) == value for name, value in native_manifest.items()), 'Native source changed after verification'

    paths = [*sorted((ROOT / 'island/src').glob('*')), *sorted((ROOT / 'island/tests').glob('*.ts')),
             *sorted((ROOT / 'island/src-tauri/src').glob('*.rs')),
             *sorted((ROOT / 'services/friday_island_server').glob('*.py')),
             *sorted((ROOT / 'tests/island').glob('*.py'))]
    paths += [ROOT / name for name in [
        'island/package.json', 'island/package-lock.json', 'island/index.html', 'island/tsconfig.json', 'island/vite.config.ts',
        'island/src-tauri/Cargo.toml', 'island/src-tauri/Cargo.lock', 'island/src-tauri/build.rs',
        'island/src-tauri/tauri.conf.json', 'island/src-tauri/capabilities/main.json',
        'services/friday_island_server/requirements.txt',
        'services/proactive/timetable.py', 'services/mind/language.py']]
    paths = sorted(p for p in set(paths) if p.is_file())
    manifest = {p.relative_to(ROOT).as_posix(): digest(p) for p in paths}
    snapshot = ROOT / 'tasks/island-verified-source.zip'
    with zipfile.ZipFile(snapshot, 'w', zipfile.ZIP_DEFLATED) as archive:
        for path in paths: archive.write(path, path.relative_to(ROOT).as_posix())

    def benchmark(data):
        return {key: data[key] for key in ['source_sha256', 'exe_sha256', 'rest_cpu_percent_one_core',
                'cpu_warmup_seconds', 'cpu_sample_seconds', 'measured_processes']}

    receipt = {
        'schema': 1, 'created_utc': datetime.now(timezone.utc).isoformat(),
        'policy': {'decision': 'allowed', 'authority': 'User task: build and locally test FRIDAY Island; small clear commits',
                   'scope': ['additive feature files', 'local builds/tests', 'isolated GUI probes', 'feature-only commits'],
                   'ruflo': 'No registered guidance tools; local legacy policy has no live collaboration harness',
                   'release_authority': False, 'published': False},
        'environment': {'os': platform.platform(), 'python': sys.version.split()[0], 'node': '24.18.0',
                        'rust': '1.98.1', 'native_dpi': online['dpi']},
        'base_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
        'source_sha256': hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest(),
        'source_files': manifest, 'local_immutable_snapshot': 'tasks/island-verified-source.zip',
        'snapshot_sha256': digest(snapshot),
        'artifact': {'path': binary.relative_to(ROOT).as_posix(), 'sha256': digest(binary), 'bytes': binary.stat().st_size},
        'observed_checks': {
            'python_tests': 9, 'rust_tests': 4, 'frontend_tests': 5,
            'chromium_bridge_integration': 'passed; states, config edits/reorder, keyboard, offline, reconnect, reduced motion',
            'native_windows': {key: True for key in checks}, 'native_bridge_authentication': True,
            'native_sneak_command': online['native_command_result'],
            'typescript_vite_build': 'passed', 'tauri_release_build': 'passed', 'tauri_dev_entry_point': 'passed',
            'npm_audit_reported_vulnerabilities': 0,
        },
        'benchmark': {'method': 'One five-second sample after five-second extra warm-up; aggregate CPU percent of one core',
                      'baseline_offline': benchmark(baseline), 'candidate_offline': benchmark(offline), 'candidate_online': benchmark(online)},
        'limitations': ['Physical monitor/resolution changes not exercised', 'Windows 10/acrylic fallback not tested on separate hardware',
                        'Configured owner apps/editor/terminal/URL launches left for manual check',
                        'No live AI provider calls; automated schedule data is a fixture',
                        'Default expand hotkey conflicts with existing FRIDAY taskbar flyout; configurable'],
    }
    target = ROOT / 'island/docs/validation.json'
    target.write_text(json.dumps(receipt, indent=2) + '\n', encoding='utf-8')
    print(f'Recorded {len(manifest)} source files; artifact {receipt["artifact"]["sha256"]}')


if __name__ == '__main__':
    main()
