"""LLM-backed codergen backends — simple (LLMBackend) and agentic (AgentBackend)."""

from __future__ import annotations

from attractor.agent.execution.local import LocalExecutionEnvironment
from attractor.agent.profiles.anthropic import AnthropicProfile
from attractor.agent.session import Session, SessionConfig
from attractor.llm.client import Client
from attractor.llm.types import Message, Request
from attractor.pipeline.context import Context
from attractor.pipeline.graph import Node


class LLMBackend:
    """Single LLM call per node — no tools, no agentic loop."""

    def __init__(self, client: Client, model: str = "claude-sonnet-4-20250514"):
        self._client = client
        self._model = model

    async def run(self, node: Node, prompt: str, context: Context) -> str:
        request = Request(
            model=self._model,
            messages=[Message.user(prompt)],
        )
        response = await self._client.complete(request)
        return response.text


class AgentBackend:
    """Full agentic loop per node — tools, shell, file ops, multi-turn."""

    def __init__(
        self,
        client: Client,
        model: str = "claude-sonnet-4-20250514",
        repo_path: str = ".",
        max_tool_rounds: int = 50,
        command_timeout_ms: int = 30000,
    ):
        self._client = client
        self._model = model
        self._repo_path = repo_path
        self._max_tool_rounds = max_tool_rounds
        self._command_timeout_ms = command_timeout_ms

    async def run(self, node: Node, prompt: str, context: Context) -> str:
        env = LocalExecutionEnvironment(working_dir=self._repo_path)
        profile = AnthropicProfile(model=self._model)
        config = SessionConfig(
            max_tool_rounds_per_input=self._max_tool_rounds,
            default_command_timeout_ms=self._command_timeout_ms,
        )
        session = Session(
            profile=profile,
            execution_env=env,
            llm_client=self._client,
            config=config,
        )
        return await session.submit(prompt)
