"""Private, confirmation-gated life graph. Source stores keep ownership of their records."""

from contextlib import closing, contextmanager, nullcontext
from dataclasses import dataclass
from difflib import SequenceMatcher
import hashlib
from pathlib import Path
import re
import sqlite3
import time
import unicodedata

from core.config import config

KINDS = frozenset(('person', 'course', 'faculty', 'assignment', 'exam', 'project', 'place', 'app', 'topic', 'goal'))
RELATIONS = frozenset(('teaches', 'enrolled_in', 'due_for', 'part_of', 'located_at', 'uses',
                       'related_to', 'mentioned_with', 'blocks', 'important_to', 'notification_channel'))
IMPORTS = frozenset(('college', 'island_projects', 'phone_places', 'coaching_goals', 'teacher'))
PROPOSAL_SOURCES = frozenset(('owner_statement', 'co_mentions'))
PERSON_NAME = re.compile(r"[^\W\d_]+(?:[.'’\-][^\W\d_]+)*\.?$")
ROLES = ('lab partner', 'study partner', 'classmate', 'project teammate', 'teammate',
         'friend', 'colleague', 'mentor', 'roommate', 'sibling')


def normalized(text):
    return ' '.join(re.findall(r'[^\W_]+', unicodedata.normalize('NFKC', text).casefold()))


def clean_name(kind, name):
    if kind not in KINDS or not isinstance(name, str) or any(not c.isprintable() for c in name):
        return ''
    name = ' '.join(name.split()).strip(' "\'')
    if not 1 <= len(name) <= 160 or not normalized(name) or re.search(r'[@\n]|https?://', name, re.I):
        return ''
    if kind in {'person', 'faculty'} and (len(name.split()) > 7
            or not all(PERSON_NAME.fullmatch(word) for word in name.split())):
        return ''
    return name


@dataclass(frozen=True)
class Node:
    kind: str
    name: str
    ref: str = ''
    aliases: tuple = ()
    due: str | None = None
    done: bool = False

    @property
    def key(self):
        return self.ref or normalized(self.name)


OWNER = Node('person', 'You', 'owner:self')

