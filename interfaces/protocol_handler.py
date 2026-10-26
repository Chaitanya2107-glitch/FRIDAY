"""
interfaces/protocol_handler.py

Runs when a button on a FRIDAY notification is clicked: Windows opens the
button's friday:// link with this script (registered by
services/proactive/buttons.py). It only passes the token and answer on to the
local API, which checks them against the notifications it really showed.

    pythonw protocol_handler.py "friday://habit?token=…&answer=open" 8000

Standard library only, so it starts fast.
"""

import json
import re
import sys
import urllib.request
from urllib.parse import parse_qs, urlsplit


def main(link: str, port: str) -> None:
    query = parse_qs(urlsplit(link).query)
    token, answer = query.get("token", [""])[0], query.get("answer", [""])[0]
    if not (re.fullmatch(r"[\w-]{10,64}", token) and re.fullmatch(r"[a-z]{1,12}", answer) and port.isdigit()):
        return  # not a link FRIDAY made
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/api/v1/notify/respond",
        data=json.dumps({"token": token, "answer": answer}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        urllib.request.urlopen(request, timeout=10).read()
    except OSError:
        pass  # FRIDAY isn't running, or the notification expired — nothing to do


if __name__ == "__main__" and len(sys.argv) >= 3:
    main(sys.argv[1], sys.argv[2])
