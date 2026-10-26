"""
interfaces/api/app.py

FastAPI application factory.
Creates and configures the app, middleware, routes, and error handlers.

WHY A FACTORY FUNCTION:
  Returning an app from create_app() instead of defining it at module level
  makes it easier to test (create a fresh app per test) and easier to
  extend later (different configs for dev/prod).
"""

import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse

from core.config import config
from core.logger import logger
from core.errors import register_error_handlers
from interfaces.api.routes import body, chat, clipboard, done, files, mind, sharing, spotify, voice, system
from interfaces.api.routes import customization
from interfaces.shell_menu import register_menu as register_file_menu
from services.activity.log import activity_log, watch_activity
from services.automation.clipboard_history import clipboard_history, watch_clipboard
from services.automation import app_finder
from services.files.index import run_indexer
from services.proactive import buttons
from services.proactive.watcher import run_proactive
from services.network.status import watch_network
from services.reminders.service import reminders, run_scheduler
from services.telegram.bot import run_bot
from services.voice.stt import preload as preload_speech_model
from services.voice.tts import tts
from services.watch.auto import run_watches

LOCAL_HOSTS = ("127.0.0.1", "localhost")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Handles startup and shutdown logic.
    Everything before yield runs on startup.
    Everything after yield runs on shutdown.
    """
    logger.info("F.R.I.D.A.Y API started successfully")
    buttons.register_protocol()  # notification buttons open friday:// links
    register_file_menu()  # Explorer: send the selected file to Chaitu
    if config.LEARNING_DATA_ENABLED:
        from services.learning import service as learning_service
        try:
            await asyncio.to_thread(learning_service.refresh, activity_log)
        except Exception as error:
            logger.warning("Learning-data startup refresh unavailable: %s", type(error).__name__)
    from services.mind import cognitive_runtime
    background_loops = [
        asyncio.create_task(cognitive_runtime.run()),
        asyncio.create_task(run_scheduler(reminders)),
        asyncio.create_task(watch_clipboard(clipboard_history)),
        asyncio.create_task(preload_speech_model()),
        asyncio.create_task(tts.prewarm()),
        asyncio.create_task(run_indexer()),  # file search: index, then rescan now and then
        asyncio.create_task(watch_activity(activity_log)),  # which app is in use, for learning habits
        asyncio.create_task(run_proactive()),  # morning briefing and nudges
        asyncio.create_task(asyncio.to_thread(app_finder.wake_everything)),
        asyncio.create_task(watch_network()),  # online → API models, offline → the local model
        asyncio.create_task(run_bot()),  # Telegram: commands from the phone (off without TELEGRAM_BOT_TOKEN)
        asyncio.create_task(run_watches()),  # "it's done" alerts: downloads, heavy work, asked-for watches
    ]
    try:
        yield
    finally:
        from services.browser.service import automation
        await automation.close()
        for loop in background_loops:
            loop.cancel()
        await asyncio.gather(*background_loops, return_exceptions=True)
        from providers.ollama.runtime import runtime
        await runtime.close()
    logger.info("F.R.I.D.A.Y API shutting down")


def create_app() -> FastAPI:
    """Create and return a configured FastAPI application."""

    app = FastAPI(
        title="F.R.I.D.A.Y",
        description="Personal AI Assistant — Local API",
        version="0.2.0",
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
    )

    # ── Local-only protection ─────────────────────────────────────────────────
    # FRIDAY's clients (tray, command bar) are local programs, not web pages.
    # Web pages open in a browser can still fire requests at localhost, so:
    #   - Host must be this machine — blocks DNS rebinding, where a site points
    #     its own domain at 127.0.0.1 to read responses (e.g. chat history).
    #   - A browser Origin must be this API itself (the /docs page) — blocks
    #     "blind" requests from other sites that would still run commands.
    allowed_hosts = sorted({config.API_HOST, *LOCAL_HOSTS})
    allowed_origins = {f"http://{host}:{config.API_PORT}" for host in allowed_hosts}
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=allowed_hosts)

    @app.middleware("http")
    async def reject_other_websites(request: Request, call_next):
        origin = request.headers.get("origin")
        if origin is not None and origin not in allowed_origins:
            logger.warning(f"Blocked {request.method} {request.url.path} from origin {origin}")
            return JSONResponse(
                status_code=403,
                content={
                    "error": "forbidden",
                    "message": "Requests from other websites aren't allowed.",
                    "status_code": 403,
                },
            )
        if request.method in {'POST', 'PUT', 'PATCH', 'DELETE'} and request.url.path.startswith('/api/v1/') and request.url.path not in {'/api/v1/chat', '/api/v1/voice'}:
            from services.mind.cognition import cognition
            with cognition.operation('feature_request', 'api', request.method + ' local feature operation') as operation:
                response = await call_next(request)
                operation.finish('completed' if response.status_code < 400 else 'failed')
                return response
        return await call_next(request)

    # ── Global error handlers ──────────────────────────────────────────────────
    register_error_handlers(app)

    # ── API Routes ────────────────────────────────────────────────────────────
    app.include_router(chat.router, prefix="/api/v1", tags=["Chat & Memory"])
    app.include_router(voice.router, prefix="/api/v1", tags=["Voice"])
    app.include_router(clipboard.router, prefix="/api/v1", tags=["Clipboard"])
    app.include_router(system.router, prefix="/api/v1", tags=["System Control"])
    app.include_router(spotify.router, prefix="/api/v1", tags=["Spotify"])
    app.include_router(files.router, prefix="/api/v1", tags=["File search"])
    app.include_router(sharing.router, prefix="/api/v1", tags=["File sharing"])
    app.include_router(done.router, prefix="/api/v1", tags=["Done alerts"])
    app.include_router(mind.router, prefix="/api/v1", tags=["Mind"])
    app.include_router(body.router, prefix="/api/v1", tags=["Body"])
    app.include_router(customization.router, prefix="/api/v1", tags=["Customization"])

    # ── Health check ──────────────────────────────────────────────────────────
    @app.get("/health", tags=["System"])
    async def health():
        return {
            "status": "online",
            "service": "F.R.I.D.A.Y",
            "version": "0.2.0",
        }

    return app
