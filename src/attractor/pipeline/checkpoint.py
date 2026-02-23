"""Pipeline checkpoint — serializable execution state for crash recovery."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


@dataclass
class Checkpoint:
    timestamp: str = ""
    current_node: str = ""
    completed_nodes: list[str] = field(default_factory=list)
    node_retries: dict[str, int] = field(default_factory=dict)
    context_values: dict[str, Any] = field(default_factory=dict)
    logs: list[str] = field(default_factory=list)

    def save(self, path: str) -> None:
        self.timestamp = datetime.now(UTC).isoformat()
        data = {
            "timestamp": self.timestamp,
            "current_node": self.current_node,
            "completed_nodes": self.completed_nodes,
            "node_retries": self.node_retries,
            "context": self.context_values,
            "logs": self.logs,
        }
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")

    @classmethod
    def load(cls, path: str) -> Checkpoint:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(
            timestamp=data.get("timestamp", ""),
            current_node=data.get("current_node", ""),
            completed_nodes=data.get("completed_nodes", []),
            node_retries=data.get("node_retries", {}),
            context_values=data.get("context", {}),
            logs=data.get("logs", []),
        )
