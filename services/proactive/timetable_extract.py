"""Read timetable images through the established prompt/parser without saving."""
import asyncio
import json
import re

from core.config import config
from core.logger import logger
from services.automation.system_control import AutomationError


def parse_classes(reply: str) -> list[dict]:
    """Keep the legacy tolerant JSON parser shared by chat and upload extraction."""
    from services.proactive import timetable
    match = re.search(r'\[\s*\{.*\}\s*\]', reply, re.S)
    if not match:
        return []
    try:
        entries = json.loads(match.group())
    except ValueError:
        return []
    return [c for c in (timetable._clean(e) for e in entries if isinstance(e, dict)) if c]


async def extract_classes(images, provider_name, section='', *, approved_model=None):
    from providers.base_provider import Message
    from providers.failover import complete_with_failover
    from services.proactive import timetable
    section = section or config.TIMETABLE_SECTION.strip()
    prompt = timetable.READ_PROMPT.format(which=timetable.ONE_SECTION.format(section=section) if section else timetable.ALL_CLASSES)
    messages = [Message(role='user', content='Read this timetable.', images=images)]
    if approved_model is None:
        result = await complete_with_failover(config.VISION_PROVIDER or provider_name, messages,
            prompt, timetable.MAX_REPLY_TOKENS, model_for=config.vision_model_for)
    else:
        from providers.registry import get_provider
        # Registry retains the existing purpose policy; no purpose relabeling.
        provider = get_provider(provider_name, model=approved_model)
        if provider_name == 'openrouter':
            # Its ordinary complete() can choose backup models. Consent pins one.
            wire = [{'role': 'system', 'content': prompt},
                    {'role': 'user', 'content': messages[0].openai_content()}]
            completion = provider._complete_with(approved_model, wire, timetable.MAX_REPLY_TOKENS, 0.7, None)
        else:
            completion = provider.complete(messages=messages, system_prompt=prompt, max_tokens=timetable.MAX_REPLY_TOKENS)
        result = await asyncio.wait_for(completion, timeout=90)
    classes = timetable.parse_classes(result.content)
    if not classes:
        logger.warning('Timetable extraction returned no usable classes')
        several = re.search(r'\bsections?\b', result.content, re.I) and not section
        raise AutomationError(
            'That timetable has several sections — say which is yours, like "read my timetable from the screen '
            'for section II-A".' if several else
            "I couldn't read the classes from that. Make sure the whole timetable is visible and try again.")
    return classes
