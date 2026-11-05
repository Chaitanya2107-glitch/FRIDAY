"""Reuse the existing monitor; sample only when no monitor reading is arriving."""
import time


def register(api):
    state = api.settings.get('battery', {'low': False, 'critical': False, 'plugged': None})
    last_reading = [time.monotonic()]

    def reading(event):
        last_reading[0] = time.monotonic()
        payload = event['payload']
        percent, plugged = payload.get('percent'), payload.get('plugged')
        if percent is None:
            return  # Desktop PCs without a battery have no battery transitions.
        if type(percent) not in {float, int} or not 0 <= percent <= 100 or type(plugged) is not bool:
            raise ValueError('Invalid battery reading')
        if state['plugged'] is not None and plugged != state['plugged']:
            api.publish('battery.plugged' if plugged else 'battery.unplugged', payload)
        state['plugged'] = plugged
        if percent > 25:
            state['low'] = state['critical'] = False
        for level, threshold in [('low', 20), ('critical', 10)]:
            if percent <= threshold and not state[level]:
                state[level] = True
                api.publish(f'battery.{level}', payload)
        api.settings.set('battery', state)

    api.subscribe('system.battery_reading', reading)
    recent = api.manager.bus.recent('system.battery_reading')
    if recent and time.time() - recent[-1]['at'] < 90:
        reading(recent[-1])

    def fallback():
        if time.monotonic() - last_reading[0] < 90:
            return
        import psutil
        battery = psutil.sensors_battery()
        api.publish('system.battery_reading', {'percent': battery.percent if battery else None,
                                             'plugged': bool(battery.power_plugged) if battery else None})

    api.every(30, fallback)
