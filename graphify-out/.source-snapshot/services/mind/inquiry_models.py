"""Validated decisions for the local inquiry layer."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class AnswerBranch(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    answer: str = Field(min_length=3, max_length=120)
    next_step: str = Field(min_length=10, max_length=180)


class Purpose(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    gap: str = Field(min_length=1, max_length=100)
    decision: str = Field(min_length=10, max_length=200)
    if_answer_a: AnswerBranch
    if_answer_b: AnswerBranch
    usefulness: Literal["changes_decision", "background_interest"]


class Decision(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    ask: bool
    question: str = Field(max_length=500)
    topic: str = Field(max_length=80)
    basis: list[str] = Field(max_length=6)
    reason: str = Field(min_length=3, max_length=350)
    purpose: Purpose | None
