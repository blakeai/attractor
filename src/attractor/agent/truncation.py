"""Tool output truncation — keeps LLM context manageable."""

from __future__ import annotations

# Default character limits per tool (spec Section 5)
DEFAULT_LIMITS: dict[str, int] = {
    "read_file": 100_000,
    "shell": 50_000,
    "grep": 30_000,
    "glob": 30_000,
    "edit_file": 10_000,
    "write_file": 10_000,
}

DEFAULT_CHAR_LIMIT = 50_000


def truncate_tool_output(
    output: str,
    tool_name: str,
    limits: dict[str, int] | None = None,
) -> str:
    """Truncate tool output to fit within character limits.

    Uses a head/tail split strategy: keep the first portion and last portion
    of the output with a truncation marker in the middle.
    """
    all_limits = {**DEFAULT_LIMITS, **(limits or {})}
    limit = all_limits.get(tool_name, DEFAULT_CHAR_LIMIT)

    if len(output) <= limit:
        return output

    # Head/tail split: 80% head, 20% tail
    head_size = int(limit * 0.8)
    tail_size = limit - head_size
    truncated_chars = len(output) - limit

    head = output[:head_size]
    tail = output[-tail_size:]
    marker = f"\n\n... [{truncated_chars} characters truncated] ...\n\n"

    return head + marker + tail
