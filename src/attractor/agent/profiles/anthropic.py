"""Anthropic (Claude Code-aligned) provider profile."""

from __future__ import annotations

from typing import Any

from attractor.agent.execution.base import ExecutionEnvironment
from attractor.agent.profiles.base import ProviderProfile
from attractor.agent.tools.core import make_all_tools
from attractor.llm.types import Tool


class AnthropicProfile(ProviderProfile):
    def __init__(
        self,
        model: str = "claude-sonnet-4-6",
        reasoning_effort: str | None = None,
    ):
        self._model = model
        self._reasoning_effort = reasoning_effort

    @property
    def id(self) -> str:
        return "anthropic"

    @property
    def model(self) -> str:
        return self._model

    @property
    def supports_reasoning(self) -> bool:
        return True

    @property
    def supports_streaming(self) -> bool:
        return True

    @property
    def supports_parallel_tool_calls(self) -> bool:
        return True

    @property
    def context_window_size(self) -> int:
        return 200_000

    def build_system_prompt(
        self, environment: ExecutionEnvironment, project_docs: str = ""
    ) -> str:
        cwd = environment.working_directory()
        parts = [
            "You are a coding agent. You help users with software engineering tasks.",
            f"Working directory: {cwd}",
            "You have access to tools for reading files, writing files, editing files, "
            "running shell commands, searching file contents (grep), and finding files (glob).",
            "Always read files before editing them. Prefer editing existing files over creating new ones.",
            "Use the shell tool for running tests, installing packages, and other terminal operations.",
        ]
        if project_docs:
            parts.append(f"\nProject documentation:\n{project_docs}")
        return "\n\n".join(parts)

    def tools(self, env: ExecutionEnvironment) -> list[Tool]:
        return make_all_tools(env)

    def provider_options(self) -> dict[str, Any] | None:
        return None
