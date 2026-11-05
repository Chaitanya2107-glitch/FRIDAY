"""Prevent query tokens from appearing in HTTP access logs."""
import logging


class PathOnlyAccess(logging.Filter):
    def filter(self, record):
        if isinstance(record.args, tuple) and len(record.args) == 5:
            args = list(record.args)
            if isinstance(args[2], str):
                args[2] = args[2].split('?', 1)[0]
                record.args = tuple(args)
        return True


def protect_access_logs():
    logger = logging.getLogger('uvicorn.access')
    if not any(isinstance(item, PathOnlyAccess) for item in logger.filters):
        logger.addFilter(PathOnlyAccess())
