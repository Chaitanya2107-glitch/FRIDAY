"""Read-only public-network smoke check; no forms, credentials or owner data."""

import asyncio
import json
import sys
import tempfile
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.browser.runtime import BrowserRuntime
from services.search.web_search import _search


async def main():
    results = await asyncio.wait_for(asyncio.to_thread(_search, "Python official tutorial", private=True), 20)
    assert results
    with tempfile.TemporaryDirectory(prefix="friday-public-probe-") as temporary:
        stopped = threading.Event()
        runtime = BrowserRuntime(stopped, Path(temporary))
        try:
            await runtime.call("start", True)
            url, title, text = await runtime.call("read", "https://docs.python.org/3/tutorial/")
            assert "Python" in title and len(text) > 1000
            result = {"search_results": len(results), "public_rendered_fetch": True,
                      "url": url, "title": title, "extracted_characters": len(text)}
        finally:
            stopped.set()
            await runtime.aclose()
    (ROOT / "tasks" / "browser-automation-public.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result))


if __name__ == "__main__":
    asyncio.run(main())
