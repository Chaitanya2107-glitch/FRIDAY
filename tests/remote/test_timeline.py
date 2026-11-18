def test_timeline_is_signed_and_allowlisted(remote, monkeypatch):
    from services.phone_signals import remote as integrations
    from services.remote.commands import Command, no_args
    remote.service.registry.commands['timeline'] = Command(lambda *_: dict(day='2026-11-14',segments=[]), 'safe', no_args)
    path = '/remote/v1/timeline'
    assert remote.client.get(path).status_code == 404
    assert remote.client.get(path, headers=remote.signed(path=path)).json()['segments'] == []
    remote.service.registry.commands.pop('timeline')
    assert remote.client.get(path, headers=remote.signed(path=path)).status_code == 404
