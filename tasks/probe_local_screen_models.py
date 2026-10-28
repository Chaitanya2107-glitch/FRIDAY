"""Use synthetic lecture text/images only, never the desktop, to check local inference."""
import asyncio
import io
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


async def main():
    import httpx
    from PIL import Image, ImageDraw, ImageFont
    from providers.ollama.runtime import runtime
    from services.screen_watch.inference import analyze
    results = []
    original = httpx.AsyncClient
    class SyntheticClient(original):
        async def post(self, url, **kwargs):
            response = await super().post(url, **kwargs)
            if str(url).endswith("/api/chat"):
                data = response.json()
                print(json.dumps({"synthetic_response": data.get("message", {}).get("content", "")[:1600],
                                  "done_reason": data.get("done_reason"), "tokens": data.get("eval_count")}), flush=True)
            return response
    httpx.AsyncClient = SyntheticClient
    try:
        for kind in ("text", "vision"):
            text = "Graph theory lecture notes. Studying nodes and edges. A graph contains vertices linked by edges."
            image = None
            if kind == "vision":
                frame = Image.new("RGB", (900, 420), "white")
                draw = ImageDraw.Draw(frame)
                font = ImageFont.truetype("arial.ttf", 38)
                draw.text((30, 24), "GRAPH THEORY LECTURE", fill="black", font=font)
                draw.text((30, 90), "Notes: Nodes and Edges", fill="black", font=font)
                draw.line((140, 240, 430, 330, 730, 210), fill="black", width=6)
                for x, y in ((140, 240), (430, 330), (730, 210)):
                    draw.ellipse((x - 26, y - 26, x + 26, y + 26), fill="navy")
                buffer = io.BytesIO()
                frame.save(buffer, format="JPEG")
                image, text = buffer.getvalue(), ""
                frame.close()
            started = time.monotonic()
            result = await analyze("owned-lecture-fixture", text, image)
            assert not result.sensitive
            assert any(word in (result.summary + " " + result.activity).lower()
                       for word in ("graph", "lecture", "notes", "node", "stud", "read"))
            results.append({"source": kind, "seconds": round(time.monotonic() - started, 3),
                            "semantic_check": True, "needs_vision": result.needs_vision})
            print(json.dumps(results[-1]), flush=True)
        (ROOT / "tasks/screen-model-probes.json").write_text(
            json.dumps({"synthetic_only": True, "screen_captured": False, "results": results}, indent=2),
            encoding="utf-8")
    finally:
        httpx.AsyncClient = original
        await runtime.close()


if __name__ == "__main__":
    asyncio.run(main())
