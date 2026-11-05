"""Encode explicit synthetic verdicts using the memory critic's source contract."""
import json


def grounded_response(args, response):
    if 'checks' not in response:
        return response
    payload = json.loads(args[1][0].content)
    items = {item['id']: item for item in payload.get('check_items', [])}
    if not any(item['kind'] == 'memory_thread' for item in items.values()):
        return response
    for check in response['checks']:
        item = items[check['id']]
        check['sources'] = [
            {'source': ref, 'quote': payload['source']['evidence'][ref]['text'][:160],
             'supported': check['supported']}
            for ref in item['value']['evidence']] if item['kind'] == 'memory_thread' else []
        if item['kind'] == 'memory_thread' and 'subject' not in item['value']:
            check['relation'] = 'same_situation' if check['supported'] else 'unrelated'
            for row in check['sources']:
                row.update(entity=row['quote'][:100], meaning='Synthetic source-specific meaning.')
    return response
