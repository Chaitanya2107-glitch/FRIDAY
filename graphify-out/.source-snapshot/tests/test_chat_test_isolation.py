"""API history tests must never operate on the owner's singleton database."""
import asyncio
from pathlib import Path

from core.config import config
from interfaces.api.routes import chat, voice


def test_both_entrypoints_use_the_fixture_database_and_clear_only_that_history(tmp_path):
    path = Path(chat._memory.db_path)
    assert path == Path(config.MEMORY_DB_PATH) and path.is_relative_to(tmp_path.parent)
    assert not path.is_relative_to(tmp_path)
    assert voice._memory is chat._memory
    chat._memory.save_message("user", "Isolated chat test.")
    assert voice._memory.get_recent_history()[0]["content"] == "Isolated chat test."
    asyncio.run(chat.clear_history())
    assert not chat._memory.get_recent_history()
