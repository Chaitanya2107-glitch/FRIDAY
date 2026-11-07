"""Continuous-category thresholds; no window or app names enter notifications."""
from __future__ import annotations

import math

from .policy import CATEGORIES


class Nudges:
    def __init__(self, policy):
        self.policy = policy
        self.category = None
        self.since = None
        self.last = -math.inf
        self.overrides = {}

    def reset(self):
        self.category = self.since = None

    def set_override(self, category, minutes, owner):
        if (category not in CATEGORIES or type(minutes) not in {int, float} or not 0 < minutes <= 10080
                or not isinstance(owner, str) or not owner or len(owner) > 128):
            raise ValueError('Use a supported category, positive minutes and a nonempty owner.')
        self.overrides.setdefault(owner, {})[category] = float(minutes)

    def clear(self, owner):
        self.overrides.pop(owner, None)

    def check(self, category, now, game_scene=False):
        if category == 'private':
            self.reset()
            return None
        if category != self.category:
            self.category, self.since = category, now
        rules = self.policy.values.get('nudge_rules', {})
        threshold = rules.get(category, math.inf) if isinstance(rules, dict) else math.inf
        if type(threshold) not in {int, float} or not threshold > 0:
            threshold = math.inf
        for values in self.overrides.values():
            threshold = min(threshold, values.get(category, math.inf))
        minutes = (now - self.since) / 60
        cooldown = self.policy.number('nudge_cooldown_minutes', 0) * 60
        if game_scene or minutes < threshold or now - self.last < cooldown:
            return None
        self.last = now
        return {'reason': 'continuous_category', 'minutes': round(minutes, 1), 'category': category}
