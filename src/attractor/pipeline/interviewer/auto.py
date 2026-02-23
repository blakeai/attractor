"""Auto-approve interviewer — always selects YES or first option."""

from __future__ import annotations

from attractor.pipeline.interviewer.base import (
    Answer,
    AnswerValue,
    Interviewer,
    Question,
    QuestionType,
)


class AutoApproveInterviewer(Interviewer):
    def ask(self, question: Question) -> Answer:
        if question.type in (QuestionType.YES_NO, QuestionType.CONFIRMATION):
            return Answer(value=AnswerValue.YES)
        if question.type == QuestionType.MULTIPLE_CHOICE and question.options:
            first = question.options[0]
            return Answer(value=first.key, selected_option=first)
        return Answer(value="auto-approved", text="auto-approved")
