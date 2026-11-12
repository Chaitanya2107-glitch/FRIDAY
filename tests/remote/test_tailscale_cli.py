from types import SimpleNamespace

import pytest

from services.remote.security import Denied
from services.remote.tailscale import Tailscale


@pytest.mark.parametrize('stream', ['stdout', 'stderr', 'both'])
def test_enable_accepts_help_on_either_stream(stream):
    calls = []

    def run(args, **kwargs):
        calls.append(args[1:])
        assert kwargs['shell'] is False
        if args[1:] == ['serve', '--help']:
            return SimpleNamespace(
                returncode=0,
                stdout='--bg --https --set-path' if stream in {'stdout', 'both'} else '',
                stderr='--bg --https --set-path' if stream in {'stderr', 'both'} else '',
            )
        assert args[1:] == ['serve', '--bg', '--https=443', '--set-path=/', 'http://127.0.0.1:8000/remote']
        return SimpleNamespace(returncode=0, stdout='', stderr='')

    cli = Tailscale('tailscale-mock', run)
    cli.enable(8000)
    assert len(calls) == 2
    assert cli.expected_proxy == 'http://127.0.0.1:8000/remote'


def test_json_status_does_not_mix_diagnostics_into_json():
    cli = Tailscale('tailscale-mock', lambda *args, **kwargs: SimpleNamespace(
        returncode=0, stdout='{}', stderr='local diagnostic'))
    assert cli.json('serve', 'status', '--json') == {}


def test_help_with_failed_exit_is_still_refused():
    cli = Tailscale('tailscale-mock', lambda *args, **kwargs: SimpleNamespace(
        returncode=1, stdout='', stderr='--bg --https --set-path'))
    with pytest.raises(Denied, match='tailscale_unavailable'):
        cli.enable(8000)
