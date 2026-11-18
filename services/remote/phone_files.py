"""Opaque file IDs, bounded signed chunks, and a non-executable quarantine."""
import hashlib
import os
from pathlib import Path, PureWindowsPath
import re
import shutil
import unicodedata
import uuid

from .commands import fields
from .security import Denied, b64, unb64
from .transport_store import identifier

MAX_FILE = 100 * 1024 * 1024
CHUNK = 10000  # Remains inside P0's signed 16 KiB JSON envelope.
BLOCKED = {'.exe', '.bat', '.cmd', '.ps1', '.psm1', '.psd1', '.msi', '.msp', '.scr', '.lnk', '.vbs', '.vbe',
           '.js', '.jse', '.mjs', '.cjs', '.jar', '.dll', '.com', '.cpl', '.hta', '.reg', '.wsf', '.wsh',
           '.sh', '.bash', '.zsh', '.fish', '.py', '.pyw', '.pl', '.rb', '.php', '.app', '.apk', '.aab',
           '.dex', '.so', '.dmg', '.pkg', '.desktop', '.url', '.website', '.webloc', '.html', '.htm', '.svg',
           '.sys', '.pif', '.sct', '.vb', '.vba', '.ws', '.application', '.appref-ms', '.msix', '.msixbundle',
           '.appx', '.appxbundle', '.deb', '.rpm', '.command', '.workflow', '.action', '.scpt',
           '.chm', '.iso', '.img', '.scf', '.inf', '.gadget', '.docm', '.xlsm', '.pptm', '.xlam', '.xll'}


def filename(value):
    if (not isinstance(value, str) or not 1 <= len(value) <= 160 or value != value.strip()
            or unicodedata.normalize('NFC', value) != value or value.endswith(('.', ' '))
            or value.startswith('.') or any(c in value for c in '/\\:%<>"|?*')
            or any(unicodedata.category(c).startswith('C') for c in value)
            or PureWindowsPath(value).is_absolute()
            or re.match(r'^(CON|PRN|AUX|NUL|COM[0-9]|LPT[0-9])(?:\.|$)', value, re.I)
            or set(s.lower() for s in Path(value).suffixes) & BLOCKED):
        raise Denied('unsafe_filename')
    return value


def begin_args(args):
    fields(args, ('name', 'size', 'sha256'))
    filename(args['name'])
    if type(args['size']) is not int or not 0 <= args['size'] <= MAX_FILE:
        raise Denied('file_too_large')
    if not isinstance(args['sha256'], str) or not re.fullmatch('[a-f0-9]{64}', args['sha256']):
        raise Denied('invalid_digest')
    return dict(args)


def chunk_args(args):
    fields(args, ('id', 'offset', 'data'))
    read_args({k: args[k] for k in ('id', 'offset')})
    data = unb64(args['data'], 14000)
    if not 0 < len(data) <= CHUNK:
        raise Denied('invalid_chunk')
    return dict(args)


def read_args(args):
    fields(args, ('id', 'offset'))
    identifier(args['id'])
    if type(args['offset']) is not int or not 0 <= args['offset'] <= MAX_FILE:
        raise Denied('invalid_offset')
    return dict(args)


def finish_args(args):
    fields(args, ('id',))
    identifier(args['id'])
    return dict(args)


def local_folder(path):
    path = Path(path).absolute()
    for part in (path, *path.parents):
        if part.is_symlink() or getattr(part, 'is_junction', lambda: False)():
            raise Denied('unsafe_quarantine')
    path.mkdir(parents=True, exist_ok=True)
    return path


