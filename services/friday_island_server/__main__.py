"""Run from the repository: python -m services.friday_island_server."""
import argparse
import asyncio
import logging
from pathlib import Path

from .server import Bridge


def main():
    parser = argparse.ArgumentParser(description="FRIDAY Island loopback bridge")
    parser.add_argument("--config", type=Path, help="Isolated config path (default: APPDATA/FRIDAY/island/config.json)")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()
    # websockets DEBUG logs include complete frames, including authentication.
    logging.basicConfig(level=logging.INFO)
    logging.getLogger("services.friday_island_server").setLevel(logging.DEBUG if args.verbose else logging.INFO)
    try:
        asyncio.run(Bridge(args.config).run())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
