"""Assemble source-bound evidence after all required college checks complete."""
import ast
from datetime import datetime
import hashlib
import json
from pathlib import Path
import subprocess
import xml.etree.ElementTree as ET
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def digest(file):
    return hashlib.sha256(file.read_bytes()).hexdigest()


def suite(name):
    file = ROOT / 'tasks' / name
    root = ET.parse(file).getroot()
    nodes = list(root.iter('testsuite'))
    counts = {key: sum(int(n.get(key, 0)) for n in nodes) for key in ('tests', 'failures', 'errors', 'skipped')}
    counts['passed'] = counts['tests'] - counts['failures'] - counts['errors'] - counts['skipped']
    counts['seconds'] = round(sum(float(n.get('time', 0)) for n in nodes), 3)
    counts['sha256'] = digest(file)
    counts['xml'] = str(file.relative_to(ROOT))
    counts['failures_detail'] = [{'test': n.get('classname', '') + '.' + n.get('name', ''),
                                 'message': child.get('message', '')[:300]}
        for n in root.iter('testcase') for child in n if child.tag in {'failure', 'error'}]
    counts['skips_detail'] = [{'test': n.get('classname', '') + '.' + n.get('name', ''), 'reason': child.get('message', '')}
        for n in root.iter('testcase') for child in n if child.tag == 'skipped']
    return counts


