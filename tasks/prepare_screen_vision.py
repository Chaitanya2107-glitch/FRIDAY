"""Install and verify the small local vision dependency; never read the screen."""
import asyncio
import json
from pathlib import Path
import sys
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
MODEL = "qwen3-vl:2b"


async def main():
    import httpx
    from core.config import config
    from providers.ollama.runtime import runtime
    base = config.OLLAMA_BASE_URL.rstrip("/")
    url = urlsplit(base)
    assert url.scheme == "http" and url.hostname in {"localhost", "127.0.0.1", "::1"}
    assert not (url.username or url.password or url.path or url.query or url.fragment)
    try:
        async with runtime.use(base), httpx.AsyncClient(timeout=30, trust_env=False, follow_redirects=False) as client:
            version = (await client.get(base + "/api/version")).json().get("version")
            tags = (await client.get(base + "/api/tags")).json().get("models", [])
            if not any(m.get("name") == MODEL for m in tags):
                async with client.stream("POST", base + "/api/pull", json={"model": MODEL, "stream": True},
                                         timeout=httpx.Timeout(30, read=900)) as response:
                    response.raise_for_status()
                    last = None
                    async for line in response.aiter_lines():
                        if not line:
                            continue
                        data = json.loads(line)
                        if data.get("error"):
                            raise RuntimeError("The local model download failed.")
                        percent = int(100 * data.get("completed", 0) / data["total"]) // 10 * 10 if data.get("total") else None
                        mark = (data.get("status", "").split()[0], percent)
                        if mark != last:
                            print(json.dumps({"phase": mark[0], "percent": percent}), flush=True)
                            last = mark
            response = await client.post(base + "/api/show", json={"model": MODEL})
            response.raise_for_status()
            shown = response.json()
            assert "vision" in shown.get("capabilities", [])
            assert not shown.get("remote_host") and not shown.get("remote_model")
            result = {"model": MODEL, "ollama_version": version, "vision": True,
                      "local_only": True, "screen_captured": False}
            (ROOT / "tasks/screen-model-readiness.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
            print(json.dumps(result), flush=True)
    finally:
        await runtime.close()


if __name__ == "__main__":
    asyncio.run(main())
