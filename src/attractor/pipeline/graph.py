"""Graph data model — nodes, edges, and the parsed graph structure."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# Shape-to-handler-type mapping
SHAPE_TO_TYPE: dict[str, str] = {
    "Mdiamond": "start",
    "Msquare": "exit",
    "box": "codergen",
    "hexagon": "wait.human",
    "diamond": "conditional",
    "component": "parallel",
    "tripleoctagon": "parallel.fan_in",
    "parallelogram": "tool",
    "house": "stack.manager_loop",
}


@dataclass
class Node:
    id: str
    attrs: dict[str, Any] = field(default_factory=dict)

    @property
    def label(self) -> str:
        return str(self.attrs.get("label", self.id))

    @property
    def shape(self) -> str:
        return str(self.attrs.get("shape", "box"))

    @property
    def type(self) -> str:
        return str(self.attrs.get("type", ""))

    @property
    def prompt(self) -> str:
        return str(self.attrs.get("prompt", ""))

    @property
    def max_retries(self) -> int:
        return int(self.attrs.get("max_retries", 0))

    @property
    def goal_gate(self) -> bool:
        return self.attrs.get("goal_gate", False) is True or self.attrs.get("goal_gate") == "true"

    @property
    def retry_target(self) -> str:
        return str(self.attrs.get("retry_target", ""))

    @property
    def fallback_retry_target(self) -> str:
        return str(self.attrs.get("fallback_retry_target", ""))

    @property
    def auto_status(self) -> bool:
        v = self.attrs.get("auto_status", False)
        return v is True or v == "true"

    @property
    def allow_partial(self) -> bool:
        v = self.attrs.get("allow_partial", False)
        return v is True or v == "true"

    @property
    def handler_type(self) -> str:
        """Resolve the handler type for this node."""
        if self.type:
            return self.type
        return SHAPE_TO_TYPE.get(self.shape, "codergen")

    def is_start(self) -> bool:
        return self.shape == "Mdiamond" or (self.id.lower() == "start" and not self.shape)

    def is_terminal(self) -> bool:
        return self.shape == "Msquare" or self.id.lower() in ("exit", "end")


@dataclass
class Edge:
    from_node: str
    to_node: str
    attrs: dict[str, Any] = field(default_factory=dict)

    @property
    def label(self) -> str:
        return str(self.attrs.get("label", ""))

    @property
    def condition(self) -> str:
        return str(self.attrs.get("condition", ""))

    @property
    def weight(self) -> int:
        return int(self.attrs.get("weight", 0))

    @property
    def loop_restart(self) -> bool:
        v = self.attrs.get("loop_restart", False)
        return v is True or v == "true"


@dataclass
class Graph:
    name: str = ""
    attrs: dict[str, Any] = field(default_factory=dict)
    nodes: dict[str, Node] = field(default_factory=dict)
    edges: list[Edge] = field(default_factory=list)
    node_defaults: dict[str, Any] = field(default_factory=dict)
    edge_defaults: dict[str, Any] = field(default_factory=dict)

    @property
    def goal(self) -> str:
        return str(self.attrs.get("goal", ""))

    def outgoing_edges(self, node_id: str) -> list[Edge]:
        return [e for e in self.edges if e.from_node == node_id]

    def incoming_edges(self, node_id: str) -> list[Edge]:
        return [e for e in self.edges if e.to_node == node_id]

    def find_start_node(self) -> Node | None:
        for node in self.nodes.values():
            if node.shape == "Mdiamond":
                return node
        for node in self.nodes.values():
            if node.id.lower() in ("start",):
                return node
        return None

    def find_exit_node(self) -> Node | None:
        for node in self.nodes.values():
            if node.shape == "Msquare":
                return node
        for node in self.nodes.values():
            if node.id.lower() in ("exit", "end"):
                return node
        return None
