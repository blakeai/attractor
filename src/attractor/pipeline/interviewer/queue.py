"""Queue interviewer — reads from a pre-filled answer queue (for testing)."""

from __future__ import annotations

from collections import deque

from attractor.pipeline.interviewer.base import Answer, AnswerValue, Interviewer, Question


class QueueInterviewer(Interviewer):
    def __init__(self, answers: list[Answer] | None = None):
        self._answers: deque[Answer] = deque(answers or [])

    def enqueue(self, answer: Answer) -> None:
        self._answers.append(answer)

    def ask(self, question: Question) -> Answer:
        if self._answers:
            return self._answers.popleft()
        return Answer(value=AnswerValue.SKIPPED)
