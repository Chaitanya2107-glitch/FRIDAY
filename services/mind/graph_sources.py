"""Read-through graph projections of explicit owner data. Each source is independently replaceable."""

from contextlib import closing
from datetime import datetime
import json
from pathlib import Path
import sqlite3
import threading

from core.config import config
from core.logger import logger
from .graph import Node, OWNER, clean_name, graph, normalized

_sync = threading.Lock()


def initialism(name):
    words = [word for word in normalized(name).split() if word not in {'and', 'of', 'the'}]
    return ''.join(word[0] for word in words).upper() if len(words) > 1 else ''


def faculty_aliases(name):
    parts = name.split()
    surname = next((part for part in reversed(parts) if len(part.rstrip('.')) > 0), '')
    if not surname:
        return ()
    return (surname,)


def college():
    from services.college import catalogs, store, work
    from services.proactive import deadlines, timetable

    weekly = timetable.load()
    catalog = catalogs.subjects()['items']
    courses, nodes, links = {}, [], []

    def course(name):
        if not (key := normalized(name)):
            return None
        existing = [node for node in courses.values() if key in {normalized(n) for n in (node.name, *node.aliases)}]
        if len(existing) == 1:
            return existing[0]
        if len(existing) > 1:
            return courses.get(key)
        forms = (*timetable.aliases(name), initialism(name))
        node = Node('course', name, aliases=tuple(dict.fromkeys(n for n in forms if n and normalized(n) != key)))
        courses[key] = node
        return node

    def place(owner, name):
        if owner and name and clean_name('place', name):
            room = Node('place', name)
            nodes.append(room)
            links.append((owner, 'located_at', room))

    # Catalog display names and aliases are resolved before schedule and work rows bind to them.
    for row in catalog:
        subject = course(row['subject'])
        name = row.get('faculty', '').strip()
        if subject and clean_name('faculty', name):
            faculty = Node('faculty', name, aliases=faculty_aliases(name))
            nodes.append(faculty)
            links.append((faculty, 'teaches', subject))
        place(subject, row.get('room'))
    for row in weekly:
        subject = course(row['subject'])
        if subject:
            nodes.append(OWNER)
            links.append((OWNER, 'enrolled_in', subject))
        place(subject, row.get('room'))
    for row in deadlines.load(include_done=True):
        subject = course(row.get('subject', ''))
        kind = 'exam' if work.is_exam(row) else 'assignment'
        name = row['what']
        names = (subject.name, *subject.aliases) if subject else ()
        short = name
        for prefix in sorted(names, key=len, reverse=True):
            if name.casefold().startswith(prefix.casefold() + ' '):
                short = name[len(prefix):].strip()
                break
        aliases = (short, *(f'{p} {short}' for p in names))
        node = Node(kind, name, ref=str(store.item_id(row)), aliases=aliases,
                    due=datetime.fromisoformat(row['due']).isoformat(timespec='minutes'), done=row.get('done') is True)
        nodes.append(node)
        if subject:
            links.append((node, 'due_for', subject))
        place(node, row.get('venue'))
    by_key = {(n.kind, n.key): n for n in (*nodes, *courses.values())}
    return tuple(by_key.values()), tuple(dict.fromkeys(links))


def project_rows():
    from types import SimpleNamespace
    from services.friday_island_server import projects
    from services.friday_island_server.config import IslandConfig, config_path

    path = config_path()
    native = []
    if path.is_file():
        if path.stat().st_size > 1024 * 1024:
            raise ValueError('Island project config is too large.')
        native = IslandConfig.model_validate_json(path.read_text(encoding='utf-8-sig')).projects
    return projects.catalog(SimpleNamespace(projects=native))['items']


def island_projects():
    rows = project_rows()
    return [Node('project', row['name'], ref=('native:' + str(row['native_id'])) if row.get('conflict') else '')
            for row in rows], ()


def phone_places(path=None):
    """Read only retained P2 geofence labels, without projecting a location timeline."""
    path = Path(path or config.MEMORY_DIR / 'phone' / 'phone_events.db').absolute()
    if not path.is_file():
        return (), ()
    with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as db:
        # Filtering in SQLite keeps all other signal payloads outside this importer.
        rows = db.execute("SELECT DISTINCT payload FROM phone_events WHERE type='places'").fetchall()
    names = set()
    for (payload,) in rows:
        try:
            data = json.loads(payload)
        except (TypeError, ValueError):
            continue
        if (isinstance(data, dict) and set(data) == {'place', 'transition'} and data['transition'] in ('entered', 'left')
                and (name := clean_name('place', data['place']))):
            names.add(name)
    return [Node('place', name) for name in sorted(names, key=str.casefold)], ()


