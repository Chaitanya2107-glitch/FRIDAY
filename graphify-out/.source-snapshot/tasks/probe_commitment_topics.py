"""Exercise real chat/voice topic routes with disposable reports and zero AI calls."""
import argparse
import asyncio
import hashlib
import json
import logging
from pathlib import Path
import sys
import tempfile
import time
from datetime import datetime, timedelta

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
SOURCES = [
    'services/mind/commitment_topics.py', 'services/mind/conversation_context.py',
    'services/mind/dialogue.py', 'services/mind/executive.py', 'services/mind/reference_context.py',
    'services/mind/temporal_memory.py', 'services/mind/brain_memory.py', 'services/mind/cognition.py',
    'services/mind/workspace.py', 'services/automation/intent.py',
    'interfaces/api/routes/chat.py', 'interfaces/api/routes/voice.py',
    'tests/test_commitment_topics.py', 'tasks/probe_commitment_topics.py',
]


def hashes():
    return {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in SOURCES}


async def run(folder):
    from core.config import config
    from core.logger import logger
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()
    logger.addHandler(logging.NullHandler())
    config.MEMORY_DIR = folder
    config.MEMORY_DB_PATH = str(folder / 'chat.db')
    config.COGNITION_ENABLED = config.AI_ASSIST_ONLY = True
    config.AI_LANGUAGE_ENABLED = config.COGNITIVE_REVIEW_ENABLED = False
    from services.mind.cognition import cognition
    from services.mind.brain_memory import BrainMemory
    from services.mind.temporal_memory import TemporalMemory, TemporalUpdate
    from services.mind import commitment_topics
    from services.automation.intent import remote_request
    from interfaces.api.routes import chat, voice
    from providers import failover

    now = datetime(2026, 10, 22, 15)
    commitment_topics.clock = lambda: now
    episodes, temporal = BrainMemory(cognition), TemporalMemory(cognition)
    calls = {'model': 0, 'search': 0}
    async def forbidden_model(*args, **kwargs):
        calls['model'] += 1
        raise AssertionError('A topic reached an AI provider')
    async def forbidden_search(*args, **kwargs):
        calls['search'] += 1
        raise AssertionError('A topic reached search')
    failover.complete_with_failover = forbidden_model
    for module in (chat, voice):
        module.build_file_context = module.build_search_context = forbidden_search

    def save(subject, phrase, supersedes=None):
        text = f'My {subject} is on {phrase}' if not supersedes else f'My {subject} was postponed to {phrase}'
        noted = now if supersedes else now - timedelta(days=1)
        ident = episodes.remember(text, now=noted)
        value = TemporalUpdate(source=f'owner_episode:{ident}', quote=text, subject=subject,
            status='planned', date_phrase=phrase, start=None, end=None, supersedes=supersedes or [])
        known = {**temporal.evidence(), **episodes.evidence()}
        with temporal._db() as db:
            temporal.save(db, temporal.resolve([value], known), noted, known)

    def snapshot():
        with cognition._lock, cognition._connect() as db:
            return {table: [tuple(row) for row in db.execute(f'SELECT * FROM {table} ORDER BY id')]
                    for table in ('owner_episodes', 'temporal_situations')}

    save('robotics exam', 'October 24')
    save('maths exam', 'October 26')
    results = []
    async def check(channel, text, success, fragment):
        before, started = snapshot(), time.monotonic()
        result = (await chat.chat(chat.ChatRequest(message=text)) if channel == 'chat' else
                  await voice._reply(text, voice.VoiceRequest(speak=False)))
        passed = (result.action_success is success and fragment in result.response
                  and not result.awaiting_reply and snapshot() == before)
        row = {'channel': channel, 'text': text, 'expectations_met': passed,
               'response': result.response, 'seconds': round(time.monotonic() - started, 4),
               'reports_unchanged': snapshot() == before}
        results.append(row)
        print(json.dumps({key: row[key] for key in ('channel', 'text', 'expectations_met', 'seconds')}), flush=True)

    await check('chat', 'When is my robotics exam?', True, '2026-10-24')
    await check('voice', 'How many days left?', True, '2 days')
    await check('voice', 'When is it again?', True, 'robotics exam')
    await check('voice', 'What about my maths exam?', True, '2026-10-26')
    await check('chat', 'How many days until it?', True, '4 days')
    await check('chat', 'What was the previous date?', False, 'unavailable')
    await check('chat', 'When is my exam?', False, 'full saved commitment name')
    await check('voice', 'When is it?', False, 'Which saved commitment')
    await check('chat', 'When is my robotics exam?', True, 'robotics exam')
    await check('voice', 'never mind', True, 'saved date is unchanged')
    await check('chat', 'When is it?', False, 'Which saved commitment')
    save('robotics exam', 'November 3', ['temporal:1'])
    await check('chat', 'When is my robotics exam?', True, '2026-11-03')
    await check('voice', 'What was the previous date?', True, '2026-10-24')
    parsed = commitment_topics.topics.match_turn('When is it?')
    token = remote_request.set(True)
    try:
        remote_blocked = (commitment_topics.topics.match_turn('When is it?') is None
                          and not commitment_topics.topics.run(parsed).success)
    finally:
        remote_request.reset(token)
    with episodes._db() as db:
        db.execute('DELETE FROM owner_episodes')
    await check('voice', 'When is it?', True, '2026-11-03')
    cognition.clear()
    await check('chat', 'When is it?', False, 'Which saved commitment')
    return {'results': results, 'remote_blocked': remote_blocked, 'calls': calls,
            'synthetic_stores_only': cognition.path.is_relative_to(folder),
            'persistent_settings_written': False, 'notifications_sent': 0, 'external_actions': 0}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'tasks/topics-final-probe.json')
    args = parser.parse_args()
    before = hashes()
    with tempfile.TemporaryDirectory(prefix='commitment-topics-', dir=ROOT / 'tasks') as directory:
        folder = Path(directory).resolve()
        assert folder.is_relative_to((ROOT / 'tasks').resolve())
        result = asyncio.run(run(folder))
    result.update(sources=before, sources_unchanged=before == hashes())
    args.output.write_text(json.dumps(result, indent=2), encoding='utf-8')
    passed = (result['sources_unchanged'] and result['remote_blocked'] and result['synthetic_stores_only']
              and not any(result['calls'].values()) and all(row['expectations_met'] for row in result['results']))
    sys.exit(0 if passed else 1)
