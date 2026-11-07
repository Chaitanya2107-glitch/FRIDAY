from types import SimpleNamespace

from scenes_support import make_scenes
from plugins.hud.main import HUD


def test_hud_uses_actual_timer_deadline_after_resume_and_restart(tmp_path):
    host = make_scenes(tmp_path)
    try:
        hud = HUD(host.api)
        host.manager.services['focus'] = SimpleNamespace(status=lambda: dict(active=True, state='running',
            minutes=25, remaining_s=600, end_at=123456., session_id='actual'))
        hud.focus = dict(session_id='old-event', duration_s=1500, ends_at=999999., remaining_s=None)
        assert hud.state()['focus']['ends_at'] == 123456.
        assert hud.state()['focus']['session_id'] == 'actual'
        host.manager.services['focus'].status = lambda: dict(active=True, state='paused', minutes=25,
            remaining_s=600, end_at=None, session_id='actual')
        assert hud.state()['focus']['remaining_s'] == 600 and hud.state()['focus']['ends_at'] is None
        host.manager.services['focus'].status = lambda: {'active': False}
        assert hud.state()['focus'] is None
    finally:
        host.api.stop(); host.engine.close(); host.manager.bus.close()


def test_hud_scene_snapshot_clears_missed_end_and_keeps_other_providers(tmp_path):
    host = make_scenes(tmp_path)
    try:
        hud = HUD(host.api)
        hud.scenes = {'legacy:work': 'work', 'scenes:old': 'game'}
        hud.event(dict(topic='scene.state', plugin_id='scenes', payload=dict(name=None, scene_id=None)))
        assert hud.scenes == {'legacy:work': 'work'}
        count = len(host.manager.bus.recent('hud.state_changed'))
        hud.event(dict(topic='scene.state', plugin_id='scenes', payload=dict(name=None, scene_id=None)))
        assert len(host.manager.bus.recent('hud.state_changed')) == count
    finally:
        host.api.stop(); host.engine.close(); host.manager.bus.close()
