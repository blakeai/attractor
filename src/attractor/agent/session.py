"""Agent session — orchestrates the agentic loop with conversation history and events."""

from __future__ import annotations

import asyncio
import hashlib
import json
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from attractor.agent.execution.base import ExecutionEnvironment
from attractor.agent.profiles.base import ProviderProfile
from attractor.agent.truncation import truncate_tool_output
from attractor.llm.client import Client
from attractor.llm.types import (
    ContentKind,
    ContentPart,
    Message,
    Request,
    Response,
    Role,
    ToolCall,
    ToolCallData,
    ToolResult,
    Usage,
)


class SessionState(StrEnum):
    IDLE = "idle"
    PROCESSING = "processing"
    AWAITING_INPUT = "awaiting_input"
    CLOSED = "closed"


class EventKind(StrEnum):
    SESSION_START = "session_start"
    SESSION_END = "session_end"
    USER_INPUT = "user_input"
    ASSISTANT_TEXT_END = "assistant_text_end"
    TOOL_CALL_START = "tool_call_start"
    TOOL_CALL_END = "tool_call_end"
    STEERING_INJECTED = "steering_injected"
    TURN_LIMIT = "turn_limit"
    LOOP_DETECTION = "loop_detection"
    ERROR = "error"


@dataclass
class SessionEvent:
    kind: EventKind
    timestamp: datetime
    session_id: str
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class SessionConfig:
    max_turns: int = 0
    max_tool_rounds_per_input: int = 0
    default_command_timeout_ms: int = 10000
    max_command_timeout_ms: int = 600000
    reasoning_effort: str | None = None
    tool_output_limits: dict[str, int] | None = None
    enable_loop_detection: bool = True
    loop_detection_window: int = 10


@dataclass
class Turn:
    kind: str  # "user", "assistant", "tool_results", "steering"
    content: str = ""
    tool_calls: list[ToolCall] | None = None
    tool_results: list[ToolResult] | None = None
    reasoning: str | None = None
    usage: Usage | None = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))


