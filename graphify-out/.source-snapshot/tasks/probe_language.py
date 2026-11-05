"""Bounded synthetic language probe: no commands execute and no memories are saved."""
import asyncio
import json
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.config import config
from core.logger import logger
from services.mind import language
from providers.ollama.runtime import runtime


async def main():
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()
    logger.addHandler(logging.NullHandler())
    results = []
    async with asyncio.timeout(90):
        for message in ['bro the speakers r too loud bring em down to 23',
                        'could u get chrome running for me pls']:
            started = time.monotonic()
            command = await language.understand(message, config.ACTIVE_PROVIDER)
            results.append({'input': message, 'command': command,
                            'seconds': round(time.monotonic() - started, 2)})
        started = time.monotonic()
        reply = await language.answer('Hi Friday, can we talk for a minute?', config.ACTIVE_PROVIDER, [], 120)
        results.append({'conversation_provider': reply.provider, 'model': reply.model,
                        'reply': reply.content, 'seconds': round(time.monotonic() - started, 2)})
    print(json.dumps(results, indent=2))


if __name__ == '__main__':
    async def run():
        try:
            await main()
        finally:
            await runtime.close()
    asyncio.run(run())
