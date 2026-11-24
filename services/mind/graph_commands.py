"""Local commands and fixed query templates over the confirmed life graph."""

import asyncio
from collections import Counter, deque
from datetime import datetime
import json
import re
import sqlite3

from core.config import config
from core.logger import logger
from services.automation import command_slots, command_words
from services.automation.results import ActionResult
from services.memory import notes
from .graph import KINDS, OWNER, ROLES, Node, clean_name, graph, normalized
from . import evening, graph_sources, wording

PRIVATE_MEMORY = 'Life graph command handled locally.'
WORK = ('assignment', 'exam')
PEOPLE = ('person', 'faculty')
QUESTIONS = (
    ('due', r'what(?: is|[’\x27]s) due (?:for|in) (.+)', ('course', 'faculty')),
    ('teaches', r'who (?:teaches|is (?:the )?(?:instructor|teacher|faculty) for) (.+)', ('course',)),
    ('project', r'which project is (.+) for', ('assignment',)),
    ('with', r'what do i have with (.+)', PEOPLE),
    ('connected', r'what(?: is|[’\x27]s) connected to (.+)', ()),
    ('know', r'how do i know (.+)', PEOPLE),
)
ROLE = re.compile(r"(?P<person>.+?) is my (?P<words>" + '|'.join(ROLES)
                  + r")(?: (?:for|in|on) (?P<target>.+))?", re.I)
LINKS = {
    'is part of': ('part_of', ('assignment', 'exam', 'project', 'topic', 'goal'), ('project', 'course', 'topic')),
    'belongs to': ('part_of', ('assignment', 'exam', 'project', 'topic', 'goal'), ('project', 'course', 'topic')),
    'is for': ('part_of', ('assignment', 'project', 'goal'), ('project', 'course')),
    'teaches': ('teaches', ('faculty',), ('course',)),
    'is due for': ('due_for', WORK, ('course',)),
    'is located at': ('located_at', ('course', 'exam', 'project'), ('place',)),
    'uses': ('uses', ('project', 'topic', 'course'), ('app',)),
    'is related to': ('related_to', (), ()),
    'blocks': ('blocks', ('exam', 'assignment'), ('project',)),
}
LINK = re.compile(r'(.+?) (' + '|'.join(re.escape(p) for p in LINKS) + r') (.+)', re.I)
ALIAS = re.compile(r'(?:alias (.+?) as|call (.+?) in my graph) (.+)', re.I)
REVIEW = re.compile(r'(confirm|reject) (?:life )?graph link #?([1-9]\d{0,11})', re.I)
IMPORTANT = re.compile(r'(mark|unmark) (.+?) (?:as )?(?:an? )?important(?: person)?(?: on (.+))?', re.I)
PACKAGE = re.compile(r'[a-zA-Z][a-zA-Z0-9_]*(?:\.[a-zA-Z0-9_]+){1,12}')
PAYLOAD = re.compile(r'^(?:type|paste|write|say|repeat|dictate|text|message|whatsapp|telegram|'
                     r'email|send|forward|reply|post|search(?: for)?|look up)\s+', re.I)


def result(body, success=True, *, silent=False):
    return ActionResult(success, body, memory_message=PRIVATE_MEMORY, repeatable=False, speech='' if silent else None)


def _phrase(value):
    return re.sub(r'^(?:the|my) ', '', value.strip(' "\''), flags=re.I)


def _faculty_phrase(value):
    return re.sub(r"(?:[’']s|s[’']) courses?$", '', value, flags=re.I)


def _node(row):
    return Node(row['kind'], row['name'], ref=row['ref'])


def _clarify(view, rows):
    options = []
    for row in rows[:5]:
        course = [n['name'] for n, _ in view.neighbors(row['id'], ('due_for',))]
        note = ', '.join(course) or row['kind']
        if sum(r['name'] == row['name'] for r in rows) > 1 and row.get('due'):
            note += ', ' + row['due'].replace('T', ' ')
        same = sum(normalized(r['name']) == normalized(row['name']) for r in rows) > 1
        options.append(f"{row['name']} ({note})" + (f" #{row['id']}" if same else ''))
    return 'Which one do you mean? ' + ' or '.join(options) + '?'


