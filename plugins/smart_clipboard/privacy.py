"""Conservative content checks shared by clipboard actions and optional phone sync."""
import math
import re
from collections import Counter


def sensitive_text(text):
    if not isinstance(text, str) or not text.strip() or len(text) > 65536:
        return True
    if re.search(r'-----BEGIN .*PRIVATE KEY-----|(?:password|passwd|secret|api[_ -]?key|access[_ -]?token|'
                 r'authorization|bearer|otp|verification code)\s*[:= ]\s*\S+', text, re.I):
        return True
    if re.search(r'\b(?:sk-[A-Za-z0-9_-]{16,}|gh[pousr]_[A-Za-z0-9]{20,}|AKIA[A-Z0-9]{16}|'
                 r'eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+)\b', text):
        return True
    if re.fullmatch(r'\s*\d{4,8}\s*', text):
        return True
    for token in re.findall(r'[A-Za-z0-9_+/=-]{24,}', text):
        counts = Counter(token)
        entropy = -sum(n / len(token) * math.log2(n / len(token)) for n in counts.values())
        if entropy > 3.7 and any(c.isdigit() for c in token) and any(c.isalpha() for c in token):
            return True
    return False
