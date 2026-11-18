import asyncio
import threading

import pytest

from plugins.smart_clipboard.privacy import sensitive_text
from services.automation.clipboard_history import ClipboardHistory
from services.remote import companion_commands


@pytest.mark.parametrize('text', ['password=hunter22', '-----BEGIN PRIVATE KEY-----', 'Bearer abc.def', 'sk-' + 'a' * 30,
                                'ghp_' + 'A2b3' * 10, '123456', 'api_key: secret', 'otp 023456'])
def test_secret_content_is_skipped(text):
    assert sensitive_text(text)


@pytest.mark.parametrize('text', ['a grocery list', 'https://example.org/article', '2+2', 'a simple note'])
def test_ordinary_clipboard_content(text):
    assert not sensitive_text(text)


def test_phone_clipboard_provenance_survives_restore_and_forget(monkeypatch):
    from services.automation import clipboard
    history = ClipboardHistory()
    history.record('first phone', source='phone', device='first')
    history.record('second phone', source='phone', device='second')
    monkeypatch.setattr(clipboard, 'set_text', lambda text: 10)
    history.restore(2)
    history.forget_phone('first')
    assert history.entries() == [{'text': 'second phone', 'source': 'phone'}]


def test_guarded_local_confirmation_does_not_block_api_loop(monkeypatch):
    from services.automation import intent
    from services.automation.results import ActionResult
    intent.cancel_pending_confirmation()
    intent._ask_first({'action': 'send_whatsapp'}, 'Send?')
    entered, proceed = threading.Event(), threading.Event()
    def execute(parsed, confirmed=False):
        assert confirmed
        entered.set()
        assert proceed.wait(3), 'The API loop was blocked and could not receive phone approval'
        return ActionResult(True, 'sent')
    monkeypatch.setattr(intent, '_execute', execute)
    async def run():
        task = asyncio.create_task(intent._handle_pending_reply('yes', 'local'))
        while not entered.is_set():
            await asyncio.sleep(.001)
        proceed.set()
        assert (await task).success
    asyncio.run(run())


def test_companion_literals_do_not_capture_unrelated_commands():
    for text in ('send note Buy milk to my phone', 'send file C:/a.txt to my phone', 'ring my phone',
                 'enable phone approvals', 'disable phone clipboard sync', 'open phone link'):
        assert companion_commands.matches(text)
    for text in ('send email', 'unlock Windows', 'phone notifications', 'reply: yes'):
        assert not companion_commands.matches(text)


def test_customization_denial_and_revalidation(monkeypatch):
    from services import customization
    from services.remote import phone_approvals
    from services.automation.system_control import AutomationError
    monkeypatch.setattr(phone_approvals, 'guard', lambda parsed: False)
    monkeypatch.setattr(customization, '_change', lambda *a, **k: pytest.fail('Denied change executed'))
    with pytest.raises(AutomationError):
        customization.change('contacts', original=None, name='A', value={}, revision='a' * 64)


def test_companion_command_cancels_previous_local_confirmation(monkeypatch):
    from services.automation import intent
    import services.remote
    intent._ask_first({'action': 'send_whatsapp'}, 'Send?')
    monkeypatch.setattr(services.remote, 'current', lambda: object())
    monkeypatch.setattr(companion_commands, 'run', lambda *a: 'queued')
    assert asyncio.run(companion_commands.try_command('send note Hi to my phone')).success
    assert not intent.is_awaiting_confirmation()


def test_shared_system_router_handles_companion_without_model(monkeypatch):
    from services.automation import intent
    from services.automation.results import ActionResult
    async def companion(message):
        assert message == 'send note Hi to my phone'
        return ActionResult(True, 'waiting', companion_commands.PRIVATE, False)
    monkeypatch.setattr(companion_commands, 'try_command', companion)
    assert asyncio.run(intent.try_system_action('send note Hi to my phone', 'disabled')).message == 'waiting'
