"""Interviewer interface and data models for human-in-the-loop interaction."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class QuestionType(StrEnum):
    YES_NO = "yes_no"
    MULTIPLE_CHOICE = "multiple_choice"
    FREEFORM = "freeform"
    CONFIRMATION = "confirmation"


class AnswerValue(StrEnum):
    YES = "yes"
    NO = "no"
    SKIPPED = "skipped"
    TIMEOUT = "timeout"


@dataclass
class Option:
    key: str
    label: str


@dataclass
class Question:
    text: str
    type: QuestionType = QuestionType.MULTIPLE_CHOICE
    options: list[Option] = field(default_factory=list)
    default: Answer | None = None
    timeout_seconds: float | None = None
    stage: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Answer:
    value: str = ""
    selected_option: Option | None = None
    text: str = ""


class Interviewer(ABC):
    @abstractmethod
    def ask(self, question: Question) -> Answer: ...

    def ask_multiple(self, questions: list[Question]) -> list[Answer]:
        return [self.ask(q) for q in questions]

    def inform(self, message: str, stage: str = "") -> None:  # noqa: B027
        pass
