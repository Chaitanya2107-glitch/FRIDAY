"""Local, bounded computation. Importing this package never loads a model."""

from services.computation.engine import EngineResult, calculate

__all__ = ["EngineResult", "calculate"]