def coaching_goals():
    from services.mind.cognition import cognition

    path = cognition.path.absolute()
    if not path.is_file():
        return (), ()
    with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as db:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name='private_coaching_commitments'").fetchone():
            return (), ()
        rows = db.execute("SELECT id,json_extract(body,'$.title') FROM private_coaching_commitments "
                          "WHERE kind='goal' ORDER BY id").fetchall()
    return [Node('goal', name, ref=str(ident), aliases=(f'goal {ident}',)) for ident, name in rows], ()


def teacher():
    from services.mind import knowledge

    path = Path(knowledge.db_path).absolute()
    if not path.is_file():
        return (), ()
    with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as db:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name='things'").fetchone():
            return (), ()
        rows = db.execute("SELECT kind,name FROM things WHERE source IN ('boss','confirmed') "
                          "AND kind IN ('app','topic','term') AND name NOT LIKE 'phone:%' ORDER BY key").fetchall()
    nodes = [Node('app' if kind == 'app' else 'topic', name) for kind, name in rows]
    return tuple({(node.kind, node.key): node for node in nodes}.values()), ()


def refresh(store=None):
    store = graph if store is None else store
    with _sync:
        for source, read in (('college', college), ('island_projects', island_projects), ('phone_places', phone_places),
                             ('coaching_goals', coaching_goals), ('teacher', teacher)):
            try:
                nodes, links = read()
                store.replace_source(source, nodes, links)
            except (OSError, sqlite3.Error, ValueError, KeyError, TypeError, RuntimeError) as error:
                logger.debug('Life graph source %s unavailable (%s)', source, type(error).__name__)
    return store.view()


def work_node(view, identity, name='', *, exact=True):
    if identity is not None:
        row = next((row for row in view.entities.values() if row['kind'] in {'assignment', 'exam'}
                    and row['ref'] == str(identity)), None)
        if row:
            return row
    matches = view.resolve(name, ('assignment', 'exam'), fuzzy=not exact)
    return matches[0] if len(matches) == 1 else None


def work_projects(view, node):
    """Confirmed project links from a scheduled item and its course."""
    found = {}
    for project, edge in view.neighbors(node['id'], ('blocks', 'part_of', 'related_to'), kinds=('project',)):
        found.setdefault(project['id'], (project, edge['relation']))
    for course, _ in view.neighbors(node['id'], ('due_for',), kinds=('course',)):
        for reverse in (False, True):
            for project, _ in view.neighbors(course['id'], ('part_of', 'related_to', 'mentioned_with'),
                                             reverse=reverse, kinds=('project',)):
                found.setdefault(project['id'], (project, 'related_to'))
    return list(found.values())


def goal_connections(identity):
    if not graph.path.is_file():
        return []
    try:
        view = graph.view()
        node = next((n for n in view.entities.values() if n['kind'] == 'goal' and n['ref'] == str(identity)), None)
        if node:
            return sorted({n['name'] for reverse in (False, True) for n, _ in
                           view.neighbors(node['id'], ('related_to', 'part_of', 'due_for'), reverse=reverse,
                                          kinds=('course', 'project'))})
    except (OSError, sqlite3.Error):
        pass
    return []


def priority_packages(vip=()):
    try:
        return list(dict.fromkeys((*vip, *sorted(graph.priority_packages()))))
    except (OSError, sqlite3.Error):
        return list(vip)


def briefing_connections(items):
    if not items or not graph.path.is_file():
        return ''
    try:
        view = refresh()
        lines = []
        for item in items[:4]:
            node = work_node(view, item.id, item.title)
            if node:
                for project, relation in work_projects(view, node)[:2]:
                    lines.append(f"{item.title} {'blocks' if relation == 'blocks' else 'is linked to'} {project['name']}.")
        return ' '.join(dict.fromkeys(lines))
    except (OSError, sqlite3.Error, ValueError):
        return ''