def main():
    full = suite('college-schedules-full-verified.xml')
    native = suite('college-schedules-native-verified.xml')
    focused = suite('college-schedules-focused-verified.xml')
    if any(r['errors'] or r['failures'] for r in (full, native, focused)):
        raise RuntimeError('Required final checks have unresolved failures; no completion receipt written.')
    manifest_file = ROOT / 'tasks' / 'college-schedules-verified-source.json'
    manifest = json.loads(manifest_file.read_text(encoding='utf-8'))
    changes = [name for name, sha in manifest.items() if not (ROOT / name).is_file() or digest(ROOT / name) != sha]
    if changes:
        raise RuntimeError('Source changed after the verification snapshot: ' + ', '.join(changes))
    archive = ROOT / 'tasks' / 'college-schedules-verified-source.zip'
    with zipfile.ZipFile(archive) as source:
        if source.testzip() is not None:
            raise RuntimeError('Source archive integrity failed')
        if any(hashlib.sha256(source.read(name)).hexdigest() != sha for name, sha in manifest.items()):
            raise RuntimeError('Archived source differs from the verification manifest')
    own = [
        '.gitignore', 'college_schedules.bat', 'college_schedules.vbs', 'services/settings_store.py',
        'services/proactive/timetable.py', 'services/proactive/timetable_extract.py', 'services/proactive/college.py',
        'services/proactive/briefing.py', 'services/proactive/deadlines.py', 'services/proactive/deadline_changes.py',
        'services/automation/command_words.py', 'services/automation/intent.py', 'interfaces/api/app.py',
        'interfaces/api/routes/college.py', 'interfaces/tray/tray.py', 'tests/college_fakes.py', 'tests/command_action_examples.json',
        'docs/COLLEGE_SCHEDULES.md', 'docs/FEATURES.md', 'docs/current_state.md', 'docs/architecture.md', 'docs/CHANGELOG.md',
        'docs/specs/2026-10-29-college-schedules.md', 'tasks/college-schedules-discovery.md',
        'tasks/college-schedules-policy.json', 'tasks/college-schedules-review.md', 'tasks/college_source_receipt.py',
        'tasks/run_college_checks.py', 'tasks/preview_college.py', 'tasks/verify_college_receipt.py',
    ]
    for directory in ('services/college', 'interfaces/college'):
        own.extend(p.relative_to(ROOT).as_posix() for p in (ROOT / directory).glob('*.py'))
    own.extend('tests/' + name for name in ('test_college_api.py', 'test_college_schedules.py',
               'test_college_uploads.py', 'test_college_viewmodel.py', 'test_college_window.py'))
    own = sorted(set(own))
    python_files = [name for name in own if name.endswith('.py')]
    for name in python_files:
        ast.parse((ROOT / name).read_text(encoding='utf-8-sig'), filename=name)
    new_files = [name for name in python_files if name.startswith(('services/college/', 'interfaces/college/',
        'tests/test_college_', 'tasks/')) or name in {'tests/college_fakes.py', 'services/proactive/timetable_extract.py'}]
    line_counts = {name: len((ROOT / name).read_text(encoding='utf-8-sig').splitlines()) for name in new_files}
    if any(n >= 500 for n in line_counts.values()):
        raise RuntimeError('New college file exceeds the repository size limit')
    baseline = json.loads((ROOT / 'tasks' / 'college-schedules-baseline-source.json').read_text(encoding='utf-8'))
    protected = ['requirements.txt', 'providers/policy.py', 'providers/failover.py',
                 'providers/registry.py', 'providers/openrouter/client.py', 'services/proactive/class_sessions.py',
                 'services/proactive/deadline_store.py']
    unchanged = {name: baseline[name] == digest(ROOT / name) for name in protected}
    if not all(unchanged.values()):
        raise RuntimeError('A protected compatibility input changed; review it before handoff')
    previews = json.loads((ROOT / 'tasks' / 'college-schedules-preview' / 'summary.json').read_text(encoding='utf-8'))
    for row in previews['tabs']:
        if digest(ROOT / row['file']) != row['sha256']:
            raise RuntimeError('Preview artifact changed: ' + row['file'])
    if len(previews['tabs']) != 6 or previews['callback_errors']:
        raise RuntimeError('Six complete native previews are required')
    total = {key: full[key] + native[key] for key in ('tests', 'passed', 'failures', 'errors', 'skipped')}
    head = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()
    result = {
        'feature_date': '2026-10-29', 'verified_at': datetime.now().astimezone().isoformat(),
        'objective': 'Native College Schedules sharing FRIDAY data', 'status': 'implemented and verified',
        'authorization': {'policy': 'tasks/college-schedules-policy.json', 'sha256': digest(ROOT / 'tasks/college-schedules-policy.json')},
        'source_identity': {'head': head, 'worktree': 'dirty; existing unrelated work retained',
            'manifest': str(manifest_file.relative_to(ROOT)), 'manifest_sha256': digest(manifest_file),
            'archive': str(archive.relative_to(ROOT)), 'archive_sha256': digest(archive), 'inputs': len(manifest),
            'archive_integrity': 'pass', 'all_snapshot_inputs_still_match': True},
        'verification': {'full_partition': full, 'native_partition': native, 'focused': focused, 'combined_full_coverage': total,
            'partition_note': 'All tests under tests/: ordinary suite excludes only the two native files, which run in the native partition.',
            'baseline': suite('college-schedules-baseline.xml'),
            'earlier_post_change_full': suite('college-schedules-full-final.xml'),
            'baseline_limit': 'Sandbox blocked Tcl/WSH; combined native baseline did not finish. Other concurrent work fixed baseline popup/test-isolation issues.',
            'existing_warning': 'Starlette TestClient httpx deprecation',
            'performance': 'No speed claim. Native test verifies event processing during a slow request.'},
        'source_validation': {'python_ast': len(python_files), 'protected_inputs_unchanged': unchanged,
            'new_python_lines': line_counts, 'all_new_python_under_500_lines': True},
        'native_previews': {**previews, 'visually_inspected': True, 'review': 'tasks/college-schedules-review.md'},
        'changed_files': own, 'changed_file_sha256': {name: digest(ROOT / name) for name in own},
        'implementation': {'tabs': ['Home', 'Timetable', 'Assignments & Homework', 'Exams', 'Events', 'Upload'],
            'entry': ['All controls / tray College Schedules', 'open college schedules', 'college_schedules.vbs', 'python -m interfaces.college'],
            'sharing': 'Existing active deadlines/exams/class occurrences; separate subject metadata; events shared by overview/local chat/local briefing',
            'imports': 'Raw bytes -> local/consented extraction -> editable preview -> reviewed diff -> explicit Confirm'},
        'limits': ['Timetable imports only; enter exams manually', '10 MiB; 300 rows; active XLSX sheet; first three PDF pages',
            'Recognizable labeled/delimited local tables; arbitrary layouts are not guaranteed',
            'Existing assist-only provider policy can refuse vision; no real provider inference was tested',
            'Independent atomic files with best-effort caught-error rollback; no multi-file crash transaction',
            'PDF text resource behavior depends on installed parser',
            'New college controls/events/faculty stay local; mirrored warnings omit superseded rooms',
            'Existing optional GUI skips retained; native college checks executed',
            'Concurrent unrelated test/Screen access customization work retained and included in final source snapshot',
            'No new dependencies, owner-data migration, commit, push, deployment or git cleanup'],
    }
    output = ROOT / 'tasks' / 'college-schedules-verification.json'
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    summary = ('# College Schedules verification\n\n'
        f'{total["passed"]} passed, {total["failures"]} failed, {total["errors"]} errors, {total["skipped"]} existing skips across full + native coverage.\n\n'
        f'Focused: {focused["passed"]} passed. Native: {native["passed"]} passed. Six synthetic tabs visually inspected.\n\n'
        f'Source: {len(manifest)} inputs; manifest SHA-256 `{digest(manifest_file)}`. All inputs still match.\n\n'
        'See college-schedules-verification.json for baseline failures, exact XML, changed files and limits. '
        'Quit FRIDAY from the tray and relaunch to load. Changes remain uncommitted.\n')
    output.with_suffix('.md').write_text(summary, encoding='utf-8')
    print(json.dumps({'receipt': str(output.relative_to(ROOT)), 'full_coverage': total,
                      'focused_passed': focused['passed'], 'native_passed': native['passed']}))


if __name__ == '__main__':
    main()