SCHEMA = """
CREATE TABLE IF NOT EXISTS entities (
    id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL, name TEXT NOT NULL,
    ref TEXT NOT NULL, created REAL NOT NULL, UNIQUE(kind, ref));
CREATE TABLE IF NOT EXISTS aliases (
    entity_id INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    alias TEXT NOT NULL, source TEXT NOT NULL, PRIMARY KEY(entity_id, alias, source));
CREATE TABLE IF NOT EXISTS entity_sources (
    entity_id INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    source TEXT NOT NULL, due TEXT, done INTEGER NOT NULL, PRIMARY KEY(entity_id, source));
CREATE TABLE IF NOT EXISTS relations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    from_id INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE, relation TEXT NOT NULL,
    to_id INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE, source TEXT NOT NULL,
    confidence REAL NOT NULL CHECK(confidence BETWEEN 0 AND 1),
    confirmed INTEGER NOT NULL CHECK(confirmed IN (0,1)), created REAL NOT NULL,
    words TEXT NOT NULL, rejected INTEGER NOT NULL DEFAULT 0,
    UNIQUE(from_id, relation, to_id, source, words));
CREATE INDEX IF NOT EXISTS graph_incoming ON relations(to_id, confirmed);
CREATE TABLE IF NOT EXISTS history (
    id INTEGER PRIMARY KEY, action TEXT NOT NULL,
    entity_id INTEGER REFERENCES entities(id) ON DELETE CASCADE,
    other_id INTEGER REFERENCES entities(id) ON DELETE CASCADE,
    relation TEXT, source TEXT NOT NULL, created REAL NOT NULL);
CREATE TABLE IF NOT EXISTS forgotten (identity TEXT PRIMARY KEY);
CREATE TABLE IF NOT EXISTS mentions (
    project INTEGER REFERENCES entities(id) ON DELETE CASCADE,
    course INTEGER REFERENCES entities(id) ON DELETE CASCADE, fingerprint TEXT NOT NULL,
    PRIMARY KEY(project, course, fingerprint));
CREATE TABLE IF NOT EXISTS graph_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""

VISIBLE = """SELECT entity_id AS id FROM entity_sources
             UNION SELECT from_id FROM relations WHERE confirmed=1
             UNION SELECT to_id FROM relations WHERE confirmed=1"""


def _fingerprint(*parts):
    return hashlib.sha256('\0'.join(parts).encode()).hexdigest()


def _history(db, action, entity, source, other=None, relation=None):
    db.execute('INSERT INTO history(action,entity_id,other_id,relation,source,created) VALUES(?,?,?,?,?,?)',
               (action, entity, other, relation, source, time.time()))


def _blocked(db, node):
    return db.execute('SELECT 1 FROM forgotten WHERE identity=?', (_fingerprint(node.kind, node.key),)).fetchone()


def _node(db, node, source):
    name = clean_name(node.kind, node.name)
    if not name or _blocked(db, node):
        return None
    old = db.execute('SELECT id,name FROM entities WHERE kind=? AND ref=?', (node.kind, node.key)).fetchone()
    if old:
        ident = old['id']
        if old['name'] != name and source in IMPORTS:
            db.execute('UPDATE entities SET name=? WHERE id=?', (name, ident))
            _history(db, 'renamed', ident, source)
    else:
        ident = db.execute('INSERT INTO entities(kind,name,ref,created) VALUES(?,?,?,?)',
                           (node.kind, name, node.key, time.time())).lastrowid
        _history(db, 'added', ident, source)
    return ident


def _edge(db, left, relation, right, source, score, confirmed, words):
    if not left or not right or left == right or relation not in RELATIONS:
        return None
    key = (left, relation, right, source, words)
    if old := db.execute('SELECT id,confirmed,rejected FROM relations WHERE from_id=? AND relation=? AND to_id=? AND source=? AND words=?',
                         key).fetchone():
        return old['id'] if confirmed or not (old['confirmed'] or old['rejected']) else None
    ident = db.execute('INSERT INTO relations(from_id,relation,to_id,source,words,confidence,confirmed,created) '
                       'VALUES(?,?,?,?,?,?,?,?)', (*key, score, int(confirmed), time.time())).lastrowid
    _history(db, 'linked' if confirmed else 'proposed', left, source, right, relation)
    return ident


class LifeGraph:
    def __init__(self, path=None):
        self._path = Path(path).absolute() if path is not None else None

    @property
    def path(self):
        return self._path or (config.MEMORY_DIR / 'life_graph.db').absolute()

    @contextmanager
    def _db(self, *, write=False):
        if write:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        target = self.path if write else self.path.as_uri() + '?mode=ro'
        with closing(sqlite3.connect(target, timeout=10, uri=not write)) as db, db:
            db.row_factory = sqlite3.Row
            db.execute('PRAGMA foreign_keys=ON')
            if write:
                db.execute('PRAGMA secure_delete=ON')
                db.executescript(SCHEMA)
            db.execute('BEGIN IMMEDIATE' if write else 'BEGIN')
            yield db

    def replace_source(self, source, nodes, links=()):
        """Reconcile one complete authoritative view, preserving independent owner links."""
        if source not in IMPORTS:
            raise ValueError('Unknown life graph source.')
        nodes, links = tuple(nodes), tuple(links)
        digest = _fingerprint(repr(nodes), repr(links))
        sync_key = 'sync:' + source
        with self._db(write=True) as db:
            before = db.execute('SELECT value FROM graph_settings WHERE key=?', (sync_key,)).fetchone()
            if before and before[0] == digest:
                return
            by_key = {}
            previous = {r['entity_id']: (r['due'], bool(r['done'])) for r in
                        db.execute('SELECT * FROM entity_sources WHERE source=?', (source,))}
            db.execute('DELETE FROM aliases WHERE source=?', (source,))
            for node in nodes:
                ident = _node(db, node, source)
                if not ident:
                    continue
                by_key[node.kind, node.key] = ident
                old = previous.pop(ident, None)
                if old != (node.due, node.done):
                    db.execute('INSERT OR REPLACE INTO entity_sources VALUES(?,?,?,?)',
                               (ident, source, node.due, node.done))
                    _history(db, 'imported' if old is None else 'source_updated', ident, source)
                db.executemany('INSERT OR IGNORE INTO aliases VALUES(?,?,?)',
                               ((ident, alias, source) for value in node.aliases
                                if (alias := clean_name(node.kind, value)) and normalized(alias) != normalized(node.name)))
            current = {}
            for left, relation, right in links:
                a, b = by_key.get((left.kind, left.key)), by_key.get((right.kind, right.key))
                if a and b and a != b and relation in RELATIONS:
                    current[a, relation, b] = (a, relation, b)
            for row in db.execute('SELECT * FROM relations WHERE source=?', (source,)).fetchall():
                key = (row['from_id'], row['relation'], row['to_id'])
                if key in current:
                    current.pop(key)
                else:
                    db.execute('DELETE FROM relations WHERE id=?', (row['id'],))
                    _history(db, 'source_unlinked', key[0], source, key[2], key[1])
            for left, relation, right in current:
                _edge(db, left, relation, right, source, 1., True, '')
            for ident in previous:
                db.execute('DELETE FROM entity_sources WHERE entity_id=? AND source=?', (ident, source))
                if db.execute(f'SELECT 1 FROM ({VISIBLE}) WHERE id=?', (ident,)).fetchone():
                    _history(db, 'source_removed', ident, source)
                else:
                    db.execute('DELETE FROM entities WHERE id=?', (ident,))
                    _history(db, 'source_removed', None, source)
            _history(db, 'source_synced', None, source)
            db.execute('INSERT OR REPLACE INTO graph_settings VALUES(?,?)', (sync_key, digest))

    def view(self, *, include_pending=False, connection=None):
        if connection is None and not self.path.is_file():
            return GraphView({}, ())
        with (self._db() if connection is None else nullcontext(connection)) as db:
            visible = VISIBLE
            if include_pending:
                visible += ' UNION SELECT from_id FROM relations UNION SELECT to_id FROM relations'
            entities = {r['id']: dict(r) | {'aliases': []} for r in db.execute(
                f'SELECT e.* FROM entities e JOIN ({visible}) v ON v.id=e.id ORDER BY e.kind,e.name,e.id')}
            for row in db.execute('SELECT DISTINCT entity_id,alias FROM aliases ORDER BY alias'):
                if row['entity_id'] in entities:
                    entities[row['entity_id']]['aliases'].append(row['alias'])
            for row in db.execute("SELECT entity_id,due,done FROM entity_sources WHERE source='college' AND due IS NOT NULL"):
                entities[row['entity_id']].update(due=row['due'], done=bool(row['done']))
            edges = tuple(dict(r) for r in db.execute('SELECT * FROM relations WHERE confirmed=1 ORDER BY id'))
        return GraphView(entities, edges)

    def propose(self, left, relation, right, *, words='', source='owner_statement', score=.9):
        if source not in PROPOSAL_SOURCES or relation not in RELATIONS - {'important_to', 'notification_channel'}:
            raise ValueError('Unknown graph proposal.')
        if words and (left.kind != 'person' or relation != 'related_to' or normalized(words) not in ROLES):
            raise ValueError('Use relationship words supplied in the statement.')
        with self._db(write=True) as db:
            if not all(clean_name(node.kind, node.name) and not _blocked(db, node) for node in (left, right)):
                return None
            a, b = (_node(db, node, source) for node in (left, right))
            return _edge(db, a, relation, b, source, score, False, words)

    def mention(self, project, course, utterance):
        """Three distinct local observations can only stage an unverified association."""
        if not self.path.is_file():
            return None
        with self._db(write=True) as db:
            ids = tuple(db.execute('SELECT id FROM entities WHERE kind=? AND ref=?', (n.kind, n.key)).fetchone()
                        for n in (project, course))
            if not all(ids):
                return None
            a, b = (row[0] for row in ids)
            if db.execute('SELECT 1 FROM relations WHERE (from_id=? AND to_id=?) OR (from_id=? AND to_id=?)',
                          (a, b, b, a)).fetchone():
                return None
            if db.execute('INSERT OR IGNORE INTO mentions VALUES(?,?,?)',
                          (a, b, _fingerprint(normalized(utterance)))).rowcount:
                amount = db.execute('SELECT COUNT(*) FROM mentions WHERE project=? AND course=?', (a, b)).fetchone()[0]
                if amount >= 3:
                    return _edge(db, a, 'mentioned_with', b, 'co_mentions', .65, False, '')

    def proposals(self, limit=10, *, connection=None):
        if connection is None and not self.path.is_file():
            return []
        with (self._db() if connection is None else nullcontext(connection)) as db:
            return [dict(row) for row in db.execute(
                'SELECT r.*, a.name AS left_name,b.name AS right_name,a.kind AS left_kind,b.kind AS right_kind FROM relations r '
                'JOIN entities a ON a.id=r.from_id JOIN entities b ON b.id=r.to_id '
                'WHERE r.confirmed=0 AND r.rejected=0 ORDER BY r.id LIMIT ?', (limit,))]

    def review(self, ident, yes):
        if not self.path.is_file():
            return False
        with self._db(write=True) as db:
            row = db.execute('SELECT * FROM relations WHERE id=? AND confirmed=0 AND rejected=0', (ident,)).fetchone()
            if not row:
                return False
            db.execute('UPDATE relations SET confirmed=?,rejected=? WHERE id=?', (int(yes), int(not yes), ident))
            _history(db, 'confirmed' if yes else 'rejected', row['from_id'], 'owner_review', row['to_id'], row['relation'])
            return True

    def add_alias(self, entity, alias):
        alias = clean_name(entity['kind'], alias)
        if not alias:
            raise ValueError('Use a short name for the alias.')
        with self._db(write=True) as db:
            if db.execute('SELECT 1 FROM entities WHERE id=?', (entity['id'],)).fetchone():
                if db.execute('INSERT OR IGNORE INTO aliases VALUES(?,?,?)',
                              (entity['id'], alias, 'owner_alias')).rowcount:
                    _history(db, 'alias_added', entity['id'], 'owner_alias')
                return True
        return False

    def mark_important(self, person, channel=None, *, important=True):
        with self._db(write=True) as db:
            source = 'owner_mark'
            ident = _node(db, person, source)
            if not ident:
                return False
            if not important:
                rows = db.execute("SELECT * FROM relations WHERE from_id=? AND source=? "
                                  "AND relation IN ('important_to','notification_channel')", (ident, source)).fetchall()
                for row in rows:
                    db.execute('DELETE FROM relations WHERE id=?', (row['id'],))
                    _history(db, 'unmarked', ident, source, row['to_id'], row['relation'])
                return bool(rows)
            owner = _node(db, OWNER, source)
            _edge(db, ident, 'important_to', owner, source, 1., True, '')
            if channel:
                app = _node(db, channel, source)
                _edge(db, ident, 'notification_channel', app, source, 1., True, '')
            return True

    def priority_packages(self):
        if not self.path.is_file():
            return set()
        with self._db() as db:
            return {row[0] for row in db.execute(
                "SELECT DISTINCT e.name FROM relations r JOIN entities e ON e.id=r.to_id "
                "WHERE r.relation='notification_channel' AND r.source='owner_mark' AND r.confirmed=1 "
                "AND EXISTS (SELECT 1 FROM relations i WHERE i.from_id=r.from_id AND i.relation='important_to' "
                "AND i.source='owner_mark' AND i.confirmed=1)")}

    def forget(self, ident):
        if not self.path.is_file():
            return False
        with self._db(write=True) as db:
            row = db.execute('SELECT kind,ref FROM entities WHERE id=? AND ref!=?', (ident, OWNER.key)).fetchone()
            if not row:
                return False
            db.execute('INSERT OR IGNORE INTO forgotten VALUES(?)', (_fingerprint(row['kind'], row['ref']),))
            db.execute('DELETE FROM entities WHERE id=?', (ident,))
            _history(db, 'forgotten', None, 'owner')
            return True

    def option(self, key, value=None):
        if value is None and not self.path.is_file():
            return 'off'
        with self._db(write=value is not None) as db:
            if value is not None:
                db.execute('INSERT OR REPLACE INTO graph_settings VALUES(?,?)', (key, value))
            row = db.execute('SELECT value FROM graph_settings WHERE key=?', (key,)).fetchone()
            return row[0] if row else 'off'

    def export(self):
        from services.settings_store import save

        data = {'entities': [], 'relations': [], 'pending': []}
        if self.path.is_file():
            with self._db() as db:
                view = self.view(connection=db)
                data = {'entities': list(view.entities.values()), 'relations': list(view.edges),
                        'pending': self.proposals(-1, connection=db)}
        path = self.path.with_name('life_graph_export.json')
        save(path, data)
        return path


@dataclass(frozen=True)
class GraphView:
    entities: dict
    edges: tuple

    def resolve(self, phrase, kinds=(), *, fuzzy=True):
        if re.fullmatch(r'#[1-9]\d{0,14}', phrase):
            row = self.entities.get(int(phrase[1:]))
            return [row] if row and (not kinds or row['kind'] in kinds) else []
        key = normalized(phrase)
        if re.fullmatch(r'[a-z]( [a-z]){1,7}', key):
            key = key.replace(' ', '')
        if not key:
            return []
        scores = []
        for row in self.entities.values():
            if kinds and row['kind'] not in kinds:
                continue
            names = {normalized(value) for value in (row['name'], *row['aliases'])}
            if key in names:
                scores.append((1., row))
            elif row['kind'] == 'faculty' and re.sub(r'^(?:prof|professor|dr) ', '', key) in names:
                scores.append((1., row))
            elif fuzzy and len(key) >= 4:
                score = max(SequenceMatcher(None, key, candidate).ratio() for candidate in names)
                if score >= .8:
                    scores.append((score, row))
        best = max((score for score, _ in scores), default=0)
        return [row for score, row in sorted(scores, key=lambda pair: -pair[0])
                if score == best or best < 1. and best - score <= .035]

    def neighbors(self, ident, relations=(), *, reverse=False, kinds=()):
        here, there = ('to_id', 'from_id') if reverse else ('from_id', 'to_id')
        return [(self.entities[e[there]], e) for e in self.edges if e[here] == ident
                and (not relations or e['relation'] in relations) and (not kinds or self.entities[e[there]]['kind'] in kinds)]


graph = LifeGraph()
