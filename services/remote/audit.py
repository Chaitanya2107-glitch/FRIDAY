"""Bounded local metadata only; request bodies and notification text never enter this log."""
import ipaddress
import json
import os
from pathlib import Path
import re
import threading
import time


class Audit:
    def __init__(self, directory: Path, max_bytes=5 * 1024 * 1024, clock=time.time):
        self.path = Path(directory).absolute() / 'audit.jsonl'
        self.max_bytes, self.clock = max_bytes, clock
        self.lock = threading.RLock()

    def ready(self):
        with self.lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open('ab'):
                pass

    def write(self, *, device='unknown', command='unknown', risk='blocked', result='refused', source='local'):
        def label(value):
            return value if isinstance(value, str) and re.fullmatch(r'[a-zA-Z0-9_:-]{1,64}', value) else 'unknown'
        try:
            source = str(ipaddress.ip_address(source))
        except ValueError:
            source = 'local'
        row = dict(time=self.clock(), device=label(device), command=label(command),
                   risk=risk if risk in {'safe', 'confirm', 'blocked'} else 'blocked', result=label(result), source_ip=source)
        encoded = (json.dumps(row, separators=(',', ':')) + '\n').encode('utf-8')
        with self.lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            if self.path.exists() and self.path.stat().st_size + len(encoded) > self.max_bytes:
                os.replace(self.path, self.path.with_name('audit.jsonl.1'))
            with self.path.open('ab') as output:
                output.write(encoded)
                output.flush()
                os.fsync(output.fileno())

    def recent(self):
        with self.lock:
            rows = []
            for path in (self.path.with_name('audit.jsonl.1'), self.path):
                if path.exists():
                    with path.open(encoding='utf-8') as stream:
                        from collections import deque
                        rows.extend(json.loads(line) for line in deque(stream, maxlen=20))
            return rows[-20:]
