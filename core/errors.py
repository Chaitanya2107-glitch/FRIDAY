"""
core/errors.py

Custom exception classes and global error handlers for F.R.I.D.A.Y.

WHY CUSTOM EXCEPTIONS:
  Instead of raising generic Exception("something broke"),
  we raise specific exceptions like ProviderError or MemoryError.
  This makes it easy to handle different failures differently
  and give the user a clear, useful error message every time.

HOW IT WORKS:
  1. Code raises a specific FridayError subclass
  2. The global handler in register_error_handlers() catches it
  3. Returns a clean JSON error to the user — never a raw Python traceback

ERROR RESPONSE FORMAT (always consistent):
  {
    "error": "provider_error",
    "message": "OpenRouter returned a 401 — check your API key",
    "status_code": 502
  }
"""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from core.logger import logger


# ── Custom exception classes ───────────────────────────────────────────────────

class FridayError(Exception):
    """
    Base class for all F.R.I.D.A.Y errors.
    Every custom exception inherits from this.
    """
    def __init__(self, message: str, status_code: int = 500):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


class ProviderError(FridayError):
    """
    Raised when an AI provider call fails.
    Examples: bad API key, rate limit hit, model not found, network timeout.
    """
    def __init__(self, message: str):
        super().__init__(message, status_code=502)   # 502 = Bad Gateway (upstream failed)


class ConfigError(FridayError):
    """
    Raised when required config is missing or invalid.
    Example: OPENROUTER_API_KEY not set in .env
    """
    def __init__(self, message: str):
        super().__init__(message, status_code=500)


class MemoryError(FridayError):
    """
    Raised when reading or writing to the memory database fails.
    """
    def __init__(self, message: str):
        super().__init__(message, status_code=500)


class ValidationError(FridayError):
    """
    Raised when user input fails validation beyond what Pydantic catches.
    Example: message is too long, contains invalid characters.
    """
    def __init__(self, message: str):
        super().__init__(message, status_code=400)   # 400 = Bad Request (user's fault)


class SearchError(FridayError):
    """
    Raised when a web search fails (no internet, DuckDuckGo rate-limiting).
    """
    def __init__(self, message: str):
        super().__init__(message, status_code=502)


# ── Error response builder ─────────────────────────────────────────────────────

def _error_response(error_type: str, message: str, status_code: int) -> JSONResponse:
    """
    Build a consistent JSON error response.
    Every error in F.R.I.D.A.Y looks the same — easy to handle on the frontend.
    """
    return JSONResponse(
        status_code=status_code,
        content={
            "error": error_type,
            "message": message,
            "status_code": status_code,
        }
    )


# ── Global error handlers ──────────────────────────────────────────────────────

def register_error_handlers(app: FastAPI):
    """
    Register global error handlers on the FastAPI app.
    Call this once in app.py when creating the app.

    After this is registered:
      - Any FridayError raised anywhere → clean JSON response
      - Any unhandled Exception → generic 500 with no sensitive details leaked
    """

    @app.exception_handler(ProviderError)
    async def handle_provider_error(request: Request, exc: ProviderError):
        logger.error(f"ProviderError on {request.url.path}: {exc.message}")
        return _error_response("provider_error", exc.message, exc.status_code)

    @app.exception_handler(ConfigError)
    async def handle_config_error(request: Request, exc: ConfigError):
        logger.error(f"ConfigError on {request.url.path}: {exc.message}")
        return _error_response("config_error", exc.message, exc.status_code)

    @app.exception_handler(MemoryError)
    async def handle_memory_error(request: Request, exc: MemoryError):
        logger.error(f"MemoryError on {request.url.path}: {exc.message}")
        return _error_response("memory_error", exc.message, exc.status_code)

    @app.exception_handler(ValidationError)
    async def handle_validation_error(request: Request, exc: ValidationError):
        logger.warning(f"ValidationError on {request.url.path}: {exc.message}")
        return _error_response("validation_error", exc.message, exc.status_code)

    @app.exception_handler(FridayError)
    async def handle_friday_error(request: Request, exc: FridayError):
        # Catch-all for any other FridayError subclass
        logger.error(f"FridayError on {request.url.path}: {exc.message}")
        return _error_response("internal_error", exc.message, exc.status_code)

    @app.exception_handler(Exception)
    async def handle_unhandled_exception(request: Request, exc: Exception):
        # Catch anything that slipped through — log the full traceback
        # but only show a generic message to the user (never leak internals)
        logger.error(
            f"Unhandled exception on {request.url.path}: {exc}",
            exc_info=True   # this includes the full traceback in the log file
        )
        return _error_response(
            "internal_error",
            "Something went wrong on our end. Check the logs for details.",
            500
        )
