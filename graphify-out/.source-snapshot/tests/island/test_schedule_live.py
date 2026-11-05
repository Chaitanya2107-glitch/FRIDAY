from datetime import datetime
import asyncio
import json

from services.friday_island_server.plugins import CollegePlugin, Registry
from services.proactive import timetable


def test_real_schedule_projection_advances_at_start_end_and_next_day():
    timetable._save([
        {'day': 'monday', 'start': '10:00', 'end': '11:00', 'subject': 'Fixture A'},
        {'day': 'monday', 'start': '11:00', 'end': '12:00', 'subject': 'Fixture B'},
        {'day': 'tuesday', 'start': '09:00', 'end': '10:00', 'subject': 'Fixture C'},
    ])
    clock = [datetime(2030, 1, 7, 9, 59)]
    plugin = CollegePlugin(now=lambda: clock[0])
    assert plugin.live()['text'] == 'Next: Fixture A · 10:00'
    clock[0] = datetime(2030, 1, 7, 10)
    live = Registry([plugin]).snippet()
    assert live['schedule'] == 'Now: Fixture A · until 11:00'
    assert live['text'] == 'Next: Fixture B · 11:00'
    assert 'expires_at' not in live
    assert 'Fixture A' in plugin.widget()['text'] and 'Fixture B' in plugin.widget()['text']
    clock[0] = datetime(2030, 1, 7, 11)
    assert plugin.live()['schedule'] == 'Now: Fixture B · until 12:00'
    assert plugin.live()['text'] == 'Next: Fixture C · Tue 09:00'
    clock[0] = datetime(2030, 1, 7, 12)
    assert plugin.live()['schedule'] == 'Next: Fixture C · Tue 09:00'
    clock[0] = datetime(2030, 1, 8, 8, 50)
    assert 'expires_at' in plugin.live()


def test_compatibility_transport_pushes_schedule_changes_in_seconds(tmp_path):
    from websockets.asyncio.client import connect
    from websockets.asyncio.server import serve
    from services.friday_island_server.config import load_config
    from services.friday_island_server.server import Bridge, ORIGINS
    path = tmp_path / 'island.json'
    config = load_config(path)
    row = {'subject': 'Before edit', 'start': '14:00'}
    bridge = Bridge(path, registry=Registry([CollegePlugin(lambda: dict(row))]))

    async def scenario():
        async with serve(bridge.handle, '127.0.0.1', 0, origins=ORIGINS) as server:
            async with connect(f'ws://127.0.0.1:{server.sockets[0].getsockname()[1]}', origin=ORIGINS[0]) as ws:
                await ws.send(json.dumps({'v': 1, 'type': 'handshake', 'id': 'hello', 'token': config.connection.token}))
                async with asyncio.timeout(3):
                    while (frame := json.loads(await ws.recv()))['type'] != 'pill_snippet_update': pass
                assert 'Before edit' in frame['college_text']
                row['subject'] = 'After edit'
                async with asyncio.timeout(7):
                    while True:
                        frame = json.loads(await ws.recv())
                        if frame['type'] == 'pill_snippet_update' and 'After edit' in frame['college_text']: break
                assert 'After edit' in frame['schedule']
    asyncio.run(scenario())
