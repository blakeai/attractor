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
            print("  Or type your feedback/instructions:")
            response = input("> ").strip()
            if not response:
                response = question.options[0].key if question.options else ""
            # Check if it's a shortcut key
            for opt in question.options:
                if response.upper() == opt.key.upper():
                    print(f"  -> {opt.label}")
                    return Answer(value=opt.key, selected_option=opt)
            # Freeform response — default to first edge but carry the feedback
            first_opt = question.options[0] if question.options else None
            print(f"  -> {first_opt.label if first_opt else 'continuing'} (with feedback)")
            return Answer(
                value=first_opt.key if first_opt else response,
                selected_option=first_opt,
                text=response,
            )

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
