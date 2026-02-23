"""Anthropic Messages API adapter."""

from __future__ import annotations

import contextlib
import json
from collections.abc import AsyncIterator
from typing import Any

import httpx

from attractor.llm.adapter import ProviderAdapter
from attractor.llm.errors import error_from_status
from attractor.llm.types import (
    ContentKind,
    ContentPart,
    FinishReason,
    Message,
    Request,
    Response,
    Role,
    StreamEvent,
    StreamEventType,
    ThinkingData,
    ToolCallData,
    ToolChoice,
    Usage,
)

ANTHROPIC_API_VERSION = "2023-06-01"
DEFAULT_BASE_URL = "https://api.anthropic.com"
DEFAULT_MAX_TOKENS = 16384

FINISH_REASON_MAP: dict[str, str] = {
    "end_turn": "stop",
    "stop_sequence": "stop",
    "max_tokens": "length",
    "tool_use": "tool_calls",
}


class AnthropicAdapter(ProviderAdapter):
    def __init__(
        self,
        api_key: str,
        base_url: str | None = None,
        default_headers: dict[str, str] | None = None,
        timeout: float = 120.0,
    ):
        self._api_key = api_key
        self._base_url = (base_url or DEFAULT_BASE_URL).rstrip("/")
        self._default_headers = default_headers or {}
        self._client = httpx.AsyncClient(timeout=timeout)

    @property
    def name(self) -> str:
        return "anthropic"

    async def close(self) -> None:
        await self._client.aclose()

    def supports_tool_choice(self, mode: str) -> bool:
        return mode in ("auto", "required", "named")

    def _build_headers(self, request: Request) -> dict[str, str]:
        headers = {
            "x-api-key": self._api_key,
            "anthropic-version": ANTHROPIC_API_VERSION,
            "content-type": "application/json",
            **self._default_headers,
        }
        provider_opts = (request.provider_options or {}).get("anthropic", {})
        beta_headers = provider_opts.get("beta_headers", [])
        if beta_headers:
            headers["anthropic-beta"] = ",".join(beta_headers)
        return headers

    def _translate_request(self, request: Request) -> dict[str, Any]:
        system_parts: list[str] = []
        messages: list[dict[str, Any]] = []

        for msg in request.messages:
            if msg.role in (Role.SYSTEM, Role.DEVELOPER):
                system_parts.append(msg.text)
                continue

            if msg.role == Role.TOOL:
                content_blocks = self._translate_tool_result_blocks(msg)
                # Tool results go in a user message per Anthropic spec
                if messages and messages[-1]["role"] == "user":
                    messages[-1]["content"].extend(content_blocks)
                else:
                    messages.append({"role": "user", "content": content_blocks})
                continue

            role = "assistant" if msg.role == Role.ASSISTANT else "user"
            content_blocks = self._translate_content_parts(msg.content, msg.role)

            # Merge consecutive same-role messages (Anthropic strict alternation)
            if messages and messages[-1]["role"] == role:
                messages[-1]["content"].extend(content_blocks)
            else:
                messages.append({"role": role, "content": content_blocks})

        body: dict[str, Any] = {
            "model": request.model,
            "messages": messages,
            "max_tokens": request.max_tokens or DEFAULT_MAX_TOKENS,
        }

        if system_parts:
            body["system"] = "\n\n".join(system_parts)

        if request.tools:
            body["tools"] = [
                {
                    "name": t.name,
                    "description": t.description,
                    "input_schema": t.parameters,
                }
                for t in request.tools
            ]

        if request.tool_choice and request.tools:
            body["tool_choice"] = self._translate_tool_choice(request.tool_choice)

        if request.temperature is not None:
            body["temperature"] = request.temperature
        if request.top_p is not None:
            body["top_p"] = request.top_p
        if request.stop_sequences:
            body["stop_sequences"] = request.stop_sequences

        # Provider-specific options
        provider_opts = (request.provider_options or {}).get("anthropic", {})
        if "thinking" in provider_opts:
            body["thinking"] = provider_opts["thinking"]

        return body

    def _translate_content_parts(
        self, parts: list[ContentPart], role: Role
    ) -> list[dict[str, Any]]:
        blocks: list[dict[str, Any]] = []
        for part in parts:
            if part.kind == ContentKind.TEXT and part.text:
                blocks.append({"type": "text", "text": part.text})
            elif part.kind == ContentKind.TOOL_CALL and part.tool_call:
                tc = part.tool_call
                args = tc.arguments if isinstance(tc.arguments, dict) else json.loads(tc.arguments)
                blocks.append({"type": "tool_use", "id": tc.id, "name": tc.name, "input": args})
            elif part.kind == ContentKind.THINKING and part.thinking:
                block: dict[str, Any] = {
                    "type": "thinking",
                    "thinking": part.thinking.text,
                }
                if part.thinking.signature:
                    block["signature"] = part.thinking.signature
                blocks.append(block)
            elif part.kind == ContentKind.REDACTED_THINKING and part.thinking:
                blocks.append({"type": "redacted_thinking", "data": part.thinking.text})
            elif part.kind == ContentKind.IMAGE and part.image:
                if part.image.url:
                    blocks.append({
                        "type": "image",
                        "source": {"type": "url", "url": part.image.url},
                    })
                elif part.image.data:
                    import base64

                    blocks.append({
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": part.image.media_type or "image/png",
                            "data": base64.b64encode(part.image.data).decode(),
                        },
                    })
        return blocks

    def _translate_tool_result_blocks(self, msg: Message) -> list[dict[str, Any]]:
        blocks: list[dict[str, Any]] = []
        for part in msg.content:
            if part.kind == ContentKind.TOOL_RESULT and part.tool_result:
                tr = part.tool_result
                content = tr.content if isinstance(tr.content, str) else json.dumps(tr.content)
                blocks.append({
                    "type": "tool_result",
                    "tool_use_id": tr.tool_call_id,
                    "content": content,
                    "is_error": tr.is_error,
                })
        return blocks

    def _translate_tool_choice(self, tc: ToolChoice) -> dict[str, Any]:
        if tc.mode == "auto":
            return {"type": "auto"}
        elif tc.mode == "required":
            return {"type": "any"}
        elif tc.mode == "named" and tc.tool_name:
            return {"type": "tool", "name": tc.tool_name}
        return {"type": "auto"}

    def _parse_response(self, data: dict[str, Any], request: Request) -> Response:
        content_parts: list[ContentPart] = []

        for block in data.get("content", []):
            block_type = block.get("type")
            if block_type == "text":
                content_parts.append(ContentPart(kind=ContentKind.TEXT, text=block["text"]))
            elif block_type == "tool_use":
                content_parts.append(
                    ContentPart(
                        kind=ContentKind.TOOL_CALL,
                        tool_call=ToolCallData(
                            id=block["id"],
                            name=block["name"],
                            arguments=block.get("input", {}),
                        ),
                    )
                )
            elif block_type == "thinking":
                content_parts.append(
                    ContentPart(
                        kind=ContentKind.THINKING,
                        thinking=ThinkingData(
                            text=block.get("thinking", ""),
                            signature=block.get("signature"),
                        ),
                    )
                )
            elif block_type == "redacted_thinking":
                content_parts.append(
                    ContentPart(
                        kind=ContentKind.REDACTED_THINKING,
                        thinking=ThinkingData(
                            text=block.get("data", ""),
                            redacted=True,
                        ),
                    )
                )

        raw_stop = data.get("stop_reason", "end_turn")
        usage_data = data.get("usage", {})

        return Response(
            id=data.get("id", ""),
            model=data.get("model", request.model),
            provider="anthropic",
            message=Message(role=Role.ASSISTANT, content=content_parts),
            finish_reason=FinishReason(
                reason=FINISH_REASON_MAP.get(raw_stop, "other"),
                raw=raw_stop,
            ),
            usage=Usage(
                input_tokens=usage_data.get("input_tokens", 0),
                output_tokens=usage_data.get("output_tokens", 0),
                total_tokens=usage_data.get("input_tokens", 0)
                + usage_data.get("output_tokens", 0),
                cache_read_tokens=usage_data.get("cache_read_input_tokens"),
                cache_write_tokens=usage_data.get("cache_creation_input_tokens"),
                raw=usage_data,
            ),
            raw=data,
        )

    async def complete(self, request: Request) -> Response:
        headers = self._build_headers(request)
        body = self._translate_request(request)
        url = f"{self._base_url}/v1/messages"

        resp = await self._client.post(url, headers=headers, json=body)

        if resp.status_code != 200:
            raw_body = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else None
            error_msg = "Anthropic API error"
            if raw_body and "error" in raw_body:
                error_msg = raw_body["error"].get("message", error_msg)
            retry_after = None
            if "retry-after" in resp.headers:
                with contextlib.suppress(ValueError):
                    retry_after = float(resp.headers["retry-after"])
            raise error_from_status(
                resp.status_code, error_msg, provider="anthropic", raw=raw_body, retry_after=retry_after
            )

        return self._parse_response(resp.json(), request)

    async def stream(self, request: Request) -> AsyncIterator[StreamEvent]:
        headers = self._build_headers(request)
        body = self._translate_request(request)
        body["stream"] = True
        url = f"{self._base_url}/v1/messages"

        async with self._client.stream("POST", url, headers=headers, json=body) as resp:
            if resp.status_code != 200:
                await resp.aread()
                raw_body = None
                with contextlib.suppress(Exception):
                    raw_body = resp.json()
                error_msg = "Anthropic API error"
                if raw_body and "error" in raw_body:
                    error_msg = raw_body["error"].get("message", error_msg)
                raise error_from_status(
                    resp.status_code, error_msg, provider="anthropic", raw=raw_body
                )

            async for event in self._parse_sse_stream(resp, request):
                yield event

    async def _parse_sse_stream(
        self, resp: httpx.Response, request: Request
    ) -> AsyncIterator[StreamEvent]:
        accumulated_content: list[ContentPart] = []
        accumulated_usage = Usage()
        current_block_type: str | None = None
        current_block_data: dict[str, Any] = {}
        message_id = ""
        model = request.model
        raw_stop_reason = "end_turn"

        event_type = ""
        data_buffer = ""

        async for line in resp.aiter_lines():
            line = line.strip()

            if not line:
                # Event boundary — process buffered event
                if event_type and data_buffer:
                    data = json.loads(data_buffer)

                    if event_type == "message_start":
                        msg = data.get("message", {})
                        message_id = msg.get("id", "")
                        model = msg.get("model", model)
                        usage_data = msg.get("usage", {})
                        accumulated_usage = Usage(
                            input_tokens=usage_data.get("input_tokens", 0),
                            output_tokens=0,
                            total_tokens=usage_data.get("input_tokens", 0),
                            cache_read_tokens=usage_data.get("cache_read_input_tokens"),
                            cache_write_tokens=usage_data.get("cache_creation_input_tokens"),
                        )
                        yield StreamEvent(type=StreamEventType.STREAM_START)

                    elif event_type == "content_block_start":
                        block = data.get("content_block", {})
                        current_block_type = block.get("type")
                        current_block_data = block

                        if current_block_type == "text":
                            yield StreamEvent(type=StreamEventType.TEXT_START)
                        elif current_block_type == "tool_use":
                            from attractor.llm.types import ToolCall

                            yield StreamEvent(
                                type=StreamEventType.TOOL_CALL_START,
                                tool_call=ToolCall(
                                    id=block.get("id", ""),
                                    name=block.get("name", ""),
                                ),
                            )
                        elif current_block_type == "thinking":
                            yield StreamEvent(type=StreamEventType.REASONING_START)

                    elif event_type == "content_block_delta":
                        delta = data.get("delta", {})
                        delta_type = delta.get("type")

                        if delta_type == "text_delta":
                            yield StreamEvent(
                                type=StreamEventType.TEXT_DELTA,
                                delta=delta.get("text", ""),
                            )
                        elif delta_type == "input_json_delta":
                            yield StreamEvent(
                                type=StreamEventType.TOOL_CALL_DELTA,
                                delta=delta.get("partial_json", ""),
                            )
                        elif delta_type == "thinking_delta":
                            yield StreamEvent(
                                type=StreamEventType.REASONING_DELTA,
                                reasoning_delta=delta.get("thinking", ""),
                            )

                    elif event_type == "content_block_stop":
                        if current_block_type == "text":
                            text = current_block_data.get("text", "")
                            accumulated_content.append(
                                ContentPart(kind=ContentKind.TEXT, text=text)
                            )
                            yield StreamEvent(type=StreamEventType.TEXT_END)
                        elif current_block_type == "tool_use":
                            accumulated_content.append(
                                ContentPart(
                                    kind=ContentKind.TOOL_CALL,
                                    tool_call=ToolCallData(
                                        id=current_block_data.get("id", ""),
                                        name=current_block_data.get("name", ""),
                                        arguments=current_block_data.get("input", {}),
                                    ),
                                )
                            )
                            yield StreamEvent(type=StreamEventType.TOOL_CALL_END)
                        elif current_block_type == "thinking":
                            accumulated_content.append(
                                ContentPart(
                                    kind=ContentKind.THINKING,
                                    thinking=ThinkingData(
                                        text=current_block_data.get("thinking", ""),
                                        signature=current_block_data.get("signature"),
                                    ),
                                )
                            )
                            yield StreamEvent(type=StreamEventType.REASONING_END)
                        current_block_type = None
                        current_block_data = {}

                    elif event_type == "message_delta":
                        delta = data.get("delta", {})
                        raw_stop_reason = delta.get("stop_reason", raw_stop_reason)
                        usage_delta = data.get("usage", {})
                        if usage_delta:
                            accumulated_usage = Usage(
                                input_tokens=accumulated_usage.input_tokens,
                                output_tokens=usage_delta.get(
                                    "output_tokens", accumulated_usage.output_tokens
                                ),
                                total_tokens=accumulated_usage.input_tokens
                                + usage_delta.get("output_tokens", accumulated_usage.output_tokens),
                                cache_read_tokens=accumulated_usage.cache_read_tokens,
                                cache_write_tokens=accumulated_usage.cache_write_tokens,
                            )

                    elif event_type == "message_stop":
                        finish = FinishReason(
                            reason=FINISH_REASON_MAP.get(raw_stop_reason, "other"),
                            raw=raw_stop_reason,
                        )
                        response = Response(
                            id=message_id,
                            model=model,
                            provider="anthropic",
                            message=Message(role=Role.ASSISTANT, content=accumulated_content),
                            finish_reason=finish,
                            usage=accumulated_usage,
                        )
                        yield StreamEvent(
                            type=StreamEventType.FINISH,
                            finish_reason=finish,
                            usage=accumulated_usage,
                            response=response,
                        )

                event_type = ""
                data_buffer = ""
                continue

            if line.startswith("event:"):
                event_type = line[len("event:"):].strip()
            elif line.startswith("data:"):
                data_buffer = line[len("data:"):].strip()
