"""One request per isolated interpreter; no app config, logging or model imports."""

import json
from pathlib import Path
import sys

# -I ignores user-site/PYTHONPATH; this fixed source root supplies only our code.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from services.computation.engine import EngineResult, MAX_INPUT, encode, evaluate


def main() -> None:
    try:
        data = json.loads(sys.stdin.read(MAX_INPUT * 8 + 100))
        command = data.get("command") if isinstance(data, dict) else None
        if not isinstance(command, str) or not command.strip() or len(command) > MAX_INPUT:
            raise ValueError("Invalid or oversized command.")
        result = evaluate(command)
    except ImportError:
        result = EngineResult(False, "engine", "SymPy is missing. Install the project's requirements first.")
    except (ValueError, SyntaxError, TypeError, ArithmeticError, NotImplementedError, RecursionError) as error:
        result = EngineResult(False, "engine", str(error)[:500] or "This calculation is undefined or unsupported.")
    except Exception:
        result = EngineResult(False, "engine", "This calculation could not be completed.")
    output = encode(result)
    if len(output) > 32000:
        output = encode(EngineResult(False, "engine", "The result is too large. Use a smaller problem."))
    sys.stdout.write(output)


if __name__ == "__main__":
    main()
