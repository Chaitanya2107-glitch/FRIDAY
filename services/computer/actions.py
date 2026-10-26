"""Validate model proposals before they can become desktop input."""

import json
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, TypeAdapter

from services.automation.keyboard import parse_keys


class Proposal(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    reason: str = Field(min_length=1, max_length=300)


class Click(Proposal):
    action: Literal["click", "double_click"]
    x: StrictInt = Field(ge=0)
    y: StrictInt = Field(ge=0)


class Scroll(Proposal):
    action: Literal["scroll"]
    x: StrictInt = Field(ge=0)
    y: StrictInt = Field(ge=0)
    amount: StrictInt = Field(ge=-5, le=5)  # wheel notches; positive is up


class TypeText(Proposal):
    action: Literal["type"]
    text: str = Field(min_length=1, max_length=1000)


class Keys(Proposal):
    action: Literal["keys"]
    keys: str = Field(min_length=1, max_length=50)


class Finished(Proposal):
    action: Literal["done", "blocked"]


Action = Annotated[Click | Scroll | TypeText | Keys | Finished, Field(discriminator="action")]
ADAPTER = TypeAdapter(Action)


def parse_action(content: str, size: tuple[int, int]) -> Proposal:
    if len(content) > 6000:
        raise ValueError("Oversized computer action")
    text = content.strip()
    if text.startswith("```json\n") and text.endswith("```"):
        text = text[8:-3].strip()
    action = ADAPTER.validate_python(json.loads(text))
    validate_action(action, size)
    return action


def validate_action(action: Proposal, size: tuple[int, int]) -> None:
    # Revalidate at execution too: no extra arguments or new tool kinds sneak in.
    ADAPTER.validate_python(action.model_dump())
    if not action.reason.strip() or any(ord(c) < 32 for c in action.reason):
        raise ValueError("Reason must be a readable single line")
    if isinstance(action, (Click, Scroll)):
        if not (0 <= action.x < size[0] and 0 <= action.y < size[1]):
            raise ValueError("Coordinates outside captured screen")
    if isinstance(action, Scroll) and action.amount == 0:
        raise ValueError("Scroll must move")
    if isinstance(action, Keys) and parse_keys(action.keys) is None:
        raise ValueError("Unknown keys")


def describe(action: Proposal) -> str:
    if isinstance(action, Click):
        return f"{'Double-click' if action.action == 'double_click' else 'Click'} at ({action.x}, {action.y})"
    if isinstance(action, Scroll):
        return f"Scroll {'up' if action.amount > 0 else 'down'} {abs(action.amount)} notches at ({action.x}, {action.y})"
    if isinstance(action, TypeText):
        return f"Type exactly {json.dumps(action.text)}"
    if isinstance(action, Keys):
        return f"Press {action.keys}"
    return action.reason
