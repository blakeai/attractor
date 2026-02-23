"""Tests for the LLM data model types."""

from attractor.llm.types import (
    ContentKind,
    ContentPart,
    FinishReason,
    Message,
    Response,
    Role,
    ToolCallData,
    Usage,
)


class TestMessage:
    def test_system_factory(self):
        msg = Message.system("You are helpful")
        assert msg.role == Role.SYSTEM
        assert msg.text == "You are helpful"
        assert len(msg.content) == 1
        assert msg.content[0].kind == ContentKind.TEXT

    def test_user_factory(self):
        msg = Message.user("Hello")
        assert msg.role == Role.USER
        assert msg.text == "Hello"

    def test_assistant_factory(self):
        msg = Message.assistant("Hi there")
        assert msg.role == Role.ASSISTANT
        assert msg.text == "Hi there"

    def test_tool_result_factory(self):
        msg = Message.tool_result("call_1", "result text")
        assert msg.role == Role.TOOL
        assert msg.tool_call_id == "call_1"
        assert msg.content[0].kind == ContentKind.TOOL_RESULT
        assert msg.content[0].tool_result.content == "result text"
        assert msg.content[0].tool_result.is_error is False

    def test_tool_result_error(self):
        msg = Message.tool_result("call_2", "error occurred", is_error=True)
        assert msg.content[0].tool_result.is_error is True

    def test_text_property_concatenates(self):
        msg = Message(
            role=Role.ASSISTANT,
            content=[
                ContentPart(kind=ContentKind.TEXT, text="Hello "),
                ContentPart(kind=ContentKind.TEXT, text="world"),
            ],
        )
        assert msg.text == "Hello world"

    def test_text_property_skips_non_text(self):
        msg = Message(
            role=Role.ASSISTANT,
            content=[
                ContentPart(kind=ContentKind.TEXT, text="Hello"),
                ContentPart(
                    kind=ContentKind.TOOL_CALL,
                    tool_call=ToolCallData(id="1", name="test", arguments={}),
                ),
            ],
        )
        assert msg.text == "Hello"


class TestUsage:
    def test_addition(self):
        a = Usage(input_tokens=10, output_tokens=20, total_tokens=30)
        b = Usage(input_tokens=5, output_tokens=15, total_tokens=20)
        result = a + b
        assert result.input_tokens == 15
        assert result.output_tokens == 35
        assert result.total_tokens == 50

    def test_addition_with_optional_fields(self):
        a = Usage(input_tokens=10, output_tokens=20, total_tokens=30, cache_read_tokens=5)
        b = Usage(input_tokens=5, output_tokens=15, total_tokens=20, cache_read_tokens=3)
        result = a + b
        assert result.cache_read_tokens == 8

    def test_addition_none_plus_value(self):
        a = Usage(input_tokens=10, output_tokens=20, total_tokens=30, cache_read_tokens=None)
        b = Usage(input_tokens=5, output_tokens=15, total_tokens=20, cache_read_tokens=3)
        result = a + b
        assert result.cache_read_tokens == 3

    def test_addition_both_none(self):
        a = Usage(input_tokens=10, output_tokens=20, total_tokens=30)
        b = Usage(input_tokens=5, output_tokens=15, total_tokens=20)
        result = a + b
        assert result.cache_read_tokens is None


class TestResponse:
    def test_text_property(self):
        resp = Response(
            id="msg_1",
            model="claude-opus-4-6",
            provider="anthropic",
            message=Message.assistant("The answer is 42"),
            finish_reason=FinishReason(reason="stop", raw="end_turn"),
            usage=Usage(input_tokens=10, output_tokens=5, total_tokens=15),
        )
        assert resp.text == "The answer is 42"

    def test_tool_calls_property(self):
        resp = Response(
            id="msg_2",
            model="claude-opus-4-6",
            provider="anthropic",
            message=Message(
                role=Role.ASSISTANT,
                content=[
                    ContentPart(
                        kind=ContentKind.TOOL_CALL,
                        tool_call=ToolCallData(
                            id="call_1",
                            name="get_weather",
                            arguments={"city": "SF"},
                        ),
                    )
                ],
            ),
            finish_reason=FinishReason(reason="tool_calls", raw="tool_use"),
            usage=Usage(input_tokens=10, output_tokens=20, total_tokens=30),
        )
        calls = resp.tool_calls
        assert len(calls) == 1
        assert calls[0].name == "get_weather"
        assert calls[0].arguments == {"city": "SF"}

    def test_reasoning_property(self):
        from attractor.llm.types import ThinkingData

        resp = Response(
            id="msg_3",
            model="claude-opus-4-6",
            provider="anthropic",
            message=Message(
                role=Role.ASSISTANT,
                content=[
                    ContentPart(
                        kind=ContentKind.THINKING,
                        thinking=ThinkingData(text="Let me think..."),
                    ),
                    ContentPart(kind=ContentKind.TEXT, text="42"),
                ],
            ),
            finish_reason=FinishReason(reason="stop"),
            usage=Usage(input_tokens=10, output_tokens=20, total_tokens=30),
        )
        assert resp.reasoning == "Let me think..."
        assert resp.text == "42"
