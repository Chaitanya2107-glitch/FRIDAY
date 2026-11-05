"""Source inventory for the command parsers; never executes an action."""
import ast
import inspect
from pathlib import Path

from test_feature_language import MATCHERS
from services.automation import intent


def outcome(family, parsed):
    if not parsed:
        return None
    if isinstance(parsed, dict):
        return parsed["action"]
    if family == "conversation" or family == "cognition":
        return parsed
    return {"screen": "screen_question", "learning": "learning_report", "life": "friday_feeling"}[family]


def _value(node, module):
    if isinstance(node, ast.Name):
        return vars(module).get(node.id)
    if isinstance(node, ast.Attribute):
        return getattr(_value(node.value, module), node.attr, None)
    if isinstance(node, (ast.Tuple, ast.List)):
        return [_value(item, module) for item in node.elts]
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "items":
        table = _value(node.func.value, module)
        return list(table.items()) if isinstance(table, dict) else None
    return None


def _bindings(target, value):
    if isinstance(target, ast.Name):
        return [(target.id, value)]
    if isinstance(target, (ast.Tuple, ast.List)) and isinstance(value, (tuple, list)):
        return [pair for child, item in zip(target.elts, value) for pair in _bindings(child, item)]
    return []


def inventory(family):
    fn = MATCHERS[family]
    if family in {"media", "spotify"}:
        fn = intent.match_media_command
    if family in {"screen", "learning", "life"}:
        return {{"screen": "screen_question", "learning": "learning_report", "life": "friday_feeling"}[family]}, set()
    module = inspect.getmodule(fn)
    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8-sig"))
    definitions = {node.name: node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
    todo, seen, actions, unresolved = [fn.__name__], set(), set(), set()
    while todo:
        name = todo.pop()
        if name in seen or name not in definitions or name == "_action":
            continue
        seen.add(name)
        nodes = list(ast.walk(definitions[name]))
        bindings = {}
        for node in nodes:
            if isinstance(node, ast.For):
                for item in _value(node.iter, module) or []:
                    for variable, value in _bindings(node.target, item):
                        if isinstance(value, str):
                            bindings.setdefault(variable, set()).add(value)
        values = []
        for node in nodes:
            if isinstance(node, ast.Dict):
                values.extend(v for k, v in zip(node.keys, node.values)
                              if isinstance(k, ast.Constant) and k.value == "action")
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                if node.func.id in definitions:
                    todo.append(node.func.id)
                if node.func.id == "_action" and node.args:
                    values.append(node.args[0])
            if family == "conversation" and isinstance(node, ast.Return) and isinstance(node.value, ast.Constant):
                if isinstance(node.value.value, str):
                    actions.add(node.value.value)
        for value in values:
            literal = _value(value, module)
            if isinstance(literal, str):
                actions.add(literal)
            elif isinstance(value, ast.Name) and value.id in bindings:
                actions.update(bindings[value.id])
            elif isinstance(value, ast.JoinedStr) and family == "device":
                # The caller supplies these two noun literals; pin the expression
                # so a new computed action shape cannot silently escape the audit.
                expression = ast.unparse(value)
                if expression in {"f'set_{noun}'", "f'change_{noun}'"}:
                    prefix = value.values[0].value
                    actions.update(prefix + noun for noun in ("volume", "brightness"))
                else:
                    unresolved.add(expression)
            elif ast.unparse(value) == "action.split('_')[0]" and family == "execution":
                actions.update(key.split("_")[0] for key in module.NATURAL)
            elif family == "reasoning" and ast.unparse(value) == "match['action'].lower()":
                # Regex named-group domain. Keep a source assertion for new verbs.
                assert "(?P<action>apply|reject)" in inspect.getsource(fn)
                actions.update({"apply", "reject"})
            else:
                unresolved.add(ast.unparse(value))
    if family == "cognition":
        actions.update(module._QUERIES)
    if family == "execution":
        actions = {action.split("_")[0] for action in actions}
    if family in {"media", "spotify"}:
        # This shared helper also builds YouTube URLs, but the media entry point
        # explicitly returns None for YouTube. The apps parser owns that action.
        actions.discard("open_url")
    return actions, unresolved
