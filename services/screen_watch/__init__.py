"""Local, read-only screen awareness with explicit desktop controls."""
def create_reader(stopped):
    """Defer COM-dependent imports until the owned worker has selected MTA."""
    from services.screen_watch.capture import ScreenReader
    return ScreenReader(stopped)
