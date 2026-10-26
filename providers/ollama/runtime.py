"""Start local Ollama on demand; stop only FRIDAY's own server after inactivity."""
import asyncio
import os
import shutil
import subprocess
import time
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit

import httpx
import psutil

from core.config import config
from core.errors import ProviderError
from core.logger import logger


def local_http_options(base_url):
    # Plain loopback HTTP has no TLS handshake or proxy. Avoid loading certificate stores for it.
    url = urlsplit(base_url)
    return {'verify': False, 'trust_env': False} if url.scheme == 'http' and url.hostname in {'localhost', '127.0.0.1', '::1'} else {}


class OllamaRuntime:
    def __init__(self):
        self.process = None
        self.lock = asyncio.Lock()
        self.active = 0
        self.last_used = 0.0
        self.monitor = None
        self.retry_after = 0.0

    async def ready(self, base_url):
        try:
            async with httpx.AsyncClient(timeout=0.5, **{'trust_env': False, **local_http_options(base_url)}) as client:
                response = await client.get(base_url.rstrip("/") + "/api/version")
                return response.status_code == 200
        except httpx.RequestError:
            return False

    async def ensure_running(self, base_url):
        async with self.lock:
            if time.monotonic() < self.retry_after:
                raise ProviderError("Ollama is unavailable; using FRIDAY's saved remarks.")
            if await self.ready(base_url):
                return
            url = urlsplit(base_url)
            if (not config.OLLAMA_AUTO_START or url.hostname not in {"localhost", "127.0.0.1", "::1"}
                    or url.scheme != "http" or url.path.strip("/") or url.username or url.password):
                raise ProviderError("Ollama endpoint is unavailable; automatic start is for local HTTP endpoints only.")
            executable = shutil.which("ollama")
            if not executable and os.name == "nt":
                candidate = Path(os.getenv("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama.exe"
                if candidate.is_file():
                    executable = str(candidate)
            if not executable:
                self.retry_after = time.monotonic() + 30
                raise ProviderError("Ollama is not installed; using FRIDAY's saved remarks.")
            try:
                if self.process is None or self.process.poll() is not None:
                    env = {**os.environ, "OLLAMA_HOST": url.netloc, "OLLAMA_NO_CLOUD": "1"}
                    self.process = subprocess.Popen(
                        [executable, "serve"], env=env, stdin=subprocess.DEVNULL,
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
                    logger.debug("Started FRIDAY's Ollama server (pid %s)", self.process.pid)
                deadline = time.monotonic() + max(1, config.OLLAMA_START_TIMEOUT_SECONDS)
                while time.monotonic() < deadline:
                    if self.process.poll() is not None:
                        raise ProviderError("Ollama exited during startup.")
                    if await self.ready(base_url):
                        if self.monitor is None or self.monitor.done():
                            self.monitor = asyncio.create_task(self.watch_idle())
                        return
                    await asyncio.sleep(0.2)
                raise ProviderError("Ollama startup timed out.")
            except BaseException:
                await self.stop_owned()
                self.retry_after = time.monotonic() + 30
                raise

    @asynccontextmanager
    async def use(self, base_url):
        self.active += 1
        try:
            await self.ensure_running(base_url)
            yield
        finally:
            self.active -= 1
            self.last_used = time.monotonic()

    async def prepare_model(self):
        """Load the configured model without a prompt; the caller owns the time/lease bound."""
        from providers.ollama.client import response_metrics
        started = time.monotonic()
        async with self.use(config.OLLAMA_BASE_URL):
            timings = {'server_ready_ms': round((time.monotonic() - started) * 1000, 2),
                       'model_load_request_ms': 0.0}
            try:
                async with httpx.AsyncClient(timeout=120, **{'trust_env': False, **local_http_options(config.OLLAMA_BASE_URL)}) as client:
                    checked = time.monotonic()
                    response = await client.get(config.OLLAMA_BASE_URL.rstrip('/') + '/api/ps')
                    response.raise_for_status()
                    matches = [model for model in response.json().get('models', [])
                               if config.OLLAMA_MODEL in (model.get('name'), model.get('model'))]
                    contexts = [model['context_length'] for model in matches if type(model.get('context_length')) is int]
                    resident = 16384 in contexts
                    timings['resident_check_ms'] = round((time.monotonic() - checked) * 1000, 2)
                    metrics = {}
                    if not resident:
                        loading = time.monotonic()
                        response = await client.post(config.OLLAMA_BASE_URL.rstrip('/') + '/api/generate', json={
                            'model': config.OLLAMA_MODEL, 'stream': False,
                            'keep_alive': max(1, config.OLLAMA_IDLE_SECONDS), 'options': {'num_ctx': 16384}})
                        response.raise_for_status()
                        data = response.json()
                        timings['model_load_request_ms'] = round((time.monotonic() - loading) * 1000, 2)
                        if data.get('done') is not True or data.get('done_reason') not in {'load', 'stop'}:
                            raise ProviderError('Local model readiness did not finish')
                        if data.get('response') or data.get('eval_count') not in (None, 0):
                            raise ProviderError('Readiness unexpectedly generated content')
                        metrics = response_metrics(data)
                    result = {'was_resident': True if resident else None if matches and not contexts else False,
                              'resident_context_length': 16384 if resident else contexts[0] if contexts else None,
                              'requested_context_length': 16384, **metrics, **timings}
                    logger.debug('Local model readiness: server=%sms lookup=%sms load=%sms compatible=%s',
                                 timings['server_ready_ms'], timings['resident_check_ms'],
                                 timings['model_load_request_ms'], result['was_resident'])
                    return result
            except (httpx.HTTPError, ValueError, TypeError, AttributeError) as error:
                raise ProviderError('Local model readiness unavailable') from error

    async def stop_owned(self):
        process, self.process = self.process, None
        if process is None:
            return
        def stop():
            try:
                parent = psutil.Process(process.pid)
                # PID identity matters: never stop an unrelated process after PID reuse.
                if process.poll() is not None:
                    return
                children = parent.children(recursive=True)
                for child in children:
                    try:
                        child.terminate()
                    except psutil.NoSuchProcess:
                        pass
                process.terminate()
                _, alive = psutil.wait_procs(children, timeout=2)
                for child in alive:
                    child.kill()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=2)
            except psutil.NoSuchProcess:
                pass
        await asyncio.to_thread(stop)
        logger.debug("Stopped FRIDAY's Ollama server")

    async def check_idle(self):
        async with self.lock:
            if self.process and not self.active and time.monotonic() - self.last_used >= max(1, config.OLLAMA_IDLE_SECONDS):
                await self.stop_owned()

    async def watch_idle(self):
        while self.process is not None:
            await asyncio.sleep(min(10, max(1, config.OLLAMA_IDLE_SECONDS)))
            await self.check_idle()

    async def close(self):
        if self.monitor:
            self.monitor.cancel()
            await asyncio.gather(self.monitor, return_exceptions=True)
            self.monitor = None
        async with self.lock:
            await self.stop_owned()


runtime = OllamaRuntime()
