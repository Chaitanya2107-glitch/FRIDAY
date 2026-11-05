"""Bind college verification to code inputs; exclude owner memory and credentials."""
import hashlib
import json
from pathlib import Path
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def snapshot(label):
    if label not in {'baseline', 'candidate', 'final', 'verified'}:
        raise ValueError('Unknown source label')
    files = []
    for folder in ('core', 'providers', 'services', 'interfaces', 'tests'):
        files.extend(p for p in (ROOT / folder).rglob('*') if p.is_file()
                     and '__pycache__' not in p.parts and p.suffix in {'.py', '.json'})
    files.extend(p for p in ROOT.iterdir() if p.is_file() and p.suffix in {'.py', '.bat', '.vbs'})
    files.append(ROOT / 'requirements.txt')
    manifest = {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in sorted(files)}
    payload = json.dumps(manifest, sort_keys=True, indent=2).encode()
    base = ROOT / 'tasks' / f'college-schedules-{label}-source'
    base.with_suffix('.json').write_bytes(payload)
    with zipfile.ZipFile(base.with_suffix('.zip'), 'w', zipfile.ZIP_DEFLATED) as archive:
        for name in manifest:
            archive.write(ROOT / name, name)
    print(json.dumps({'label': label, 'inputs': len(manifest),
                      'manifest_sha256': hashlib.sha256(payload).hexdigest(),
                      'archive_sha256': hashlib.sha256(base.with_suffix('.zip').read_bytes()).hexdigest()}))


if __name__ == '__main__':
    snapshot(sys.argv[1])
