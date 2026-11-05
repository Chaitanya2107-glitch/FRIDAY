"""Goal-directed procedural fiction: search valid actions, then realize scenes."""

from dataclasses import dataclass
import heapq
import itertools
import random
import re
import secrets
import shlex

from services.computation.engine import EngineResult


@dataclass(frozen=True)
class Action:
    name: str
    requires: frozenset[str]
    adds: frozenset[str]
    removes: frozenset[str]
    cost: int
    scene: str


def plan(initial: frozenset[str], goal: frozenset[str], actions: list[Action]) -> list[Action]:
    """Dijkstra search over world facts. Positive costs; at most 512 expanded states."""
    order = itertools.count()
    frontier = [(0, next(order), initial, [])]
    best = {initial: 0}
    expanded = 0
    while frontier and expanded < 512:
        cost, _, state, path = heapq.heappop(frontier)
        if cost != best[state]:
            continue
        if goal <= state:
            return path
        expanded += 1
        for action in actions:
            if action.cost <= 0:
                raise ValueError("Story actions require positive costs.")
            if not action.requires <= state:
                continue
            following = (state - action.removes) | action.adds
            candidate = cost + action.cost
            if following == state or candidate >= best.get(following, float("inf")):
                continue
            best[following] = candidate
            heapq.heappush(frontier, (candidate, next(order), following, path + [action]))
    raise ValueError("No complete story plan fits this world and search budget.")


_WORLDS = {
    "scifi": {
        "place": ("the rainlit docks of Kepler Station", "a settlement beneath Europa's ice", "the last city on a wandering moon"),
        "site": ("the silent relay tower", "the abandoned observatory", "the buried navigation vault"),
        "tool": "a cracked service drone", "key": "an obsolete access cylinder",
        "obstacle": "a collapsed maintenance crossing", "device": "the emergency beacon",
        "gift": "a spare power cell", "clue": "a faint repeating signal",
        "discovery": "a maintenance log hidden inside the signal",
    },
    "fantasy": {
        "place": ("the river town of Alderfall", "a village below the glass mountains", "the lantern market of a floating island"),
        "site": ("the ivy-covered watchtower", "the sleeping astronomer's library", "the shrine beyond the mist"),
        "tool": "a damaged climbing harness", "key": "a silver tuning fork",
        "obstacle": "a storm-broken rope bridge", "device": "the valley's warning bell",
        "gift": "the last loaf of travel bread", "clue": "a melody scratched into an old map",
        "discovery": "a caretaker's note between the map's layers",
    },
    "mystery": {
        "place": ("the harbour streets of Bellweather", "a mountain town cut off by winter", "a coastal village before the autumn storm"),
        "site": ("the shuttered lighthouse", "the abandoned weather station", "the locked harbour office"),
        "tool": "a battered survey kit", "key": "a brass master key",
        "obstacle": "a washed-out service bridge", "device": "the storm warning transmitter",
        "gift": "a dry coat from the supply cupboard", "clue": "a coded entry in a missing keeper's ledger",
        "discovery": "the keeper's unfinished repair notes",
    },
}