def _resolve(view, phrase, kinds=(), *, fuzzy=True):
    return command_slots.entity(_phrase(phrase), kinds, view=view, fuzzy=fuzzy)


def _due(view, courses, now):
    from services.proactive.deadlines import when

    items = {node['id']: node for course in courses for node, _ in view.neighbors(course['id'], ('due_for',),
             kinds=WORK, reverse=True) if node.get('due') and not node.get('done')}
    ordered = sorted(items.values(), key=lambda row: (row['due'], row['name']))
    return [f"{row['name']} — {when(datetime.fromisoformat(row['due']), now)}" for row in ordered[:12]]


def _connections(view, start):
    todo, seen, results = deque([(start, 0)]), {start['id']}, []
    while todo and len(results) < 12:
        node, depth = todo.popleft()
        if depth == 3:
            continue
        for reverse in (False, True):
            for other, edge in view.neighbors(node['id'], reverse=reverse):
                if other['id'] in seen or edge['relation'] in {'enrolled_in', 'important_to', 'notification_channel'}:
                    continue
                seen.add(other['id'])
                results.append(other)
                todo.append((other, depth + 1))
                if len(results) == 12:
                    return results
    return results


def _relationships(view, start):
    rows = view.neighbors(start['id'], ('related_to', 'teaches'))
    labels = [f"{edge['words']} for {node['name']}" if edge['words'] and node['ref'] != OWNER.key
              else edge['words'] or f"teaches {node['name']}" for node, edge in rows
              if edge['words'] or edge['relation'] == 'teaches']
    return list(dict.fromkeys(labels))


def answer(view, action, node, now):
    name, ident = node['name'], node['id']
    if action == 'due':
        courses = [row for row, _ in view.neighbors(ident, ('teaches',), kinds=('course',))] if node['kind'] == 'faculty' else [node]
        due = _due(view, courses, now)
        return (f'Due for {name} — ' + '. '.join(due) + '.' if due else f'I have no open work recorded for {name}.')
    if action == 'teaches':
        names = sorted({row['name'] for row, _ in view.neighbors(ident, ('teaches',), kinds=('faculty',), reverse=True)})
        return (' and '.join(names) + f' teaches {name}.' if len(names) == 1 else
                ' and '.join(names) + f' teach {name}.' if names else f'I have no confirmed faculty for {name}.')
    if action == 'project':
        names = sorted({row['name'] for row, _ in view.neighbors(ident, ('part_of',), kinds=('project',))})
        return (f'{name} is for ' + ' and '.join(names) + '.' if names else
                f'I have no confirmed project for {name}.')
    if action == 'connected':
        rows = _connections(view, node)
        return (f'Connected to {name} — ' + ', '.join(f"{r['name']} ({r['kind']})" for r in rows) + '.' if rows else
                f'I have no confirmed connections for {name}.')
    roles = _relationships(view, node)
    if action == 'know':
        return (f'You recorded {name} as ' + ' and '.join(roles) + '.' if roles else
                f'I have no confirmed relationship words for {name}.')
    linked = {r['id']: r for reverse in (False, True) for r, _ in
              view.neighbors(ident, ('related_to', 'teaches', 'part_of'), reverse=reverse,
                             kinds=('course', 'project', *WORK))}
    if not linked and not roles:
        return f'I have no confirmed activities with {name}.'
    due = _due(view, [row for row in linked.values() if row['kind'] == 'course'], now)
    direct = [r['name'] for r in linked.values() if not roles or r['kind'] in WORK]
    parts = [f'You recorded {name} as ' + ' and '.join(roles) + '.'] if roles else []
    if direct:
        parts.append(f"Saved links for {name} — {', '.join(dict.fromkeys(direct))}.")
    if due:
        parts.append('Saved for those courses — ' + '. '.join(due) + '.')
    return ' '.join(parts)


