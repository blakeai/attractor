"""Tests for the LLM Client."""

import pytest

from attractor.llm.adapter import ProviderAdapter
from attractor.llm.client import Client
from attractor.llm.errors import ConfigurationError
from attractor.llm.types import (
    FinishReason,
    Message,
    Request,
    Response,
    Usage,
)


class MockAdapter(ProviderAdapter):
    def __init__(self, name_: str = "mock"):
        self._name = name_
        self.last_request: Request | None = None

    @property
    def name(self) -> str:
        return self._name

    async def complete(self, request: Request) -> Response:
        self.last_request = request
        return Response(
            id="mock_1",
            model=request.model,
            provider=self._name,
            message=Message.assistant("Mock response"),
            finish_reason=FinishReason(reason="stop"),
            usage=Usage(input_tokens=10, output_tokens=5, total_tokens=15),
        )

    async def stream(self, request):
        raise NotImplementedError


class TestClient:
    @pytest.mark.asyncio
    async def test_complete_routes_to_adapter(self):
        adapter = MockAdapter()
        client = Client(providers={"mock": adapter})

        request = Request(model="test-model", messages=[Message.user("Hello")])
        response = await client.complete(request)

        assert response.provider == "mock"
        assert response.text == "Mock response"
        assert adapter.last_request is not None

    @pytest.mark.asyncio
    async def test_default_provider(self):
        adapter = MockAdapter()
        client = Client(providers={"mock": adapter}, default_provider="mock")

        request = Request(model="test-model", messages=[Message.user("Hello")])
        response = await client.complete(request)
        assert response.provider == "mock"

    @pytest.mark.asyncio
    async def test_explicit_provider(self):
        mock1 = MockAdapter("mock1")
        mock2 = MockAdapter("mock2")
        client = Client(providers={"mock1": mock1, "mock2": mock2}, default_provider="mock1")

        request = Request(
            model="test-model", messages=[Message.user("Hello")], provider="mock2"
        )
        response = await client.complete(request)
        assert response.provider == "mock2"

    @pytest.mark.asyncio
    async def test_no_provider_raises(self):
        client = Client()
        request = Request(model="test-model", messages=[Message.user("Hello")])
        with pytest.raises(ConfigurationError):
            await client.complete(request)

    @pytest.mark.asyncio
    async def test_unknown_provider_raises(self):
        client = Client(providers={"mock": MockAdapter()})
        request = Request(
            model="test-model", messages=[Message.user("Hello")], provider="unknown"
        )
        with pytest.raises(ConfigurationError, match="not registered"):
            await client.complete(request)

    def test_register(self):
        client = Client()
        adapter = MockAdapter("new")
        client.register(adapter)
        assert "new" in client._providers

    @pytest.mark.asyncio
    async def test_close(self):
        adapter = MockAdapter()
        client = Client(providers={"mock": adapter})
        await client.close()  # Should not raise
