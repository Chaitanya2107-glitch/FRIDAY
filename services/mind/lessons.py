"""Deterministic matching of owner-reviewed lessons. No inference or model access."""
import re


def key(text):
    text = text.lower().replace("’", "'").replace("favorite", "favourite")
    text = re.sub(r"\bwhat's\b", "what is", text)
    return " ".join(re.findall(r"\w+", text))


def owner_question(text):
    return key(re.sub(r"\byour\b", "my", text, flags=re.I))


def personal_question(text):
    text = re.sub(r"^tell me\s+", "tell ", text, flags=re.I)
    return bool(re.match(r"^(?:what|who|where|when|how|why|do you remember|tell)\b", text, re.I)
                and re.search(r"\b(?:my|me|mine|our|we|i)\b", text, re.I))


def keywords(text):
    ignored = {"what", "whats", "s", "is", "are", "was", "were", "the", "a", "an", "my", "your", "me",
               "i", "our", "we", "who", "where", "when", "how", "why", "do", "does", "did", "you", "about",
               "remember", "know", "tell", "name", "please", "can", "could", "of", "to", "have", "has"}
    return set(key(text).split()) - ignored


def reply(rows, query):
    wanted = key(query)
    for row in rows:  # newest applied lesson first; exact examples never choose actions
        aliases = {key(row["question"])}
        if row["kind"] == "question":
            aliases.add(owner_question(row["question"]))
        if row["kind"] in {"example", "question"} and wanted in aliases:
            if row["preferred"]:
                return row["preferred"]
            if row["teaching"]:
                return "You taught me: " + row["teaching"]
    if not personal_question(query):
        return None
    terms = keywords(query)
    matches = []
    for row in rows:
        evidence = keywords(row["teaching"])
        if row["kind"] == "question":
            evidence |= keywords(row["question"])
        if terms and row["teaching"] and terms <= evidence and row["teaching"] not in matches:
            matches.append(row["teaching"])
    if matches:
        # Conflicting statements are shown as evidence, not silently resolved by a guess.
        return "You taught me: " + matches[0] if len(matches) == 1 else "Reviewed memories:\n" + "\n".join(matches[:5])
    return None
