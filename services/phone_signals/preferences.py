"""Explicit local privacy switches; no phone data is model input by default."""
import json
from core.config import config
from services.settings_store import save

DEFAULTS = dict(ai_app_names=False, teacher=False, telegram_briefings=False)


def load():
    try:
        value = json.loads((config.MEMORY_DIR / 'phone' / 'preferences.json').read_text(encoding='utf-8'))
        return {key: value.get(key) is True for key in DEFAULTS}
    except (OSError, ValueError, AttributeError):
        return dict(DEFAULTS)


def update(**values):
    if set(values) - set(DEFAULTS) or any(type(v) is not bool for v in values.values()):
        raise ValueError('Unknown phone privacy setting')
    save(config.MEMORY_DIR / 'phone' / 'preferences.json', {**load(), **values})
