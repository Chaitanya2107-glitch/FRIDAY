"""Small, closed action vocabulary; models can propose, never execute."""

import hashlib
import json
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Step(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    action: Literal["navigate", "launch", "click", "fill", "press", "download", "done", "blocked"]
    reason: str = Field(min_length=1, max_length=300)
    target: int = Field(default=0, ge=0, le=100)
    value: str = Field(default="", max_length=1000)


@dataclass
class Observation:
    location: str
    title: str
    text: str = field(repr=False)
    controls: list[dict] = field(default_factory=list, repr=False)

    def payload(self):
        return {"location": self.location, "title": self.title,
                "text": self.text[:12000], "controls": self.controls}

    def fingerprint(self):
        return hashlib.sha256(json.dumps(self.payload(), sort_keys=True).encode()).hexdigest()


def parse_step(content: str, observation: Observation, kind: str) -> Step:
    if len(content) > 6000:
        raise ValueError("Oversized proposal")
    step = Step.model_validate_json(content)
    if not step.reason.strip() or any(ord(c) < 32 for c in step.reason):
        raise ValueError("Unreadable reason")
    if step.action in {"click", "fill", "press", "download"}:
        control = next((c for c in observation.controls if c["id"] == step.target), None)
        if not control or control.get("protected"):
            raise ValueError("Target is unavailable or protected")
        if step.action == "fill" and control["kind"] not in {"input", "textarea", "Edit", "Document"}:
            raise ValueError("Target is not an editor")
        if step.action == "press" and step.value not in {"Enter", "Tab", "Escape", "ArrowDown", "ArrowUp"}:
            raise ValueError("Unsupported key")
    elif step.target:
        raise ValueError("Unexpected target")
    if step.action == "navigate" and (kind != "browser" or not step.value):
        raise ValueError("Navigation requires a browser URL")
    if step.action == "launch" and (kind != "desktop" or step.value != "notepad"):
        raise ValueError("Only launching Notepad is supported")
    if step.action == "download" and kind != "browser":
        raise ValueError("Downloads require a browser")
    if step.action == "fill" and not step.value:
        raise ValueError("Missing literal text")
    if step.action == "done" and (not step.value or step.value not in observation.text):
        raise ValueError("Completion requires a quote from the latest observation")
    return step


def describe(step: Step, observation: Observation) -> str:
    label = next((c["name"] for c in observation.controls if c["id"] == step.target), "")
    if step.action == "navigate":
        return f"Open {step.value}"
    if step.action == "launch":
        return "Open Notepad"
    if step.action == "fill":
        return f"Enter {json.dumps(step.value, ensure_ascii=False)} into {label!r}"
    if step.action == "press":
        return f"Press {step.value} on {label!r}"
    if step.action == "download":
        return f"Download from {label!r}; save without opening the file"
    return f"Click {label!r}" if step.action == "click" else step.reason
