"""Pipeline execution context — thread-safe key-value store."""

from __future__ import annotations

import copy
import threading
from typing import Any


class Context:
    def __init__(self, values: dict[str, Any] | None = None):
        self._values: dict[str, Any] = dict(values) if values else {}
        self._lock = threading.RLock()
        self._logs: list[str] = []

    def set(self, key: str, value: Any) -> None:
        with self._lock:
            self._values[key] = value

    def get(self, key: str, default: Any = None) -> Any:
        with self._lock:
            return self._values.get(key, default)

    def get_string(self, key: str, default: str = "") -> str:
        value = self.get(key)
        if value is None:
            return default
        return str(value)

    def append_log(self, entry: str) -> None:
        with self._lock:
            self._logs.append(entry)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._values)

    def clone(self) -> Context:
        with self._lock:
            ctx = Context(copy.copy(self._values))
            ctx._logs = list(self._logs)
            return ctx

    def apply_updates(self, updates: dict[str, Any]) -> None:
        with self._lock:
            self._values.update(updates)

    @property
    def logs(self) -> list[str]:
        with self._lock:
            return list(self._logs)
