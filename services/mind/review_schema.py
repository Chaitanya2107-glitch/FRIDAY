"""A single kind of cognitive work per native structured response."""
from copy import deepcopy


def single_work(schema):
    props = schema['properties']
    definitions = deepcopy(schema['$defs'])
    # Relative dates are local calendar work, not tokens the model must repeat/calculate.
    temporal = definitions['TemporalUpdate']
    for key in ('start', 'end'):
        temporal['properties'].pop(key)
        temporal['required'].remove(key)
    definitions['Conclusion']['properties']['text']['maxLength'] = 240
    definitions['TaskPlan']['properties']['steps']['maxItems'] = 5
    definitions['TaskPlan']['properties']['steps']['items']['maxLength'] = 120
    branches = []
    for work in ('situations', 'memories', 'conclusions', None):
        if work and props[work].get('maxItems') == 0:
            continue
        variant = {'work_kind': {'type': 'string', 'const': work or 'silence'}}
        if work == 'situations':
            variant['items'] = {'type': 'array', 'minItems': 1, 'maxItems': props[work]['maxItems'],
                                'items': {'$ref': '#/$defs/TemporalUpdate'}}
        elif work:
            definition = 'MemoryThread' if work == 'memories' else 'Conclusion'
            variant['item'] = {'$ref': '#/$defs/' + definition}
        branches.append({'type': 'object', 'additionalProperties': False,
                         'properties': variant, 'required': list(variant)})
    schema = {'oneOf': branches}
    used = set()
    def visit(value):
        if isinstance(value, dict):
            for key, child in value.items():
                if key == '$ref' and child.startswith('#/$defs/'):
                    name = child.split('/')[-1]
                    if name not in used:
                        used.add(name)
                        visit(definitions[name])
                else:
                    visit(child)
        elif isinstance(value, list):
            for child in value: visit(child)
    visit(schema)
    schema['$defs'] = {key: value for key, value in definitions.items() if key in used}
    return schema


def unpack(value):
    """Expand compact native output into the existing strict internal report contract."""
    if not isinstance(value, dict):
        raise ValueError('A cognitive report must be an object')
    if any(key in value for key in ('facts', 'conclusions', 'questions', 'situations', 'memories')):
        return value  # Existing internal/in-flight reports still receive full normal validation.
    kind = value.get('work_kind')
    field = 'items' if kind == 'situations' else 'item' if kind in {'memories', 'conclusions'} else None
    if kind not in {'situations', 'memories', 'conclusions', 'silence'} or set(value) != {'work_kind', *([field] if field else [])}:
        raise ValueError('A cognitive response must select exactly one work item or silence')
    report = {'work_kind': kind, 'facts': [], 'conclusions': [], 'questions': [], 'situations': [], 'memories': []}
    if kind == 'situations':
        items = value['items']
        if not isinstance(items, list) or any(not isinstance(item, dict) or 'start' in item or 'end' in item for item in items):
            raise ValueError('Temporal wire dates must be omitted and resolved by the local calendar')
        report[kind] = [{**item, 'start': None, 'end': None} for item in items]
    elif field:
        report[kind] = [value[field]]
    return report


def repair_work_kind(value, previous):
    """Keep a correction in its selected scope, even when its body is malformed."""
    work = value.get('work_kind')
    if work is None:
        kinds = [key for key in ('situations', 'memories', 'conclusions')
                 if isinstance(value.get(key), list) and value[key]]
        # Preserve the existing priority for older mixed temporal/memory reports.
        work = 'situations' if 'situations' in kinds else kinds[0] if len(kinds) == 1 else None
    if work not in ('situations', 'memories', 'conclusions', 'silence'):
        return previous  # the full model validator still refuses malformed selectors
    if previous and work not in (previous, 'silence'):
        raise ValueError('A correction retry must repair the selected work kind or choose silence')
    return previous or work
