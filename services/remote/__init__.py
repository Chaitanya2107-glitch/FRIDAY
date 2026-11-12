"""Owner-paired remote transport on FRIDAY's existing loopback bridge."""

_service = None


def current():
    global _service
    if _service is None:
        from core.config import config
        from .service import RemoteService
        _service = RemoteService(config.MEMORY_DIR / 'remote', config.API_PORT)
    return _service


def start_bridge():
    global _service
    from core.config import config
    from .service import RemoteService
    if _service is not None:
        _service.fence_off()
    _service = RemoteService(config.MEMORY_DIR / 'remote', config.API_PORT)
    return _service
