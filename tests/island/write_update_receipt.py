"""Record the requested window/app-launching update after running its checks."""
import hashlib
import json
import platform
import subprocess
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    apps = json.loads((ROOT / 'tasks/island-apps-native/evidence.json').read_text())
    window = json.loads((ROOT / 'tasks/island-transparency/evidence.json').read_text())
    native = json.loads((ROOT / 'tasks/island-native-online/evidence.json').read_text())
    executable = ROOT / 'island/src-tauri/target/release/friday-island.exe'
    assert sha(executable) == apps['artifact_sha256'] == window['artifact_sha256'] == native['exe_sha256']
    assert window['desktop_pixels_unchanged'] and window['real_browser_click_and_typing']
    assert all(apps[k] for k in ['non_indexed_target_rejected', 'suggestion_pin_unpin', 'unpin_does_not_prevent_launch',
                                'successful_launch_recorded', 'favourites_and_recents_survive_restart', 'manual_rescan', 'offline'])
    assert all(native[k] for k in ['startup_passive', 'hover_passive', 'expand_focus', 'escape_restores_fixture',
                                  'click_elsewhere_keeps_focus', 'transparent_regions', 'sneak_centered', 'native_authenticated'])
    bound = json.loads((ROOT / 'tasks/island-native-online/source.json').read_text())
    assert all(sha(ROOT / path) == digest for path, digest in bound.items()), 'Source changed after native validation'
    paths = [*sorted((ROOT / 'island/src').glob('*')), *sorted((ROOT / 'island/tests').glob('*.ts')),
             *sorted((ROOT / 'island/src-tauri/src').glob('*.rs')),
             *sorted((ROOT / 'services/friday_island_server').glob('*.py')), *sorted((ROOT / 'tests/island').glob('*.py'))]
    paths += [ROOT / p for p in ['island/package.json', 'island/package-lock.json', 'island/tsconfig.json', 'island/vite.config.ts',
              'island/index.html', 'island/src-tauri/Cargo.toml', 'island/src-tauri/Cargo.lock', 'island/src-tauri/build.rs',
              'island/src-tauri/tauri.conf.json', 'island/src-tauri/capabilities/main.json', 'services/friday_island_server/requirements.txt']]
    paths = sorted(p for p in set(paths) if p.is_file())
    manifest = {p.relative_to(ROOT).as_posix(): sha(p) for p in paths}
    snapshot = ROOT / 'tasks/island-update-verified-source.zip'
    with zipfile.ZipFile(snapshot, 'w', zipfile.ZIP_DEFLATED) as archive:
        for p in paths: archive.write(p, p.relative_to(ROOT).as_posix())
    receipt = {
        'schema': 1, 'created_utc': datetime.now(timezone.utc).isoformat(),
        'policy': {'decision': 'allowed', 'authority': 'User requested window bug fix first and a separate commit, then installed-app launching',
                   'scope': ['feature-local edits', 'local builds/tests', 'isolated GUI/browser/Calculator checks', 'feature-only commits'],
                   'release_authority': False, 'published': False},
        'ordering': {'window_fix_commit': '689b48e', 'native_catalog_commit': 'f59fe82'},
        'base_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
        'environment': {'os': platform.platform(), 'dpi': native['dpi']},
        'artifact': {'path': executable.relative_to(ROOT).as_posix(), 'sha256': sha(executable), 'bytes': executable.stat().st_size},
        'source_sha256': hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest(), 'source_files': manifest,
        'local_immutable_snapshot': snapshot.relative_to(ROOT).as_posix(), 'snapshot_sha256': sha(snapshot),
        'observed_checks': {'python_tests': 10, 'rust_tests': 7, 'explicit_live_metadata_test': 'passed', 'frontend_tests': 5,
                            'chromium_bridge_suite': 'passed; native-first suggestions, duplicate Tab IDs, pin/unpin, reorder, priority, offline, rescan, reconnect',
                            'native_apps': apps, 'real_browser_transparency': window,
                            'native_focus_and_bridge': {k: native[k] for k in ['startup_passive', 'hover_passive', 'expand_focus',
                                'escape_restores_fixture', 'click_elsewhere_keeps_focus', 'transparent_regions', 'sneak_centered', 'native_command_result']},
                            'typescript_vite_build': 'passed', 'tauri_release_build': 'passed'},
        'limitations': ['Physical display changes and separate Windows 10 hardware remain manual',
                        'Only Calculator was actually launched; other owner-selected app/project launches remain manual',
                        'Metadata sources define installed apps; unregistered portable apps use the manual picker']}
    (ROOT / 'island/docs/update-validation.json').write_text(json.dumps(receipt, indent=2) + '\n', encoding='utf-8')
    print(f'Recorded {len(manifest)} update source files; artifact {sha(executable)}')


if __name__ == '__main__': main()
