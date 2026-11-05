"""Copy this folder, choose a unique manifest ID, and edit register()."""


def register(api):
    def command(match):
        visits = api.settings.get('visits', 0) + 1
        api.settings.set('visits', visits)
        api.publish('my_plugin.used', {'visits': visits})
        return {'ok': True, 'text': f'My plugin ran {visits} times.', 'error': None}

    api.on_command(r'try my plugin', command, help='Run the starter plugin.', examples=['try my plugin'])


def unload():
    pass  # Optional: close resources you opened outside the managed API.