def listing(view):
    if not view.entities:
        return 'Your life graph is empty.'
    text = []
    for kind in sorted(KINDS):
        names = [row['name'] for row in view.entities.values() if row['kind'] == kind]
        if names:
            text.append(f'{kind.title()} ({len(names)})\n' + ', '.join(names))
    if view.edges:
        text.append('Confirmed links\n' + '\n'.join(_line(view, edge) for edge in view.edges))
    return '\n\n'.join(text)


def _line(view, edge):
    a, b = (view.entities[edge[key]] for key in ('from_id', 'to_id'))
    label = edge['words'] or edge['relation'].replace('_', ' ')
    return f"{a['name']} · {label} · {b['name']}"


def evening_review():
    items = graph.proposals(1)
    if not items:
        return None
    return proposal_text(items[0])


def proposal_text(p):
    label = p['words'] or p['relation'].replace('_', ' ')
    return (f"Graph proposal #{p['id']} ({p['confidence']:.0%}) — {p['left_name']} · {label} · {p['right_name']}. "
            f"Say “confirm graph link {p['id']}” or “reject graph link {p['id']}”.")


def _parse_statement(text):
    explicit = bool(re.match(r'^(?:link|remember(?: that)?) ', text, re.I))
    sentence = re.sub(r'^(?:link|remember(?: that)?) ', '', text, flags=re.I)
    if PAYLOAD.match(sentence):
        return None
    if role := ROLE.fullmatch(sentence):
        if clean_name('person', role['person']) and normalized(role['person']) not in {'you', 'i', 'she', 'he', 'they', 'it'}:
            return 'role', role, explicit
    if link := LINK.fullmatch(sentence):
        return 'link', link, explicit
    return None


def _endpoint(view, value, kinds):
    match = re.fullmatch(r'(' + '|'.join(sorted(KINDS)) + r') (.+)', _phrase(value), re.I)
    kind = match[1].lower() if match else None
    if kind and kinds and kind not in kinds:
        return [], None
    name = _phrase(match[2] if match else value)
    rows = _resolve(view, name, (kind,) if kind else kinds, fuzzy=False)
    if rows:
        return rows, _node(rows[0]) if len(rows) == 1 else None
    return [], Node(kind, name) if kind and clean_name(kind, name) else None


def _stage(view, statement):
    kind, match, explicit = statement
    if kind == 'role':
        person, words, target = match['person'], match['words'], match['target']
        found, left = _endpoint(view, person, ('person',))
        if len(found) > 1:
            return _clarify(view, found)
        left = left or Node('person', person)
        right = OWNER
        if target:
            found, right = _endpoint(view, target, ('course', 'project'))
            if len(found) > 1:
                return _clarify(view, found)
            if not right:
                return 'Which course or project do you mean? You can give its saved name or say “course” and its name.'
        relation = 'related_to'
    else:
        relation, left_kinds, right_kinds = LINKS[match[2].lower()]
        a, left = _endpoint(view, match[1], left_kinds)
        b, right = _endpoint(view, match[3], right_kinds)
        if len(a) > 1 or len(b) > 1:
            return _clarify(view, a if len(a) > 1 else b)
        if not left or not right:
            return 'Which saved entities should I link? You can give their kinds and names.' if explicit else None
        words = ''
    ident = graph.propose(left, relation, right, words=words)
    return (f'Staged graph link #{ident} for evening review.' if ident else 'That link is unavailable for a new graph proposal.')


def _co_mention(view, text):
    flat = ' ' + normalized(text) + ' '
    matches = {}
    for row in view.entities.values():
        if row['kind'] in ('course', 'project'):
            names = {normalized(n) for n in (row['name'], *row['aliases'])}
            hit = {name for name in names if len(name) >= 3 and f' {name} ' in flat}
            if hit:
                matches.setdefault(row['kind'], []).append((row, hit))
    projects, courses = matches.get('project', []), matches.get('course', [])
    if len(projects) == len(courses) == 1 and projects[0][1] != courses[0][1]:
        return _node(projects[0][0]), _node(courses[0][0])
    return None


