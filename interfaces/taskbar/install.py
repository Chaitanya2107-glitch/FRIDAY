"""Install FRIDAY's taskbar widget launcher for the current Windows user."""

import argparse
import os
from pathlib import Path
import subprocess

from interfaces.taskbar.windows import ROOT, LAUNCH_PATH, create_shortcut, pythonw


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", type=Path, help="Optional .lnk path; default is the user's Start menu")
    parser.add_argument("--launch", action="store_true", help="Open FRIDAY after installing the shortcut")
    parser.add_argument("--startup", action="store_true", help="Show the widget after signing into Windows")
    args = parser.parse_args()
    destination = args.destination or (Path(os.environ["APPDATA"]) / "Microsoft/Windows/Start Menu/Programs/FRIDAY.lnk")
    path = create_shortcut(destination)
    print(f"FRIDAY shortcut: {path}")
    if args.startup:
        startup = Path(os.environ["APPDATA"]) / "Microsoft/Windows/Start Menu/Programs/Startup/FRIDAY Widget.lnk"
        print(f"Sign-in shortcut: {create_shortcut(startup)}")
    if args.launch:
        subprocess.Popen([str(pythonw()), "-B", str(LAUNCH_PATH)], cwd=ROOT)
    print("FRIDAY's taskbar button stays available while the assistant is stopped.")


if __name__ == "__main__":
    main()
