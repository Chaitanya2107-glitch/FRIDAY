"""Public calculation boundary: bounded input, owned process, exact result data."""

from dataclasses import asdict, dataclass, field
import json
import os
from pathlib import Path
import subprocess
import sys
import threading

MAX_INPUT = 1600
TIMEOUT_SECONDS = 8
_slots = threading.BoundedSemaphore(2)
_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class EngineResult:
    success: bool
    domain: str
    value: str
    steps: tuple[str, ...] = ()
    assumptions: tuple[str, ...] = ()
    details: dict = field(default_factory=dict)

    def render(self) -> str:
        if not self.success:
            return f"Calculation unavailable: {self.value}"
        parts = [self.value]
        if self.steps:
            parts.append("Working:\n" + "\n".join(f"- {step}" for step in self.steps))
        if self.assumptions:
            parts.append("Assumptions: " + " ".join(self.assumptions))
        return "\n\n".join(parts)


def calculate(command: str) -> EngineResult:
    """Compute without network/models; timeouts kill and reap the owned child."""
    if not isinstance(command, str) or not command.strip() or len(command) > MAX_INPUT:
        return EngineResult(False, "engine", f"Use a nonempty command of at most {MAX_INPUT} characters.")
    if not _slots.acquire(blocking=False):
        return EngineResult(False, "engine", "The two calculation slots are busy. Try again shortly.")
    try:
        executable = Path(sys.executable)
        if executable.name.lower() == "pythonw.exe":
            executable = executable.with_name("python.exe")
        environment = None
        if os.name == "nt":
            # The Windows venv redirector spawns another interpreter. Launch its
            # base directly so subprocess timeout owns the actual worker PID.
            environment = os.environ.copy()
            environment["__PYVENV_LAUNCHER__"] = str(executable)
            executable = Path(getattr(sys, "_base_executable", str(executable))).with_name("python.exe")
        completed = subprocess.run(
            [str(executable), "-I", "-B", str(_ROOT / "services/computation/worker.py")],
            input=json.dumps({"command": command}), text=True, encoding="utf-8",
            capture_output=True, timeout=TIMEOUT_SECONDS, cwd=_ROOT, env=environment,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        if completed.returncode or len(completed.stdout) > 48000:
            return EngineResult(False, "engine", "The calculation worker could not return a result.")
        data = json.loads(completed.stdout)
        if (not isinstance(data, dict) or type(data.get("success")) is not bool
                or not isinstance(data.get("value"), str) or not isinstance(data.get("domain"), str)
                or not isinstance(data.get("steps", []), list)
                or not isinstance(data.get("assumptions", []), list)
                or not all(isinstance(v, str) for v in data.get("steps", []) + data.get("assumptions", []))
                or not isinstance(data.get("details", {}), dict)):
            raise ValueError("Invalid worker response")
        return EngineResult(data["success"], data["domain"], data["value"],
                            tuple(data.get("steps", [])), tuple(data.get("assumptions", [])),
                            data.get("details", {}))
    except subprocess.TimeoutExpired:
        return EngineResult(False, "engine", f"Calculation exceeded {TIMEOUT_SECONDS} seconds and was stopped.")
    except (OSError, ValueError, TypeError):
        return EngineResult(False, "engine", "The local calculation worker is unavailable.")
    finally:
        _slots.release()


def evaluate(command: str) -> EngineResult:
    """Worker-only dispatch. Call calculate() for the bounded public entry point."""
    from services.computation.commands import HELP, canonical
    query = canonical(command)
    if query is None:
        raise ValueError('Use "engine help" for the supported command syntax.')
    if query.casefold() in {"engine", "engine help", "engine status"}:
        return EngineResult(True, "engine", HELP)
    head, _, tail = query.partition(" ")
    if head == "story":
        from services.computation.stories import generate
        return generate(tail)
    from services.computation.mathematics import compute_math
    if head in {"physics", "chemistry", "convert"}:
        from services.computation.science import compute_science
        return compute_science(head, tail)
    return compute_math(query)


def encode(result: EngineResult) -> str:
    return json.dumps(asdict(result), ensure_ascii=True, allow_nan=False)
