from activity_support import make_activity


def test_scene_snapshot_reconciles_missed_end_without_removing_other_owners(tmp_path):
    value = make_activity(tmp_path)
    try:
        owner = 'scenes:' + 'a' * 32
        value.tracker.scene(dict(topic='scene.started', payload={'name': 'game', 'scene_id': owner}))
        value.tracker.set_threshold_override('games', 10, owner)
        value.tracker.set_threshold_override('games', 20, 'another-plugin')
        value.tracker.scene(dict(topic='scene.state', plugin_id='scenes', payload={'name': None, 'scene_id': None, 'phase': 'idle'}))
        assert owner not in value.tracker.scenes and owner not in value.tracker.nudges.overrides
        assert 'another-plugin' in value.tracker.nudges.overrides
        value.tracker.scene(dict(topic='scene.state', plugin_id='scenes', payload={'name': 'private', 'scene_id': owner, 'phase': 'active'}))
        assert value.tracker.paused()
        value.tracker.scene(dict(topic='scene.state', plugin_id='untrusted-event-source', payload={'name': None, 'scene_id': None}))
        assert value.tracker.paused()
    finally:
        value.api.stop(); value.tracker.close(); value.manager.bus.close()
