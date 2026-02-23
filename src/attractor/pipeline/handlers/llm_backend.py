"""LLM-backed codergen backend — sends prompts to an LLM client."""

from __future__ import annotations

from attractor.llm.client import Client
from attractor.llm.types import Message, Request
from attractor.pipeline.context import Context
from attractor.pipeline.graph import Node


class LLMBackend:
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
