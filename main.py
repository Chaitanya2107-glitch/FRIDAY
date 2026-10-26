"""
main.py

F.R.I.D.A.Y — Entry point.

Run with:   python main.py
Then open:  http://localhost:8000/docs  to test via Swagger UI
"""

import sys
import threading
import uvicorn
from core.config import config

# Windows consoles default to a legacy codepage (e.g. cp1252) that can't
# encode the box-drawing banner below — force UTF-8 stdout so it doesn't crash.
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")


def main():
    print("")
    print("  ███████╗ ██████╗  ██╗ ██████╗   █████╗ ██╗   ██╗")
    print("  ██╔════╝ ██╔══██╗ ██║ ██╔══██╗ ██╔══██╗╚██╗ ██╔╝")
    print("  █████╗   ██████╔╝ ██║ ██║  ██║ ███████║ ╚████╔╝ ")
    print("  ██╔══╝   ██╔══██╗ ██║ ██║  ██║ ██╔══██║  ╚██╔╝  ")
    print("  ██║      ██║  ██║ ██║ ██████╔╝ ██║  ██║   ██║   ")
    print("  ╚═╝      ╚═╝  ╚═╝ ╚═╝ ╚═════╝  ╚═╝  ╚═╝   ╚═╝   ")
    print("")
    print("  Personal AI Assistant — v0.1.0  |  Phase 1: Foundation")
    print("  ─────────────────────────────────────────────────────")

    # Step 1: Validate config before doing anything
    errors = config.validate()
    if errors:
        print("\n  ❌ Config errors — fix these in your .env file:\n")
        for e in errors:
            print(f"     • {e}")
        print("")
        return

    # Step 2: Create required directories
    config.ensure_dirs()

    # Step 3: Print startup info
    print(f"\n  Provider : {config.ACTIVE_PROVIDER}")
    print(f"  Model    : {_get_active_model()}")
    print(f"  Memory   : {config.MEMORY_DB_PATH}")
    print(f"  Debug    : {config.DEBUG}")
    print(f"\n  API      : http://{config.API_HOST}:{config.API_PORT}")
    print(f"  Docs     : http://{config.API_HOST}:{config.API_PORT}/docs")
    print("\n  ─────────────────────────────────────────────────────")
    print("  Ready. Press CTRL+C to stop.\n")

    # Step 4: Start the server
    options = dict(host=config.API_HOST, port=config.API_PORT,
                   reload=config.API_RELOAD, factory=True,
                   log_level="info" if config.DEBUG else "warning")
    if "--desktop-managed" in sys.argv:
        options["reload"] = False
        server = uvicorn.Server(uvicorn.Config("interfaces.api.app:create_app", **options))
        from interfaces.taskbar.windows import wait_for_backend_stop
        event_name = next(arg.split("=", 1)[1] for arg in sys.argv if arg.startswith("--desktop-stop-event="))
        owner_pid = int(next(arg.split("=", 1)[1] for arg in sys.argv if arg.startswith("--desktop-owner=")))

        def desktop_closed():
            # Keep stdin free for libraries inspecting it during startup. A
            # private Windows event also handles the desktop owner crashing.
            wait_for_backend_stop(event_name, owner_pid)
            server.should_exit = True

        threading.Thread(target=desktop_closed, name="desktop-owner", daemon=True).start()
        server.run()
    else:
        uvicorn.run("interfaces.api.app:create_app", **options)


def _get_active_model() -> str:
    """Return the model name for the active provider."""
    provider = config.ACTIVE_PROVIDER
    if provider == "openrouter":
        return config.OPENROUTER_MODEL
    elif provider == "anthropic":
        return config.ANTHROPIC_MODEL
    elif provider == "openai":
        return config.OPENAI_MODEL
    elif provider == "ollama":
        return config.OLLAMA_MODEL
    return "unknown"


if __name__ == "__main__":
    if "--no-reload" in sys.argv:
        config.API_RELOAD = False
    main()
