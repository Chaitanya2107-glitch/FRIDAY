"""A plugin needs only plugin.json and register(api)."""


def register(api):
    api.on_command(r'hello friday', lambda match: {
        'ok': True, 'text': 'Hello! Your offline plugin is working.', 'error': None,
    }, help='Check the plugin system.', examples=['hello friday'])
    api.subscribe('activity.*', lambda event: api.log.debug('Activity event: %s', event['topic']))