def _handle(text, now, remote):
    lower = text.casefold()
    note = notes.match_note_command(text)
    note_body = note['text'] if note and note['action'] == 'add_note' else ''
    statement = _parse_statement((note_body or text).strip().rstrip('.!?'))
    query = next(((action, match[1], kinds) for action, pattern, kinds in QUESTIONS
                  if (match := re.fullmatch(pattern, text, re.I))), None)
    if query and command_slots.has_command_tail(text):
        query = None
    course_time = None
    if re.match(r"^(?:what time is|when(?:'s| is)|show me the time of) ", text, re.I):
        from services.proactive import timetable
        course_time = timetable._COURSE_TIME.fullmatch(text)
        if course_time and command_slots.has_command_tail(text):
            course_time = None
    review, alias, important = REVIEW.fullmatch(text), ALIAS.fullmatch(text), IMPORTANT.fullmatch(text)
    forget = re.fullmatch(r'forget (?P<scope>graph (?:entity )?)?(?P<name>.+)', text, re.I)
    if forget and not forget['scope'] and re.search(
            r"^(?:(?:my|the) )?(?:that|this topic|phone(?: selection)?|project|contacts?|login|routine|"
            r"reminders?|clipboard|correction)\b|\b(?:habit|habits|mode|routine|project|login|password|number)$",
            forget['name'], re.I):
        forget = None
    wording_setting = re.fullmatch(r'turn (?:life )?graph (?:model |llm )?wording (on|off)', lower)
    review_now = lower in {'review graph links', 'review my graph links'}
    evening_turn = evening.match_evening_command(text)
    show, export = lower == 'show my life graph', lower == 'export my graph'
    mention = re.fullmatch(r'mention (.+)', text, re.I)
    scope = (query or review or alias or important or forget or wording_setting or review_now or show or export
             or mention or statement and (statement[0] == 'role' or statement[2]))
    if remote:
        return (result('Life graph commands are available at this laptop.', False, silent=True), None) if scope else (None, None)
    if note and note['action'] in {'list_notes', 'delete_note', 'clear_notes'} and notes.has_private():
        return result(notes.run(note, include_private=True), silent=True), None
    if evening_turn and (proposal := evening_review()):
        return result(proposal, silent=True), None
    if course_time and graph.path.is_file() and not command_slots.course(course_time['course'], native_only=True):
        view = graph.view()
        options = _resolve(view, course_time['course'], ('course',))
        if len(options) > 1:
            return result(_clarify(view, options), False), None
        if options and (course := command_slots.course(course_time['course'], view=view)):
            parsed = {'action': 'course_schedule', 'course': course, 'query': course_time['course'],
                      'day': command_slots.calendar(course_time['day'] or 'today')}
            return result(timetable.run(parsed, now)), None
    if not (scope or statement or note_body):
        return None, None
    if review:
        ok = graph.review(int(review[2]), review[1].casefold() == 'confirm')
        return result(('Graph link confirmed.' if review[1].casefold() == 'confirm' else 'Graph proposal rejected.')
                      if ok else 'That graph link is no longer pending.', ok), None
    if wording_setting:
        enabled = graph.option('model_wording', wording_setting[1])
        return result(f'Graph wording assistance is {enabled}.'), None
    if review_now:
        return result(evening_review() or 'There are no graph links waiting for review.', silent=True), None

    view = graph_sources.refresh()
    if show:
        return result(listing(view), silent=True), None
    if export:
        return result(f'Exported the life graph to {graph.export()}.', silent=True), None
    if query:
        action, phrase, kinds = query
        matches = _resolve(view, _faculty_phrase(phrase) if action == 'due' else phrase, kinds)
        if len(matches) > 1:
            return result(_clarify(view, matches), False), None
        if not matches:
            return result(f"I have no confirmed graph entry for “{phrase}”.", False), None
        body = answer(view, action, matches[0], now)
        rendered = wording.render({'kind': 'graph_answer', 'fact': body}, snapshot={}, now=now)
        counts = Counter(n['kind'] for n in view.entities.values()) if graph.option('model_wording') == 'on' else None
        return result(rendered), counts
    if forget:
        pending = graph.view(include_pending=True)
        matches = _resolve(pending, forget['name'], fuzzy=False)
        if not matches and (near := _resolve(pending, forget['name'])):
            return result('Please give the exact name or alias. ' + _clarify(pending, near), False), None
        if len(matches) != 1:
            return result(_clarify(pending, matches) if matches else 'I have no graph entity by that name.', False), None
        ok = graph.forget(matches[0]['id'])
        return result('Removed that entity and its links from the life graph.' if ok else 'That graph entity is unavailable.', ok), None
    if alias:
        matches = _resolve(view, alias[1] or alias[2])
        if len(matches) != 1:
            return result(_clarify(view, matches) if matches else 'Which graph entity should get an alias?', False), None
        ok = graph.add_alias(matches[0], alias[3])
        return result('Graph alias saved.' if ok else 'The entity changed. Ask again.', ok), None
    if important:
        action, name, package = important.groups()
        if package and (action.casefold() == 'unmark' or not PACKAGE.fullmatch(package)):
            return result('Use the Android package name, for example com.whatsapp.', False), None
        matches = _resolve(view, name, PEOPLE, fuzzy=False)
        if len(matches) > 1:
            return result(_clarify(view, matches), False), None
        person = _node(matches[0]) if matches else Node('person', name)
        if person.key == OWNER.key:
            return result('Choose another person for that setting.', False), None
        ok = graph.mark_important(person, Node('app', package) if package else None, important=action.casefold() == 'mark')
        return result(('Important person marked.' if action.casefold() == 'mark' else 'Important person unmarked.')
                      + (' This prioritizes the selected app channel.' if package else '') if ok else
                      'Use a saved person or a short name.', ok), None

    outcome = _stage(view, statement) if statement else None
    if outcome:
        if note_body:
            outcome = notes.add(note_body, private=True) + ' ' + outcome
        return result(outcome), None
    pair = _co_mention(view, mention[1] if mention else note_body) if mention or note_body else None
    if pair:
        ident = graph.mention(*pair, mention[1] if mention else note_body)
        body = notes.add(note_body, private=True) if note_body else 'Recorded the co-mention locally.'
        if ident:
            body += f' Graph link #{ident} is waiting for confirmation.'
        return result(body), None
    if mention:
        return result('Name one saved project and one saved course.', False), None
    return None, None


