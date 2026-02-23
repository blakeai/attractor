"""Console interviewer — reads from stdin."""

from __future__ import annotations

from attractor.pipeline.interviewer.base import (
    Answer,
    AnswerValue,
    Interviewer,
    Question,
    QuestionType,
)


class ConsoleInterviewer(Interviewer):
    def ask(self, question: Question) -> Answer:
        print(f"\n[?] {question.text}")

        if question.type == QuestionType.MULTIPLE_CHOICE:
            for opt in question.options:
                print(f"  [{opt.key}] {opt.label}")
            response = input("Select: ").strip()
            for opt in question.options:
                if response.upper() == opt.key.upper():
                    return Answer(value=opt.key, selected_option=opt)
            if question.options:
                return Answer(
                    value=question.options[0].key, selected_option=question.options[0]
                )
            return Answer(value=response, text=response)

        if question.type in (QuestionType.YES_NO, QuestionType.CONFIRMATION):
            response = input("[Y/N]: ").strip().lower()
            return Answer(value=AnswerValue.YES if response in ("y", "yes") else AnswerValue.NO)

        if question.type == QuestionType.FREEFORM:
            response = input("> ").strip()
            return Answer(text=response, value=response)

        return Answer(value=AnswerValue.SKIPPED)

    def inform(self, message: str, stage: str = "") -> None:
        prefix = f"[{stage}] " if stage else ""
        print(f"{prefix}{message}")
