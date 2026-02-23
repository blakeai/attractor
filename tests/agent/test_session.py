"""Tests for the agent session and agentic loop."""

import pytest

from attractor.agent.execution.local import LocalExecutionEnvironment
from attractor.agent.profiles.anthropic import AnthropicProfile
from attractor.agent.session import EventKind, Session, SessionConfig
from attractor.llm.adapter import ProviderAdapter
from attractor.llm.client import Client
from attractor.llm.types import (
    ContentKind,
    ContentPart,
    FinishReason,
    Message,
    Request,
    Response,
    Role,
    ToolCallData,
    Usage,
)


class MockLLMAdapter(ProviderAdapter):
    """Mock adapter that returns predefined responses in sequence."""

    def __init__(self, responses: list[Response]):
        self._responses = list(responses)
        self._call_count = 0

    @property
    def name(self) -> str:
        return "anthropic"

    async def complete(self, request: Request) -> Response:
        if self._call_count < len(self._responses):
            resp = self._responses[self._call_count]
            self._call_count += 1
            return resp
        return Response(
            id="fallback",
            model=request.model,
            provider="anthropic",
            message=Message.assistant("Done"),
            finish_reason=FinishReason(reason="stop"),
            usage=Usage(input_tokens=10, output_tokens=5, total_tokens=15),
        )

    async def stream(self, request):
        raise NotImplementedError


def _text_response(text: str) -> Response:
    return Response(
        id="resp_1",
        model="test",
        provider="anthropic",
        message=Message.assistant(text),
        finish_reason=FinishReason(reason="stop", raw="end_turn"),
        usage=Usage(input_tokens=10, output_tokens=20, total_tokens=30),
    )


def _tool_call_response(tool_name: str, args: dict, call_id: str = "call_1") -> Response:
    return Response(
        id="resp_tc",
        model="test",
        provider="anthropic",
        message=Message(
            role=Role.ASSISTANT,
            content=[
                ContentPart(
                    kind=ContentKind.TOOL_CALL,
                    tool_call=ToolCallData(id=call_id, name=tool_name, arguments=args),
                )
            ],
        ),
        finish_reason=FinishReason(reason="tool_calls", raw="tool_use"),
        usage=Usage(input_tokens=10, output_tokens=20, total_tokens=30),
    )


@pytest.fixture
def tmp_dir(tmp_path):
    return str(tmp_path)


class TestSession:
    @pytest.mark.asyncio
    async def test_simple_text_response(self, tmp_dir):
        adapter = MockLLMAdapter([_text_response("Hello!")])
        client = Client(providers={"anthropic": adapter})
        env = LocalExecutionEnvironment(tmp_dir)
        profile = AnthropicProfile(model="test")

        session = Session(profile, env, client)
        result = await session.submit("Say hello")

        assert result == "Hello!"
        assert len(session.events) >= 3  # user_input, assistant_text_end, session_end
        assert any(e.kind == EventKind.SESSION_END for e in session.events)

    @pytest.mark.asyncio
    async def test_tool_call_then_text(self, tmp_dir):
        import os

        test_file = os.path.join(tmp_dir, "test.txt")
        with open(test_file, "w") as f:
            f.write("hello world\n")

        adapter = MockLLMAdapter([
            _tool_call_response("read_file", {"file_path": test_file}),
            _text_response("The file says hello world"),
        ])
        client = Client(providers={"anthropic": adapter})
        env = LocalExecutionEnvironment(tmp_dir)
        profile = AnthropicProfile(model="test")

        session = Session(profile, env, client)
        result = await session.submit("Read the test file")

        assert result == "The file says hello world"
        assert any(e.kind == EventKind.TOOL_CALL_START for e in session.events)
        assert any(e.kind == EventKind.TOOL_CALL_END for e in session.events)

    @pytest.mark.asyncio
    async def test_round_limit(self, tmp_dir):
        # Model keeps calling tools forever — should hit limit
        responses = [
            _tool_call_response("shell", {"command": "echo hi"}, f"call_{i}")
            for i in range(10)
        ]
        adapter = MockLLMAdapter(responses)
        client = Client(providers={"anthropic": adapter})
        env = LocalExecutionEnvironment(tmp_dir)
        profile = AnthropicProfile(model="test")
        config = SessionConfig(max_tool_rounds_per_input=3)

        session = Session(profile, env, client, config)
        await session.submit("Keep going")

        assert any(e.kind == EventKind.TURN_LIMIT for e in session.events)

    @pytest.mark.asyncio
    async def test_steering(self, tmp_dir):
        adapter = MockLLMAdapter([
            _tool_call_response("shell", {"command": "echo hi"}),
            _text_response("Done, with new instructions"),
        ])
        client = Client(providers={"anthropic": adapter})
        env = LocalExecutionEnvironment(tmp_dir)
        profile = AnthropicProfile(model="test")

        session = Session(profile, env, client)
        session.steer("Focus on testing")
        result = await session.submit("Start")

        assert result == "Done, with new instructions"
        assert any(e.kind == EventKind.STEERING_INJECTED for e in session.events)

    @pytest.mark.asyncio
    async def test_unknown_tool(self, tmp_dir):
        adapter = MockLLMAdapter([
            _tool_call_response("nonexistent_tool", {"arg": "val"}),
            _text_response("I see that tool doesn't exist"),
        ])
        client = Client(providers={"anthropic": adapter})
        env = LocalExecutionEnvironment(tmp_dir)
        profile = AnthropicProfile(model="test")

        session = Session(profile, env, client)
        result = await session.submit("Use a tool")

        # Should handle gracefully
        assert result == "I see that tool doesn't exist"

    @pytest.mark.asyncio
    async def test_usage_tracking(self, tmp_dir):
        adapter = MockLLMAdapter([
            _tool_call_response("shell", {"command": "echo hi"}),
            _text_response("Done"),
        ])
        client = Client(providers={"anthropic": adapter})
        env = LocalExecutionEnvironment(tmp_dir)
        profile = AnthropicProfile(model="test")

        session = Session(profile, env, client)
        await session.submit("Run something")

        assert session.total_usage.input_tokens == 20
        assert session.total_usage.output_tokens == 40
