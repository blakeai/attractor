"""Pipeline execution outcome — result of executing a node handler."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class StageStatus(StrEnum):
    SUCCESS = "success"
    PARTIAL_SUCCESS = "partial_success"
    RETRY = "retry"
    FAIL = "fail"
    SKIPPED = "skipped"


@dataclass
class Outcome:
    status: StageStatus = StageStatus.SUCCESS
    preferred_label: str = ""
    suggested_next_ids: list[str] = field(default_factory=list)
    context_updates: dict[str, Any] = field(default_factory=dict)
    notes: str = ""
    failure_reason: str = ""
