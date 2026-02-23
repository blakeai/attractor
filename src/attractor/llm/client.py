"""Core LLM Client — provider routing and middleware."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Callable
from typing import Any

from attractor.llm.adapter import ProviderAdapter
from attractor.llm.errors import ConfigurationError
from attractor.llm.types import Request, Response, StreamEvent

Middleware = Callable[[Request, Callable[..., Any]], Any]


class Client:
    def __init__(
        self,
        providers: dict[str, ProviderAdapter] | None = None,
        default_provider: str | None = None,
        middleware: list[Middleware] | None = None,
    ):
        self._providers: dict[str, ProviderAdapter] = providers or {}
        self._default_provider = default_provider
        self._middleware = middleware or []

        if not self._default_provider and self._providers:
            self._default_provider = next(iter(self._providers))

    @classmethod
    def from_env(cls) -> Client:
        """Create a client from environment variables, registering adapters for available keys."""
        providers: dict[str, ProviderAdapter] = {}

        if os.environ.get("ANTHROPIC_API_KEY"):
            from attractor.llm.adapters.anthropic import AnthropicAdapter

            providers["anthropic"] = AnthropicAdapter(
                api_key=os.environ["ANTHROPIC_API_KEY"],
                base_url=os.environ.get("ANTHROPIC_BASE_URL"),
            )

        return cls(providers=providers)

    def _resolve_provider(self, provider: str | None) -> ProviderAdapter:
        name = provider or self._default_provider
        if not name:
            raise ConfigurationError("No provider specified and no default provider set")
        adapter = self._providers.get(name)
        if not adapter:
            raise ConfigurationError(f"Provider '{name}' is not registered")
        return adapter

    async def complete(self, request: Request) -> Response:
        adapter = self._resolve_provider(request.provider)
        return await adapter.complete(request)

    async def stream(self, request: Request) -> AsyncIterator[StreamEvent]:
        adapter = self._resolve_provider(request.provider)
        return await adapter.stream(request)

    async def close(self) -> None:
        for adapter in self._providers.values():
            await adapter.close()

    def register(self, adapter: ProviderAdapter) -> None:
        self._providers[adapter.name] = adapter
        if not self._default_provider:
            self._default_provider = adapter.name
