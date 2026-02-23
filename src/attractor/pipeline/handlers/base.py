"""Handler interface and registry."""

from __future__ import annotations

from abc import ABC, abstractmethod

from attractor.pipeline.context import Context
from attractor.pipeline.graph import SHAPE_TO_TYPE, Graph, Node
from attractor.pipeline.outcome import Outcome


class Handler(ABC):
    @abstractmethod
    async def execute(
        self,
        node: Node,
        context: Context,
        graph: Graph,
        logs_root: str,
    ) -> Outcome: ...


class HandlerRegistry:
    def __init__(self, default_handler: Handler | None = None):
        self._handlers: dict[str, Handler] = {}
        self._default_handler = default_handler

    def register(self, type_string: str, handler: Handler) -> None:
        self._handlers[type_string] = handler

    def resolve(self, node: Node) -> Handler:
        # 1. Explicit type attribute
        if node.type and node.type in self._handlers:
            return self._handlers[node.type]

        # 2. Shape-based resolution
        handler_type = SHAPE_TO_TYPE.get(node.shape, "")
        if handler_type and handler_type in self._handlers:
            return self._handlers[handler_type]

        # 3. Default
        if self._default_handler:
            return self._default_handler

        raise ValueError(f"No handler found for node '{node.id}' (type='{node.type}', shape='{node.shape}')")
