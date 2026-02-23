"""Simple condition expression evaluator for edge conditions.

Supports expressions like:
  outcome=success
  outcome!=fail
  outcome=success AND last_stage=validate
"""

from __future__ import annotations

from typing import Any

from attractor.pipeline.context import Context
from attractor.pipeline.outcome import Outcome


def evaluate_condition(
    expr: str,
    outcome: Outcome,
    context: Context,
) -> bool:
    """Evaluate a condition expression against the current outcome and context."""
    expr = expr.strip()
    if not expr:
        return True

    # Handle AND/OR
    if " AND " in expr:
        parts = expr.split(" AND ")
        return all(evaluate_condition(p.strip(), outcome, context) for p in parts)
    if " OR " in expr:
        parts = expr.split(" OR ")
        return any(evaluate_condition(p.strip(), outcome, context) for p in parts)

    # Handle NOT
    if expr.startswith("NOT "):
        return not evaluate_condition(expr[4:].strip(), outcome, context)

    # Handle comparison operators
    for op in ("!=", "="):
        if op in expr:
            key, value = expr.split(op, 1)
            key = key.strip()
            value = value.strip()

            actual = _resolve_key(key, outcome, context)
            if op == "=":
                return str(actual).lower() == value.lower()
            else:
                return str(actual).lower() != value.lower()

    # Bare truthy check
    actual = _resolve_key(expr, outcome, context)
    return bool(actual)


def _resolve_key(key: str, outcome: Outcome, context: Context) -> Any:
    """Resolve a key to its value from outcome or context."""
    if key == "outcome":
        return outcome.status.value
    if key == "status":
        return outcome.status.value
    if key == "preferred_label":
        return outcome.preferred_label
    return context.get(key, "")
