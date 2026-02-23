"""Provider adapter abstract interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

from attractor.llm.types import Request, Response, StreamEvent


class ProviderAdapter(ABC):
    @property
    @abstractmethod
    def name(self) -> str: ...

    @abstractmethod
    async def complete(self, request: Request) -> Response: ...

    @abstractmethod
    async def stream(self, request: Request) -> AsyncIterator[StreamEvent]: ...

    async def close(self) -> None:  # noqa: B027
        pass

    async def initialize(self) -> None:  # noqa: B027
        pass

    def supports_tool_choice(self, mode: str) -> bool:
        return True
