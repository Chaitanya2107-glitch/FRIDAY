"""Compile and stage a source-bound candidate while the current desktop stays up."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / ('tasks/capsule-default' if '--capsule' in sys.argv else 'tasks/mochi-rollback' if '--rollback' in sys.argv else 'tasks/coucou-validation')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def inputs():
    files = [path for folder in ['island/src', 'island/public', 'island/src-tauri/src', 'island/src-tauri/capabilities']
             for path in (ROOT / folder).rglob('*') if path.is_file()]
    files += [ROOT / name for name in ['island/package.json', 'island/package-lock.json', 'island/index.html',
        'island/tsconfig.json', 'island/vite.config.ts', 'island/src-tauri/Cargo.toml',
        'island/src-tauri/Cargo.lock', 'island/src-tauri/build.rs', 'island/src-tauri/tauri.conf.json']]
    return {path.relative_to(ROOT).as_posix(): sha(path) for path in sorted(files)}


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    source = inputs()
    started = time.time()
    print('Compiling the Island release candidate; current desktop stays running.', flush=True)
    with (OUTPUT / 'build.log').open('w', encoding='utf-8') as output:
        result = subprocess.run(['npm.cmd', 'run', 'tauri', '--', 'build', '--no-bundle', '--', '--offline'],
            cwd=ROOT / 'island', stdout=output, stderr=subprocess.STDOUT, timeout=900,
            creationflags=subprocess.CREATE_NO_WINDOW)
    assert source == inputs(), 'Build inputs changed; do not activate this candidate'
    log = (OUTPUT / 'build.log').read_text(encoding='utf-8')
    linked = ROOT / 'island/src-tauri/target/release/deps/friday_island.exe'
    # Cargo links this artifact first, then tries to replace the running top-level exe.
    locked = 'failed to remove file' in log and 'Access is denied' in log
    assert result.returncode == 0 or locked, log[-6000:]
    assert linked.is_file() and linked.stat().st_mtime >= started, 'No newly linked candidate'
    candidate = OUTPUT / 'friday-island.exe'
    shutil.copy2(linked, candidate)
    assert sha(linked) == sha(candidate)
    receipt = {'candidate_compiled': True, 'build_command_exit': result.returncode,
        'running_executable_locked': locked, 'source': source, 'source_unchanged': True,
        'candidate': candidate.relative_to(ROOT).as_posix(), 'binary_sha256': sha(candidate),
        'seconds': round(time.time() - started, 2)}
    (OUTPUT / 'candidate.json').write_text(json.dumps(receipt, indent=2), encoding='utf-8')
    print(json.dumps({key: value for key, value in receipt.items() if key != 'source'}), flush=True)


if __name__ == '__main__':
    main()