class PhoneFiles:
    def __init__(self, service, store):
        self.service, self.store = service, store
        self.spool = local_folder(store.path.parent / 'transfers')
        with store.db() as db:
            for row in db.execute('SELECT id FROM transfers WHERE expires_at<=?', (store.clock(),)).fetchall():
                self.path(row['id']).unlink(missing_ok=True)
            db.execute("DELETE FROM transfers WHERE expires_at<=? AND NOT (direction='upload' AND complete=1)", (store.clock(),))

    def quarantine(self):
        from .phone_handoff import settings
        options = settings(self.service)
        root = local_folder(options.get('quarantine', str(Path.home() / 'Documents' / 'FRIDAY-from-phone')))
        if options.get('index_received_files') is not True:
            (root / '.nosearch').touch(exist_ok=True)
        return root

    def path(self, identity):
        identifier(identity)
        path = self.spool / identity
        if path.is_symlink() or getattr(path, 'is_junction', lambda: False)():
            raise Denied('unsafe_transfer')
        return path

    def row(self, db, device, identity, direction):
        identifier(identity)
        row = db.execute('SELECT * FROM transfers WHERE id=? AND device=? AND direction=?',
                         (identity, device, direction)).fetchone()
        if not row or row['expires_at'] <= self.store.clock():
            raise Denied('transfer_expired')
        return dict(row)

    def begin(self, device, args):
        begin_args(args)
        self.quarantine()  # Exclusion marker exists before any received file.
        with self.store.db() as db:
            existing = db.execute("SELECT id,offset FROM transfers WHERE device=? AND direction='upload' "
                                  'AND name=? AND size=? AND sha256=? AND expires_at>? ORDER BY rowid DESC LIMIT 1',
                                  (device, args['name'], args['size'], args['sha256'], self.store.clock())).fetchone()
            if existing:
                return dict(existing)
            if db.execute('SELECT count(*) FROM transfers WHERE device=? AND complete=0 AND expires_at>?',
                          (device, self.store.clock())).fetchone()[0] >= 4:
                raise Denied('transfer_limit')
            identity = uuid.uuid4().hex
            with self.path(identity).open('xb'):
                pass
            db.execute('INSERT INTO transfers VALUES (?,?,?,?,?,0,?,?,0)',
                       (identity, device, args['name'], args['size'], args['sha256'], 'upload', self.store.clock() + 86400))
        return dict(id=identity, offset=0)

    def chunk(self, device, args):
        data = unb64(args['data'], 14000)
        with self.store.db() as db:
            row = self.row(db, device, args['id'], 'upload')
            if row['complete'] or args['offset'] + len(data) > row['size']:
                raise Denied('invalid_offset')
            with self.path(row['id']).open('r+b') as output:
                if args['offset'] < row['offset']:
                    output.seek(args['offset'])
                    if args['offset'] + len(data) <= row['offset'] and output.read(len(data)) == data:
                        return dict(offset=row['offset'])
                    raise Denied('chunk_conflict')
                if args['offset'] != row['offset']:
                    raise Denied('invalid_offset')
                output.truncate(row['offset'])
                output.seek(row['offset']); output.write(data); output.flush(); os.fsync(output.fileno())
            offset = row['offset'] + len(data)
            db.execute('UPDATE transfers SET offset=? WHERE id=?', (offset, row['id']))
        return dict(offset=offset)

    def finish(self, device, args):
        with self.store.db() as db:
            row = self.row(db, device, args['id'], 'upload')
            destination = self.quarantine() / (row['id'] + '-' + filename(row['name']))
            if destination.is_symlink() or getattr(destination, 'is_junction', lambda: False)():
                raise Denied('unsafe_quarantine')
            if row['complete']:
                return {k: row[k] for k in ('id', 'name', 'size', 'sha256')}
            source = self.path(row['id'])
            if row['offset'] != row['size'] or source.stat().st_size != row['size']:
                raise Denied('incomplete_file')
            with source.open('rb') as data:
                prefix = data.read(4)
                data.seek(0)
                digest = hashlib.file_digest(data, 'sha256').hexdigest()
            if prefix.startswith((b'MZ', b'\x7fELF', b'#!')) or digest != row['sha256']:
                raise Denied('file_rejected')
            # No replace: a crash after publication may only recover the identical file.
            if destination.exists():
                with destination.open('rb') as data:
                    if hashlib.file_digest(data, 'sha256').hexdigest() != digest:
                        raise Denied('quarantine_conflict')
            else:
                temporary = destination.parent / ('.' + row['id'] + '.partial')
                temporary.unlink(missing_ok=True)
                try:
                    with temporary.open('xb') as output, source.open('rb') as data:
                        shutil.copyfileobj(data, output, 65536)
                        output.flush(); os.fsync(output.fileno())
                    os.link(temporary, destination)  # Atomic publication, never overwrites an owner's file.
                finally:
                    temporary.unlink(missing_ok=True)
            self.service.audit.write(device=device, command='phone_file', risk='safe', result=digest)
            db.execute('UPDATE transfers SET complete=1 WHERE id=?', (row['id'],))
            source.unlink(missing_ok=True)
        return {k: row[k] for k in ('id', 'name', 'size', 'sha256')}

    def send(self, device, path):
        from plugins.smart_clipboard.windows import local_path
        source = local_path(str(path))
        if source is None or not source.is_file() or not source.stat().st_size <= MAX_FILE:
            raise Denied('invalid_local_file')
        name, identity = filename(source.name), uuid.uuid4().hex
        with source.open('rb') as data, self.path(identity).open('xb') as output:
            digest, size = hashlib.sha256(), 0
            while chunk := data.read(65536):
                size += len(chunk)
                if size > MAX_FILE:
                    raise Denied('file_too_large')
                digest.update(chunk); output.write(chunk)
        sha = digest.hexdigest()
        with self.store.db() as db:
            db.execute('INSERT INTO transfers VALUES (?,?,?,?,?,0,?,?,1)',
                       (identity, device, name, size, sha, 'download', self.store.clock() + 86400))
        self.store.put(device, 'file', dict(id=identity, name=name, size=size, sha256=sha), ttl=86400)
        self.service.audit.write(device=device, command='send_phone_file', risk='safe', result=sha)
        return identity

    def read(self, device, args):
        with self.store.db() as db:
            row = self.row(db, device, args['id'], 'download')
            if args['offset'] > row['size']:
                raise Denied('invalid_offset')
            with self.path(row['id']).open('rb') as data:
                data.seek(args['offset']); chunk = data.read(CHUNK)
        return dict(data=b64(chunk), offset=args['offset'], done=args['offset'] + len(chunk) == row['size'],
                    **{key: row[key] for key in ('name', 'size', 'sha256')})

    def forget(self, device):
        with self.store.db() as db:
            rows = db.execute('SELECT * FROM transfers WHERE device=?', (device,)).fetchall()
            for row in rows:
                self.path(row['id']).unlink(missing_ok=True)
                if row['direction'] == 'upload' and row['complete']:
                    path = self.quarantine() / (row['id'] + '-' + filename(row['name']))
                    if path.is_file() and not path.is_symlink():
                        with path.open('rb') as data:
                            same = hashlib.file_digest(data, 'sha256').hexdigest() == row['sha256']
                        if same:
                            path.unlink()
