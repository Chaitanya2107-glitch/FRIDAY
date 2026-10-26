"""Synthetic local-only latency diagnosis; no owner sources or OS actions."""
import asyncio
import json
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import httpx
from core.config import config
from core.logger import logger
from providers.ollama.runtime import runtime
from services.mind.inquiry import Decision, PROMPT


async def run():
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()
    logger.addHandler(logging.NullHandler())
    started = time.monotonic()
    try:
        async with runtime.use(config.OLLAMA_BASE_URL):
            async with httpx.AsyncClient(timeout=55, trust_env=False) as client:
                response = await client.post(config.OLLAMA_BASE_URL.rstrip('/') + '/api/chat', json={
                    'model': config.OLLAMA_MODEL, 'stream': False, 'format': Decision.model_json_schema(),
                    'messages': [{'role': 'system', 'content': PROMPT}, {'role': 'user', 'content':
                        json.dumps({'explicit_request': True, 'evidence': {'task:1': {'title': 'Synthetic report',
                            'blocker': 'Waiting for review notes'}}, 'history': [], 'present': {'busy': False}})}],
                    'options': {'num_ctx': 4096, 'num_predict': 350, 'temperature': 0}})
                response.raise_for_status()
                body = response.json()
                print(json.dumps({'seconds': round(time.monotonic()-started, 2),
                    'content': body.get('message', {}).get('content'),
                    'load_seconds': body.get('load_duration', 0)/1e9,
                    'prompt_seconds': body.get('prompt_eval_duration', 0)/1e9,
                    'generation_seconds': body.get('eval_duration', 0)/1e9,
                    'tokens': body.get('eval_count')}, indent=2))
    except Exception as error:
        print(json.dumps({'seconds': round(time.monotonic()-started, 2), 'error': type(error).__name__}))
    finally:
        await runtime.close()


asyncio.run(run())
