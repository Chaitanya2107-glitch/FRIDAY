"""Absolute bootstrap: Windows can relaunch FRIDAY from any working directory."""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> None:
    from interfaces.taskbar.windows import prepare_process
    prepare_process()
    from interfaces.tray.app import main as run_desktop
    run_desktop()


if __name__ == "__main__":
    main()
