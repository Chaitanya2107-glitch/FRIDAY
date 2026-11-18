"""The shared finite trust ladder; a suggestion never grants permission by itself."""


def accepted(row):
    return {**row, 'streak': row['streak'] + 1}


def declined(row):
    return {**row, 'level': 'ask', 'streak': 0}


def can_offer(row, risky=False):
    return not risky and row['streak'] >= 3 and not row['promotion_offered']