async def try_command(message, *, remote=False, now=None):
    from services.automation.system_control import AutomationError
    from services.remote.context import conversation_only, remote_origin
    from services.screen_watch.commands import local_request

    remote = remote or remote_origin.get() or conversation_only.get() or not local_request.get()
    text = command_words.strip_leading_filler(message).strip().rstrip(' .!?')
    if not text or len(text) > 2000:
        return None
    try:
        response, counts = await asyncio.to_thread(_handle, text, now or datetime.now(), remote)
    except (OSError, ValueError, sqlite3.Error, AutomationError) as error:
        logger.debug('Life graph command unavailable (%s)', type(error).__name__)
        known = isinstance(error, (ValueError, AutomationError))
        return result(str(error) if known else 'The local life graph is unavailable.', False, silent=True)
    if counts and config.FRIDAY_LLM == 'on':
        from providers.base_provider import Message
        from providers.failover import complete_with_failover

        openings = ('From your graph.', 'Here is what you saved.')
        try:
            reply = await complete_with_failover(config.ACTIVE_PROVIDER, [Message(role='user', content=json.dumps(counts))],
                'Choose one opening exactly: ' + ' / '.join(openings), 32, purpose='wording', attempt_timeout=3)
            if reply and reply.content in openings:
                response = response._replace(message=reply.content + ' ' + response.message)
        except Exception as error:
            logger.debug('Optional life graph wording unavailable (%s)', type(error).__name__)
    return response
