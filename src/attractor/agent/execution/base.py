"""Abstract execution environment interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class ShellResult:
    stdout: str
    stderr: str
    exit_code: int
    duration_ms: int
    timed_out: bool = False


class ExecutionEnvironment(ABC):
    @abstractmethod
    def working_directory(self) -> str: ...

    @abstractmethod
    async def read_file(self, path: str, offset: int = 0, limit: int = 2000) -> str: ...

    @abstractmethod
    async def write_file(self, path: str, content: str) -> int: ...

    @abstractmethod
    async def edit_file(
        self, path: str, old_string: str, new_string: str, replace_all: bool = False
    ) -> int: ...

    @abstractmethod
    async def shell(self, command: str, timeout_ms: int = 10000) -> ShellResult: ...

    @abstractmethod
    async def glob(self, pattern: str, path: str | None = None) -> list[str]: ...

    @abstractmethod
    async def grep(
        self,
        pattern: str,
        path: str | None = None,
        glob_filter: str | None = None,
        case_insensitive: bool = False,
        max_results: int = 100,
    ) -> str: ...
