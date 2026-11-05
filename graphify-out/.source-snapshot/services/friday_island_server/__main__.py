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
    parser.add_argument('--bridge-only', action='store_true', help='Isolated compatibility bridge without FRIDAY runtime')
    parser.add_argument('--island-owner', type=int, help='Native Island process owning the desktop session')
    args = parser.parse_args()
    # websockets DEBUG logs include complete frames, including authentication.
    logging.basicConfig(level=logging.INFO)
    logging.getLogger("services.friday_island_server").setLevel(logging.DEBUG if args.verbose else logging.INFO)
    if not args.bridge_only and args.config is None:
        import sys
        if args.island_owner:
            sys.argv.append(f'--island-owner={args.island_owner}')
        import subprocess
        root = Path(__file__).resolve().parents[2]
        command = [sys.executable, '-B', str(root / 'interfaces/taskbar/launch.py')]
        if args.island_owner:
            command.append(f'--island-owner={args.island_owner}')
        subprocess.run(command, cwd=root, check=True)
        return
    try:
        asyncio.run(Bridge(args.config).run())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
