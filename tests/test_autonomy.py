"""Autonomy stays local and undo uses the recorded effect's identity."""
import asyncio

from services.automation import autonomy, intent
from services.files import filing
from services.presence import commands, rules
from services.presence.rule_store import RuleStore


def test_three_accepts_one_offer_and_undo_drops_one_level():
    for _ in range(3):
        with autonomy.record('set_timer'):
            pass
    assert 'Do and tell' in autonomy.offer_text('set_timer', 'Timer set.')
    assert autonomy.offer_text('set_timer', 'Timer set.') == 'Timer set.'
    assert autonomy.action_level('set_timer') == autonomy.ASK
    assert 'Do and tell' in asyncio.run(commands.try_command('yes')).message
    assert autonomy.action_level('set_timer') == autonomy.TELL

    for _ in range(3):
        with autonomy.record('set_timer'):
            pass
    assert 'Just do' in autonomy.offer_text('set_timer', 'Timer set.')
    asyncio.run(commands.try_command('yes'))
    assert autonomy.action_level('set_timer') == autonomy.SILENT
    assert not asyncio.run(commands.try_command('undo that')).success
    assert autonomy.action_level('set_timer') == autonomy.TELL
    assert not asyncio.run(commands.try_command('undo that')).success
    assert autonomy.action_level('set_timer') == autonomy.TELL
    assert autonomy.offer_text('set_timer', 'Timer set.') == 'Timer set.'


def test_p0_action_type_stays_ask():
    for action in ('open_app', 'lock_pc', 'sleep_pc', 'send_message', 'delete_note', 'clear_notes', 'phone_forget'):
        for _ in range(3):
            with autonomy.record(action):
                pass
        assert autonomy.offer_text(action, 'Done.') == 'Done.'
        assert autonomy.action_level(action) == autonomy.ASK


def test_file_undo_refuses_to_overwrite_and_retries(tmp_path):
    source = tmp_path / 'notes.txt'
    source.write_text('original')
    destination = tmp_path / 'archive'
    filing.move(str(source), str(destination))
    assert not source.exists()
    source.write_text('new')
    reply = asyncio.run(commands.try_command('undo that'))
    assert not reply.success and 'occupied' in reply.message
    assert source.read_text() == 'new'
    assert (destination / source.name).read_text() == 'original'
    source.unlink()
    reply = asyncio.run(commands.try_command('undo that'))
    assert reply.success and source.read_text() == 'original'
    assert not (destination / source.name).exists()


def test_confirmation_and_undo_stay_channel_bound(tmp_path):
    source = tmp_path / 'notes.txt'
    source.write_text('original')
    filing.move(str(source), str(tmp_path / 'archive'))
    token = intent.remote_request.set(True)
    try:
        reply = asyncio.run(commands.try_command('undo that'))
        assert not reply.success and not source.exists()
    finally:
        intent.remote_request.reset(token)
    assert asyncio.run(commands.try_command('undo that')).success and source.exists()


def test_legacy_presence_migration_keeps_rules_and_receipts(tmp_path):
    legacy_path = tmp_path / 'presence-rules.json'
    legacy = RuleStore(legacy_path)
    rule = legacy.add(rules.parse('when I leave home tell me what is due today'), {})
    legacy.patch(rule['id'], level=autonomy.TELL, streak=3, promotion_offered=True)
    run = legacy.begin(rule['id'], 5, 'presence:old')
    legacy.checkpoint(run['id'], [{'type': 'spoken'}], status='completed')
    before = legacy_path.read_bytes()
    with autonomy.record('set_timer'):
        pass

    store = RuleStore(autonomy.file_path(), legacy_path)
    state = store.load()
    assert store.get(rule['id'])['level'] == autonomy.TELL
    assert {row.get('action', row.get('rule')) for row in state['runs']} == {'set_timer', rule['id']}
    assert store.load() == state and legacy_path.read_bytes() == before


def test_negative_feedback_demotes_an_automatic_move_once():
    def promote(state):
        state['actions']['move_file'] = {'level': autonomy.SILENT, 'streak': 3, 'promotion_offered': True}
    autonomy.update(promote)
    with autonomy.record('move_file', origin='automatic'):
        pass
    reply = asyncio.run(commands.try_command('no'))
    assert reply.success and autonomy.action_level('move_file') == autonomy.TELL
    assert asyncio.run(commands.try_command('no')) is None
    assert autonomy.action_level('move_file') == autonomy.TELL


def test_automatic_filing_requires_owner_promotion_and_a_unique_filename(tmp_path, monkeypatch):
    from services.presence import delivery
    from services.proactive import timetable
    from services.watch import auto

    folder = tmp_path / 'College'
    monkeypatch.setattr(filing, 'COLLEGE_DIR', folder)
    timetable._save_subjects(['Finance', 'Management'])
    for i in range(3):
        source = tmp_path / f'training-{i}.txt'
        source.write_text('reviewed')
        response = filing.move(str(source), str(folder / 'Finance'))
    assert 'Do and tell' in response
    assert asyncio.run(commands.try_command('yes')).success

    async def approve(*args, **kwargs):
        return kwargs['on_send']()
    monkeypatch.setattr(delivery, 'submit', approve)
    shown = []
    monkeypatch.setattr('services.reminders.service.show_toast', lambda *args, **kwargs: shown.append(args) or True)
    source = tmp_path / 'Finance test.txt'
    source.write_text('budget')
    auto.announce(source, slow=False)
    assert not source.exists() and (folder / 'Finance' / source.name).exists()
    assert 'Moved Finance test.txt' in shown[0][1]

    ambiguous = tmp_path / 'Finance and Management.txt'
    ambiguous.write_text('Finance')
    auto.announce(ambiguous, slow=False)
    assert ambiguous.exists()


def test_telegram_retracts_only_the_recorded_message(monkeypatch):
    from core.config import config
    from services.telegram import client, commands as telegram_commands

    monkeypatch.setattr(config, 'TELEGRAM_BOT_TOKEN', 'test-token')
    monkeypatch.setattr(config, 'TELEGRAM_USER_ID', 11)
    monkeypatch.setattr(telegram_commands.capabilities, 'ready', lambda: True)
    effects = []
    def call(method, **params):
        effects.append((method, params))
        return {'message_id': 42} if method == 'sendMessage' else True
    monkeypatch.setattr(client, 'call', call)
    assert telegram_commands.run({'action': 'telegram_message', 'text': 'Private test'}).success
    reply = asyncio.run(commands.try_command('undo that'))
    assert reply.success and ('deleteMessage', {'chat_id': 11, 'message_id': 42}) in effects
    assert b'Private test' not in autonomy.file_path().read_bytes()
