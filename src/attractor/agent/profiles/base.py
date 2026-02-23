"""Abstract provider profile interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from attractor.agent.execution.base import ExecutionEnvironment
from attractor.llm.types import Tool


class ProviderProfile(ABC):
    @property
    @abstractmethod
    def id(self) -> str: ...

    @property
    @abstractmethod
    def model(self) -> str: ...

    @property
    @abstractmethod
    def supports_reasoning(self) -> bool: ...

    @property
    @abstractmethod
    def supports_streaming(self) -> bool: ...

    @property
    @abstractmethod
    def supports_parallel_tool_calls(self) -> bool: ...

    @property
    @abstractmethod
    def context_window_size(self) -> int: ...

    @abstractmethod
    def build_system_prompt(
        self, environment: ExecutionEnvironment, project_docs: str = ""
    ) -> str: ...

    @abstractmethod
    def tools(self, env: ExecutionEnvironment) -> list[Tool]: ...

    @abstractmethod
    def provider_options(self) -> dict[str, Any] | None: ...
