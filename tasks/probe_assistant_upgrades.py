"""Read-only installed-integration checks; never capture audio, message, ring or play."""

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    from core.config import config
    from services.phone.transport import Transport, PhoneError
    from services.spotify import auth, player
    from services.spotify.auth import SpotifyError

    result = {"phone": {}, "spotify": {}, "side_effects": "No notification contents read; no audio, replies, ring or playback."}
    try:
        with Transport() as connection:
            devices = connection.devices()
            result["phone"] = {"native_dbus_connected": True, "paired_reachable_count": len(devices)}
            if len(devices) == 1:
                properties = connection.properties(devices[0])
                result["phone"]["paired"] = properties.get("isPaired") is True
                result["phone"]["reachable"] = properties.get("isReachable") is True
                result["phone"]["notification_interface_available"] = isinstance(connection.notifications(devices[0]), list)
    except PhoneError as error:
        result["phone"] = {"native_dbus_connected": False, "reason": str(error)}
    result["spotify"] = {"configured": bool(config.SPOTIFY_CLIENT_ID), "connected": auth.is_connected()}
    if result["spotify"]["connected"]:
        try:
            result["spotify"]["playback_device_count"] = len(player._api("GET", "/me/player/devices").get("devices", []))
            result["spotify"]["mood_search_track_count"] = len(player._search("chill relaxing", "track", limit=5).get("track", []))
        except SpotifyError as error:
            result["spotify"]["readiness_error"] = str(error)
    (ROOT / "tasks" / "assistant-upgrades-live.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