class Session:
    def __init__(
        self,
        profile: ProviderProfile,
        execution_env: ExecutionEnvironment,
        llm_client: Client,
        config: SessionConfig | None = None,
    ):
        self.id = str(uuid.uuid4())
        self.profile = profile
        self.execution_env = execution_env
        self.llm_client = llm_client
        self.config = config or SessionConfig()
        self.state = SessionState.IDLE
        self.history: list[Turn] = []
        self.events: list[SessionEvent] = []
        self.steering_queue: deque[str] = deque()
        self.followup_queue: deque[str] = deque()
        self.total_usage = Usage()

    def emit(self, kind: EventKind, **data: Any) -> SessionEvent:
        event = SessionEvent(
            kind=kind,
            timestamp=datetime.now(UTC),
            session_id=self.id,
            data=data,
        )
        self.events.append(event)
        return event

    def steer(self, message: str) -> None:
        self.steering_queue.append(message)

    def follow_up(self, message: str) -> None:
        self.followup_queue.append(message)

    def _drain_steering(self) -> None:
        while self.steering_queue:
            msg = self.steering_queue.popleft()
            self.history.append(Turn(kind="steering", content=msg))
            self.emit(EventKind.STEERING_INJECTED, content=msg)

    def _build_messages(self) -> list[Message]:
        system_prompt = self.profile.build_system_prompt(self.execution_env)
        messages: list[Message] = [Message.system(system_prompt)]

        for turn in self.history:
            if turn.kind == "user":
                messages.append(Message.user(turn.content))
            elif turn.kind == "assistant":
                parts: list[ContentPart] = []
                if turn.content:
                    parts.append(ContentPart(kind=ContentKind.TEXT, text=turn.content))
                if turn.tool_calls:
                    for tc in turn.tool_calls:
                        parts.append(ContentPart(
                            kind=ContentKind.TOOL_CALL,
                            tool_call=ToolCallData(
                                id=tc.id,
                                name=tc.name,
                                arguments=tc.arguments,
                            ),
                        ))
                messages.append(Message(role=Role.ASSISTANT, content=parts))
            elif turn.kind == "tool_results" and turn.tool_results:
                for tr in turn.tool_results:
                    messages.append(Message.tool_result(
                        tool_call_id=tr.tool_call_id,
                        content=tr.content,
                        is_error=tr.is_error,
                    ))
            elif turn.kind == "steering":
                messages.append(Message.user(turn.content))

        return messages

    def _detect_loop(self) -> bool:
        if not self.config.enable_loop_detection:
            return False

        window = self.config.loop_detection_window
        # Extract recent tool call signatures
        signatures: list[str] = []
        for turn in reversed(self.history):
            if turn.kind == "assistant" and turn.tool_calls:
                for tc in turn.tool_calls:
                    sig = hashlib.md5(
                        json.dumps({"name": tc.name, "args": tc.arguments}, sort_keys=True).encode()
                    ).hexdigest()[:8]
                    signatures.insert(0, sig)
            if len(signatures) >= window:
                break

        if len(signatures) < window:
            return False

        recent = signatures[-window:]
        for pattern_len in (1, 2, 3):
            if window % pattern_len != 0:
                continue
            pattern = recent[:pattern_len]
            all_match = True
            for i in range(pattern_len, window, pattern_len):
                if recent[i : i + pattern_len] != pattern:
                    all_match = False
                    break
            if all_match:
                return True

        return False

    async def _execute_tool_call(self, tool_call: ToolCall) -> ToolResult:
        self.emit(EventKind.TOOL_CALL_START, tool_name=tool_call.name, call_id=tool_call.id)

        tools = self.profile.tools(self.execution_env)
        tool_map = {t.name: t for t in tools}
        tool = tool_map.get(tool_call.name)

        if not tool or not tool.execute:
            error_msg = f"Unknown tool: {tool_call.name}"
            self.emit(EventKind.TOOL_CALL_END, call_id=tool_call.id, error=error_msg)
            return ToolResult(tool_call_id=tool_call.id, content=error_msg, is_error=True)

        try:
            raw_output = tool.execute(**tool_call.arguments)
            if asyncio.iscoroutine(raw_output):
                raw_output = await raw_output

            raw_str = raw_output if isinstance(raw_output, str) else str(raw_output)
            truncated = truncate_tool_output(
                raw_str, tool_call.name, self.config.tool_output_limits
            )

            self.emit(EventKind.TOOL_CALL_END, call_id=tool_call.id, output=raw_str)
            return ToolResult(tool_call_id=tool_call.id, content=truncated)

        except Exception as e:
            error_msg = f"Tool error ({tool_call.name}): {e}"
            self.emit(EventKind.TOOL_CALL_END, call_id=tool_call.id, error=error_msg)
            return ToolResult(tool_call_id=tool_call.id, content=error_msg, is_error=True)

    async def _execute_tool_calls(self, tool_calls: list[ToolCall]) -> list[ToolResult]:
        if self.profile.supports_parallel_tool_calls and len(tool_calls) > 1:
            return list(
                await asyncio.gather(*[self._execute_tool_call(tc) for tc in tool_calls])
            )
        results = []
        for tc in tool_calls:
            results.append(await self._execute_tool_call(tc))
        return results

    async def submit(self, user_input: str) -> str:
        """Submit user input and run the agentic loop until completion."""
        self.state = SessionState.PROCESSING
        self.history.append(Turn(kind="user", content=user_input))
        self.emit(EventKind.USER_INPUT, content=user_input)

        self._drain_steering()

        round_count = 0
        final_text = ""

        while True:
            # Check limits
            if (
                self.config.max_tool_rounds_per_input > 0
                and round_count >= self.config.max_tool_rounds_per_input
            ):
                self.emit(EventKind.TURN_LIMIT, round=round_count)
                break

            if self.config.max_turns > 0 and len(self.history) >= self.config.max_turns:
                self.emit(EventKind.TURN_LIMIT, total_turns=len(self.history))
                break

            # Build and send request
            messages = self._build_messages()
            tools = self.profile.tools(self.execution_env)

            request = Request(
                model=self.profile.model,
                messages=messages,
                tools=tools if tools else None,
                reasoning_effort=self.config.reasoning_effort,
                provider=self.profile.id,
                provider_options=self.profile.provider_options(),
            )

            response: Response = await self.llm_client.complete(request)

            # Record assistant turn
            self.history.append(Turn(
                kind="assistant",
                content=response.text,
                tool_calls=response.tool_calls or None,
                reasoning=response.reasoning,
                usage=response.usage,
            ))
            self.total_usage = self.total_usage + response.usage
            self.emit(EventKind.ASSISTANT_TEXT_END, text=response.text, reasoning=response.reasoning)

            final_text = response.text

            # If no tool calls, natural completion
            if not response.tool_calls:
                break

            # Execute tool calls
            round_count += 1
            results = await self._execute_tool_calls(response.tool_calls)
            self.history.append(Turn(kind="tool_results", tool_results=results))

            # Drain steering
            self._drain_steering()

            # Loop detection
            if self._detect_loop():
                warning = (
                    f"Loop detected: the last {self.config.loop_detection_window} tool calls "
                    "follow a repeating pattern. Try a different approach."
                )
                self.history.append(Turn(kind="steering", content=warning))
                self.emit(EventKind.LOOP_DETECTION, message=warning)

        # Process follow-ups
        if self.followup_queue:
            next_input = self.followup_queue.popleft()
            return await self.submit(next_input)

        self.state = SessionState.IDLE
        self.emit(EventKind.SESSION_END)
        return final_text
