from contextvars import ContextVar
from contextlib import contextmanager

# This transport never shares Telegram's temporary command/dialogue state.
conversation_only = ContextVar('remote_conversation_only', default=False)
remote_origin = ContextVar('tailscale_remote_origin', default=False)


@contextmanager
def origin_scope(remote=False):
    token = remote_origin.set(remote_origin.get() or remote)
    try:
        yield
    finally:
        remote_origin.reset(token)