def generate(payload: str) -> EngineResult:
    options, separator, topic = payload.partition(" about ")
    if payload.startswith("about "):
        options, separator, topic = "", " about ", payload[6:]
    genre, hero, seed = "scifi", None, None
    seen = set()
    for token in shlex.split(options):
        if token in _WORLDS:
            key, value = "genre", token
        elif "=" in token:
            key, value = token.split("=", 1)
        else:
            raise ValueError('Use: story scifi|fantasy|mystery seed=42 hero=Mira [about a lost robot].')
        if key in seen:
            raise ValueError(f"Duplicate story option: {key}.")
        seen.add(key)
        if key == "genre" and value in _WORLDS:
            genre = value
        elif key == "seed" and re.fullmatch(r"\d{1,10}", value) and int(value) < 2 ** 32:
            seed = int(value)
        elif key == "hero" and re.fullmatch(r"[\w -]{1,40}", value) and value.strip():
            hero = value.strip()
        else:
            raise ValueError("Story options: genre=scifi|fantasy|mystery, seed=0..4294967295, hero=<name>.")
    if separator and (not topic.strip() or len(topic) > 180 or any(ord(c) < 32 for c in topic)):
        raise ValueError("A story topic must contain 1-180 printable characters.")
    seed = seed if seed is not None else secrets.randbits(32)
    rng = random.Random(seed)
    world = _WORLDS[genre]
    context = {key: rng.choice(value) if isinstance(value, tuple) else value for key, value in world.items()}
    context["hero"] = hero or rng.choice(("Mira", "Arin", "Noor", "Ishan", "Tavi"))
    context["ally"] = rng.choice(tuple(name for name in ("Sera", "Dev", "Jun", "Leela", "Ren")
                                      if name.casefold() != context["hero"].casefold()))
    objective = rng.choice(("restore the warning before the storm arrived", "guide a stranded traveller home", "recover a lost record before it was destroyed"))
    context["objective"] = objective
    initial = frozenset({"home", "gift"})
    goal = frozenset({"home", "resolved"})

    def action(name, requires, adds, removes, scene):
        return Action(name, frozenset(requires.split()), frozenset(adds.split()),
                      frozenset(removes.split()), rng.randint(1, 7), scene.format(**context))

    actions = [
        action("study_clue", "home", "route", "",
               "{hero} studied {clue}. What first looked like damage repeated too neatly to be accidental. By tracing the pattern, {hero} found a route to {site}."),
        action("repair_tool", "home", "tool", "",
               "Before leaving, {hero} opened {tool} on the kitchen table. Two failed attempts left a black mark on the wood; the third brought a small, reassuring click. It would hold."),
        action("help_ally", "home gift", "ally", "gift",
               "At the supply door, {hero} found {ally} shivering and offered {gift}. 'You will need help out there,' {ally} said. This time, {hero} did not pretend otherwise."),
        action("ask_directions", "home ally", "route", "",
               "{ally} knew a service path to {site}. 'The obvious road is gone,' {ally} warned, drawing a second route in the dust. {hero} memorized each turn."),
        action("travel", "home route", "site", "home",
               "The path ended at {site}. Behind it, the sky was darkening. {hero} could still turn back, but the reason for coming had become more urgent with every step."),
        action("cross_with_tool", "site tool", "across", "site",
               "{obstacle} blocked the final approach. {hero} secured {tool}, tested it once, and crossed slowly. The last support gave way just as solid ground came within reach."),
        action("cross_with_ally", "site ally", "across", "site",
               "At {obstacle}, {hero} stopped. {ally} spotted a narrow lower crossing and held the safety line. Together they reached the other side, soaked and shaking but unhurt."),
        action("search_site", "across", "key", "",
               "Inside, {hero} found {key} beneath a loose panel. It had been left where a frightened person might overlook it, beside {discovery}. Now the silence made sense: someone had tried to finish this work alone."),
        action("restore_warning", "across key tool", "resolved", "key",
               "Using {key} and the repaired equipment, {hero} brought {device} back to life. Its first clear note cut through the storm. Far below, answering lights appeared, one after another."),
        action("restore_with_ally", "across key ally", "resolved", "key",
               "{hero} fitted {key} while {ally} held the failing mechanism steady. {device} answered. Neither could have kept it working alone; together they gave the waiting town enough warning."),
        action("rescue_traveller", "across key ally", "resolved", "key",
               "{key} opened the shelter where the missing traveller had taken refuge. {ally} checked the traveller's injuries while {hero} marked a safe route. 'I thought no one had seen the signal,' the traveller whispered."),
        action("rescue_with_tool", "across key tool", "resolved", "key",
               "The shelter door resisted until {hero} set {tool} against its warped frame and turned {key}. A stranded traveller blinked into the light. The repaired equipment became a lifeline for the slow journey out."),
        action("recover_record", "across key", "resolved", "key",
               "{key} opened the archive. {hero} copied the damaged record before the next leak reached it. The names inside belonged to ordinary people who had done difficult things; losing them would have made the town smaller."),
        action("return_home", "across resolved", "home", "across",
               "By morning, {hero} was back in {place}. The storm had left work for everyone, but the purpose of the journey had been fulfilled. For once, being useful felt less like carrying everything and more like knowing which small thing to do next."),
    ]
    ending = "restore" if objective.startswith("restore") else "rescue" if objective.startswith("guide") else "recover"
    actions = [a for a in actions if not a.name.startswith(("restore", "rescue", "recover")) or a.name.startswith(ending)]
    chosen = plan(initial, goal, actions)
    state, trace = initial, []
    for item in chosen:
        if not item.requires <= state:
            raise ValueError("The story plan failed its prerequisite check.")
        following = (state - item.removes) | item.adds
        trace.append({"action": item.name, "requires": sorted(item.requires), "adds": sorted(item.adds),
                      "removes": sorted(item.removes), "before": sorted(state), "after": sorted(following)})
        state = following
    if not goal <= state:
        raise ValueError("The story plan did not reach its goal.")
    title = rng.choice(("The Last Safe Crossing", "A Light Left Burning", "What the Storm Could Not Take"))
    opening = f"In {context['place']}, {context['hero']} had one night to {objective}."
    if topic.strip():
        opening += f" A note on the desk named the concern in a few words: '{topic.strip()}'."
    prose = "\n\n".join([title, opening, *(item.scene[:1].upper() + item.scene[1:] for item in chosen)])
    return EngineResult(True, "story", prose, (),
                        (f"Procedural fiction; {genre}; seed={seed}; {len(chosen)} valid planned actions. Authored world and scene vocabulary.",),
                        {"seed": seed, "genre": genre, "objective": objective, "topic": topic.strip(),
                         "initial": sorted(initial), "goal": sorted(goal), "final": sorted(state), "plan": trace})
