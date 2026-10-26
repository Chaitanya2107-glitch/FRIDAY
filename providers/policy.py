"""Purpose-scoped language assistance and local background review."""
from contextvars import ContextVar

from core.config import config
from core.errors import ProviderError

purpose = ContextVar("ai_purpose", default=None)


def check_allowed(task=None):
    task = task or purpose.get()
    if task == "automation_proposal" and not (config.BROWSER_AUTOMATION_ENABLED and config.AI_LANGUAGE_ENABLED):
        raise ProviderError("Supervised automation proposals require enabled automation and language assistance.")
    if task in {"understanding", "conversation"} and not config.AI_LANGUAGE_ENABLED:
        raise ProviderError("AI language understanding is disabled.")
    if task == "notification_review" and not config.NOTIFICATION_REVIEW_ENABLED:
        raise ProviderError("Notification review is disabled.")
    if task == 'inquiry' and not (config.COGNITION_ENABLED and config.REASONING_ENABLED):
        raise ProviderError('Cognitive inquiry is disabled.')
    if task == "cognitive_review" and not (config.COGNITIVE_REVIEW_ENABLED and config.REASONING_ENABLED and config.COGNITION_ENABLED):
        raise ProviderError("Cognitive review is disabled.")
    if not config.AI_ASSIST_ONLY:
        return
    enabled = {"understanding": config.AI_LANGUAGE_ENABLED, "conversation": config.AI_LANGUAGE_ENABLED,
               "automation_proposal": config.BROWSER_AUTOMATION_ENABLED and config.AI_LANGUAGE_ENABLED,
               'inquiry': config.COGNITION_ENABLED and config.REASONING_ENABLED,
               "wording": config.AI_WORDING_ENABLED, "knowledge": config.AI_KNOWLEDGE_ENABLED,
               "notification_review": config.NOTIFICATION_REVIEW_ENABLED,
               "cognitive_review": config.COGNITIVE_REVIEW_ENABLED and config.REASONING_ENABLED and config.COGNITION_ENABLED}
    if not enabled.get(task, False):
        raise ProviderError("Models require an enabled language, wording, knowledge, notification-review or cognitive-review purpose.")
