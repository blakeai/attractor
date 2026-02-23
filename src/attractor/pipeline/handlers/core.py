"""Core node handlers — start, exit, conditional, codergen, wait.human."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Protocol

from attractor.pipeline.context import Context
from attractor.pipeline.graph import Graph, Node
from attractor.pipeline.handlers.base import Handler
from attractor.pipeline.interviewer.base import (
    AnswerValue,
    Interviewer,
    Option,
    Question,
    QuestionType,
)
from attractor.pipeline.outcome import Outcome, StageStatus


class StartHandler(Handler):
    async def execute(self, node: Node, context: Context, graph: Graph, logs_root: str) -> Outcome:
        return Outcome(status=StageStatus.SUCCESS)


class ExitHandler(Handler):
    async def execute(self, node: Node, context: Context, graph: Graph, logs_root: str) -> Outcome:
        return Outcome(status=StageStatus.SUCCESS)


class ConditionalHandler(Handler):
    async def execute(self, node: Node, context: Context, graph: Graph, logs_root: str) -> Outcome:
        return Outcome(
            status=StageStatus.SUCCESS,
            notes=f"Conditional node evaluated: {node.id}",
        )


class CodergenBackend(Protocol):
    async def run(self, node: Node, prompt: str, context: Context) -> str | Outcome: ...


class CodergenHandler(Handler):
    def __init__(self, backend: CodergenBackend | None = None):
        self._backend = backend

    async def execute(self, node: Node, context: Context, graph: Graph, logs_root: str) -> Outcome:
        # 1. Build prompt
        prompt = node.prompt or node.label
        prompt = _expand_variables(prompt, graph, context)

        # 2. Write prompt to logs
        stage_dir = Path(logs_root) / node.id
        stage_dir.mkdir(parents=True, exist_ok=True)
        (stage_dir / "prompt.md").write_text(prompt, encoding="utf-8")

        # 3. Call backend
        if self._backend is not None:
            try:
                result = await self._backend.run(node, prompt, context)
                if isinstance(result, Outcome):
                    _write_status(stage_dir, result)
                    return result
                response_text = str(result)
            except Exception as e:
                outcome = Outcome(status=StageStatus.FAIL, failure_reason=str(e))
                _write_status(stage_dir, outcome)
                return outcome
        else:
            response_text = f"[Simulated] Response for stage: {node.id}"

        # 4. Write response to logs
        (stage_dir / "response.md").write_text(response_text, encoding="utf-8")

        # 5. Return outcome
        outcome = Outcome(
            status=StageStatus.SUCCESS,
            notes=f"Stage completed: {node.id}",
            context_updates={
                "last_stage": node.id,
                "last_response": response_text[:200],
            },
        )
        _write_status(stage_dir, outcome)
        return outcome


class WaitForHumanHandler(Handler):
    def __init__(self, interviewer: Interviewer):
        self._interviewer = interviewer

    async def execute(self, node: Node, context: Context, graph: Graph, logs_root: str) -> Outcome:
        edges = graph.outgoing_edges(node.id)
        if not edges:
            return Outcome(
                status=StageStatus.FAIL,
                failure_reason="No outgoing edges for human gate",
            )

        # Show the previous stage's full response so the human has context
        last_stage = context.get("last_stage")
        if last_stage and logs_root:
            response_path = Path(logs_root) / str(last_stage) / "response.md"
            if response_path.exists():
                response_text = response_path.read_text(encoding="utf-8")
                self._interviewer.inform(
                    f"\n{'=' * 60}\n{response_text}\n{'=' * 60}",
                    stage=str(last_stage),
                )

        choices = []
        for edge in edges:
            label = edge.label or edge.to_node
            key = _parse_accelerator_key(label)
            choices.append((key, label, edge.to_node))

        options = [Option(key=c[0], label=c[1]) for c in choices]
        question = Question(
            text=node.label or "Select an option:",
            type=QuestionType.MULTIPLE_CHOICE,
            options=options,
            stage=node.id,
        )

        answer = self._interviewer.ask(question)

        if answer.value == AnswerValue.TIMEOUT:
            default = node.attrs.get("human.default_choice")
            if default:
                return Outcome(
                    status=StageStatus.SUCCESS,
                    suggested_next_ids=[str(default)],
                    context_updates={"human.gate.selected": str(default)},
                )
            return Outcome(
                status=StageStatus.RETRY,
                failure_reason="Human gate timeout, no default",
            )

        if answer.value == AnswerValue.SKIPPED:
            return Outcome(
                status=StageStatus.FAIL,
                failure_reason="Human skipped interaction",
            )

        # Find matching choice
        selected = choices[0]  # default to first
        for c in choices:
            if answer.value.upper() == c[0].upper():
                selected = c
                break
            if answer.selected_option and answer.selected_option.key.upper() == c[0].upper():
                selected = c
                break

        context_updates: dict[str, str] = {
            "human.gate.selected": selected[0],
            "human.gate.label": selected[1],
        }

        # Store freeform feedback so the next stage can use it
        if answer.text and answer.text.upper() != selected[0].upper():
            context_updates["human.feedback"] = answer.text

        return Outcome(
            status=StageStatus.SUCCESS,
            suggested_next_ids=[selected[2]],
            context_updates=context_updates,
        )


def _parse_accelerator_key(label: str) -> str:
    """Extract accelerator key from label patterns like [Y] Yes, Y) Yes, Y - Yes."""
    # Pattern: [K] Label
    m = re.match(r"\[(\w)\]\s+", label)
    if m:
        return m.group(1).upper()
    # Pattern: K) Label
    m = re.match(r"(\w)\)\s+", label)
    if m:
        return m.group(1).upper()
    # Pattern: K - Label
    m = re.match(r"(\w)\s*-\s+", label)
    if m:
        return m.group(1).upper()
    # Default: first character
    return label[0].upper() if label else "?"


def _expand_variables(text: str, graph: Graph, context: Context) -> str:
    """Expand $<key> variables from graph attrs and context."""
    for key, value in graph.attrs.items():
        text = text.replace(f"${key}", str(value))
    for key, value in context.snapshot().items():
        text = text.replace(f"${key}", str(value))
    return text


def _write_status(stage_dir: Path, outcome: Outcome) -> None:
    """Write status.json to the stage directory."""
    import json

    data = {
        "status": outcome.status.value,
        "notes": outcome.notes,
        "failure_reason": outcome.failure_reason,
    }
    (stage_dir / "status.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
