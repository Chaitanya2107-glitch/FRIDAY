"""Run pytest with import-time stores isolated before the API singletons load."""
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main(mode, label='final'):
    if mode not in {'full', 'native', 'focused'}:
        raise ValueError('Choose full, native or focused')
    if label not in {'final', 'reviewed', 'verified'}:
        raise ValueError('Unknown evidence label')
    scratch = ROOT / 'tasks' / ('college-checks-' + mode + '-' + label)
    scratch.mkdir(exist_ok=True)
    os.environ['MEMORY_DB_PATH'] = str(scratch / 'import-memory.db')
    from core.config import config
    config.MEMORY_DIR = scratch / 'import-memory'
    config.MEMORY_DIR.mkdir(exist_ok=True)
    import pytest
    native = ['tests/test_settings_window.py', 'tests/test_college_window.py']
    if mode == 'full':
        # Every test is covered by full + native; separate Tcl from long-lived ML threads.
        selected = ['tests', *('--ignore=' + name for name in native)]
    elif mode == 'native':
        selected = native
    else:
        selected = ['tests/test_college_schedules.py', 'tests/test_college_uploads.py', 'tests/test_college_api.py',
                    'tests/test_college_viewmodel.py', 'tests/test_timetable.py', 'tests/test_college.py',
                    'tests/test_deadlines.py', 'tests/test_deadline_changes.py', 'tests/test_class_changes.py',
                    'tests/test_customization.py', 'tests/test_tray.py', 'tests/test_multi_command.py', 'tests/test_command_words.py']
        selected.append('tests/test_command_action_coverage.py')
    args = [*selected, '-q', '-p', 'no:cacheprovider', '--basetemp=' + str(scratch / 'pytest-temp'),
            '--junitxml=' + str(ROOT / 'tasks' / ('college-schedules-' + mode + '-' + label + '.xml'))]
    return pytest.main(args)


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else 'final'))
