"""Local filesystem execution environment."""

from __future__ import annotations

import asyncio
import fnmatch
import os
import re
import time
from pathlib import Path

from attractor.agent.execution.base import ExecutionEnvironment, ShellResult


class LocalExecutionEnvironment(ExecutionEnvironment):
    def __init__(self, working_dir: str | None = None):
        self._working_dir = working_dir or os.getcwd()

    def working_directory(self) -> str:
        return self._working_dir

    def _resolve(self, path: str) -> Path:
        p = Path(path)
        if not p.is_absolute():
            p = Path(self._working_dir) / p
        return p

    async def read_file(self, path: str, offset: int = 0, limit: int = 2000) -> str:
        resolved = self._resolve(path)
        if not resolved.exists():
            raise FileNotFoundError(f"File not found: {path}")
        if not resolved.is_file():
            raise IsADirectoryError(f"Path is a directory: {path}")

        text = resolved.read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines()

        start = max(0, offset)
        end = start + limit
        selected = lines[start:end]

        numbered = []
        for i, line in enumerate(selected, start=start + 1):
            numbered.append(f"{i:>4} | {line}")
        return "\n".join(numbered)

    async def write_file(self, path: str, content: str) -> int:
        resolved = self._resolve(path)
        resolved.parent.mkdir(parents=True, exist_ok=True)
        resolved.write_text(content, encoding="utf-8")
        return len(content.encode("utf-8"))

    async def edit_file(
        self, path: str, old_string: str, new_string: str, replace_all: bool = False
    ) -> int:
        resolved = self._resolve(path)
        if not resolved.exists():
            raise FileNotFoundError(f"File not found: {path}")

        text = resolved.read_text(encoding="utf-8")
        count = text.count(old_string)

        if count == 0:
            raise ValueError(f"String not found in {path}")
        if count > 1 and not replace_all:
            raise ValueError(
                f"String found {count} times in {path}. "
                "Use replace_all=true or provide more context to make the match unique."
            )

        if replace_all:
            new_text = text.replace(old_string, new_string)
        else:
            new_text = text.replace(old_string, new_string, 1)

        resolved.write_text(new_text, encoding="utf-8")
        return count if replace_all else 1

    async def shell(self, command: str, timeout_ms: int = 10000) -> ShellResult:
        start = time.monotonic()
        timeout_sec = timeout_ms / 1000.0

        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self._working_dir,
            )
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(), timeout=timeout_sec
            )
            elapsed = int((time.monotonic() - start) * 1000)
            return ShellResult(
                stdout=stdout_bytes.decode("utf-8", errors="replace"),
                stderr=stderr_bytes.decode("utf-8", errors="replace"),
                exit_code=proc.returncode or 0,
                duration_ms=elapsed,
            )
        except TimeoutError:
            proc.kill()
            await proc.wait()
            elapsed = int((time.monotonic() - start) * 1000)
            return ShellResult(
                stdout="",
                stderr=f"Command timed out after {timeout_ms}ms",
                exit_code=-1,
                duration_ms=elapsed,
                timed_out=True,
            )

    async def glob(self, pattern: str, path: str | None = None) -> list[str]:
        base = Path(path) if path else Path(self._working_dir)
        matches = sorted(base.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
        return [str(m) for m in matches if m.is_file()]

    async def grep(
        self,
        pattern: str,
        path: str | None = None,
        glob_filter: str | None = None,
        case_insensitive: bool = False,
        max_results: int = 100,
    ) -> str:
        base = Path(path) if path else Path(self._working_dir)
        flags = re.IGNORECASE if case_insensitive else 0
        regex = re.compile(pattern, flags)
        results: list[str] = []

        def _search_file(fp: Path) -> None:
            try:
                text = fp.read_text(encoding="utf-8", errors="replace")
                for i, line in enumerate(text.splitlines(), 1):
                    if regex.search(line):
                        results.append(f"{fp}:{i}: {line}")
                        if len(results) >= max_results:
                            return
            except (PermissionError, OSError):
                pass

        if base.is_file():
            _search_file(base)
        else:
            for fp in base.rglob("*"):
                if not fp.is_file():
                    continue
                if glob_filter and not fnmatch.fnmatch(fp.name, glob_filter):
                    continue
                _search_file(fp)
                if len(results) >= max_results:
                    break

        return "\n".join(results)
