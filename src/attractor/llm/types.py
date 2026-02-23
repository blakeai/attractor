"""Unified LLM Client data model — types for messages, requests, responses, tools, and streaming."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class Role(StrEnum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"
    DEVELOPER = "developer"


class ContentKind(StrEnum):
    TEXT = "text"
    IMAGE = "image"
    AUDIO = "audio"
    DOCUMENT = "document"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    THINKING = "thinking"
    REDACTED_THINKING = "redacted_thinking"


class ImageData(BaseModel):
    url: str | None = None
    data: bytes | None = None
    media_type: str | None = None
    detail: str | None = None


class AudioData(BaseModel):
    url: str | None = None
    data: bytes | None = None
    media_type: str | None = None


class DocumentData(BaseModel):
    url: str | None = None
    data: bytes | None = None
    media_type: str | None = None
    file_name: str | None = None


class ToolCallData(BaseModel):
    id: str
    name: str
    arguments: dict[str, Any] | str
    type: str = "function"


class ToolResultData(BaseModel):
    tool_call_id: str
    content: str | dict[str, Any]
    is_error: bool = False
    image_data: bytes | None = None
    image_media_type: str | None = None


class ThinkingData(BaseModel):
    text: str
    signature: str | None = None
    redacted: bool = False


class ContentPart(BaseModel):
    kind: ContentKind | str
    text: str | None = None
    image: ImageData | None = None
    audio: AudioData | None = None
    document: DocumentData | None = None
    tool_call: ToolCallData | None = None
    tool_result: ToolResultData | None = None
    thinking: ThinkingData | None = None


class Message(BaseModel):
    role: Role
    content: list[ContentPart]
    name: str | None = None
    tool_call_id: str | None = None

    @staticmethod
    def system(text: str) -> Message:
        return Message(role=Role.SYSTEM, content=[ContentPart(kind=ContentKind.TEXT, text=text)])

    @staticmethod
    def user(text: str) -> Message:
        return Message(role=Role.USER, content=[ContentPart(kind=ContentKind.TEXT, text=text)])

    @staticmethod
    def assistant(text: str) -> Message:
        return Message(
            role=Role.ASSISTANT, content=[ContentPart(kind=ContentKind.TEXT, text=text)]
        )

    @staticmethod
    def tool_result(
        tool_call_id: str,
        content: str | dict[str, Any],
        is_error: bool = False,
    ) -> Message:
        return Message(
            role=Role.TOOL,
            content=[
                ContentPart(
                    kind=ContentKind.TOOL_RESULT,
                    tool_result=ToolResultData(
                        tool_call_id=tool_call_id,
                        content=content,
                        is_error=is_error,
                    ),
                )
            ],
            tool_call_id=tool_call_id,
        )

    @property
    def text(self) -> str:
        return "".join(p.text for p in self.content if p.kind == ContentKind.TEXT and p.text)


class ToolChoice(BaseModel):
    mode: str = "auto"
    tool_name: str | None = None


class ToolCall(BaseModel):
    id: str
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    raw_arguments: str | None = None


class ToolResult(BaseModel):
    tool_call_id: str
    content: str | dict[str, Any] | list[Any]
    is_error: bool = False


class ResponseFormat(BaseModel):
    type: str = "text"
    json_schema: dict[str, Any] | None = None
    strict: bool = False


class Tool(BaseModel):
    model_config = {"arbitrary_types_allowed": True}

    name: str
    description: str
    parameters: dict[str, Any]
    execute: Callable[..., Any] | None = None


class Request(BaseModel):
    model: str
    messages: list[Message]
    provider: str | None = None
    tools: list[Tool] | None = None
    tool_choice: ToolChoice | None = None
    response_format: ResponseFormat | None = None
    temperature: float | None = None
    top_p: float | None = None
    max_tokens: int | None = None
    stop_sequences: list[str] | None = None
    reasoning_effort: str | None = None
    metadata: dict[str, str] | None = None
    provider_options: dict[str, Any] | None = None


class FinishReason(BaseModel):
    reason: str
    raw: str | None = None


class Usage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    reasoning_tokens: int | None = None
    cache_read_tokens: int | None = None
    cache_write_tokens: int | None = None
    raw: dict[str, Any] | None = None

    def __add__(self, other: Usage) -> Usage:
        def _add_opt(a: int | None, b: int | None) -> int | None:
            if a is None and b is None:
                return None
            return (a or 0) + (b or 0)

        return Usage(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            total_tokens=self.total_tokens + other.total_tokens,
            reasoning_tokens=_add_opt(self.reasoning_tokens, other.reasoning_tokens),
            cache_read_tokens=_add_opt(self.cache_read_tokens, other.cache_read_tokens),
            cache_write_tokens=_add_opt(self.cache_write_tokens, other.cache_write_tokens),
        )


class Warning(BaseModel):
    message: str
    code: str | None = None


class RateLimitInfo(BaseModel):
    requests_remaining: int | None = None
    requests_limit: int | None = None
    tokens_remaining: int | None = None
    tokens_limit: int | None = None
    reset_at: datetime | None = None


class Response(BaseModel):
    id: str
    model: str
    provider: str
    message: Message
    finish_reason: FinishReason
    usage: Usage
    raw: dict[str, Any] | None = None
    warnings: list[Warning] = Field(default_factory=list)
    rate_limit: RateLimitInfo | None = None

    @property
    def text(self) -> str:
        return self.message.text

    @property
    def tool_calls(self) -> list[ToolCall]:
        calls = []
        for part in self.message.content:
            if part.kind == ContentKind.TOOL_CALL and part.tool_call:
                tc = part.tool_call
                args = tc.arguments if isinstance(tc.arguments, dict) else {}
                calls.append(
                    ToolCall(
                        id=tc.id,
                        name=tc.name,
                        arguments=args,
                        raw_arguments=tc.arguments if isinstance(tc.arguments, str) else None,
                    )
                )
        return calls

    @property
    def reasoning(self) -> str | None:
        parts = [
            p.thinking.text
            for p in self.message.content
            if p.kind == ContentKind.THINKING and p.thinking and p.thinking.text
        ]
        return "".join(parts) if parts else None


class StreamEventType(StrEnum):
    STREAM_START = "stream_start"
    TEXT_START = "text_start"
    TEXT_DELTA = "text_delta"
    TEXT_END = "text_end"
    REASONING_START = "reasoning_start"
    REASONING_DELTA = "reasoning_delta"
    REASONING_END = "reasoning_end"
    TOOL_CALL_START = "tool_call_start"
    TOOL_CALL_DELTA = "tool_call_delta"
    TOOL_CALL_END = "tool_call_end"
    FINISH = "finish"
    ERROR = "error"
    PROVIDER_EVENT = "provider_event"


class StreamEvent(BaseModel):
    type: StreamEventType | str
    delta: str | None = None
    text_id: str | None = None
    reasoning_delta: str | None = None
    tool_call: ToolCall | None = None
    finish_reason: FinishReason | None = None
    usage: Usage | None = None
    response: Response | None = None
    error: Any | None = None
    raw: dict[str, Any] | None = None
