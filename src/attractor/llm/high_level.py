"""High-level API: generate() with automatic tool execution loop."""

from __future__ import annotations

import asyncio
from typing import Any

from attractor.llm.client import Client
from attractor.llm.retry import RetryPolicy, retry
from attractor.llm.types import (
    FinishReason,
    Message,
    Request,
    Response,
    Tool,
    ToolCall,
    ToolChoice,
    ToolResult,
    Usage,
    Warning,
)

# Module-level default client (lazily initialized)
_default_client: Client | None = None


def set_default_client(client: Client) -> None:
    global _default_client
    _default_client = client


def get_default_client() -> Client:
    global _default_client
    if _default_client is None:
        _default_client = Client.from_env()
    return _default_client


class StepResult:
    def __init__(
        self,
        text: str,
        reasoning: str | None,
        tool_calls: list[ToolCall],
        tool_results: list[ToolResult],
        finish_reason: FinishReason,
        usage: Usage,
        response: Response,
        warnings: list[Warning] | None = None,
    ):
        self.text = text
        self.reasoning = reasoning
        self.tool_calls = tool_calls
        self.tool_results = tool_results
        self.finish_reason = finish_reason
        self.usage = usage
        self.response = response
        self.warnings = warnings or []


class GenerateResult:
    def __init__(
        self,
        text: str,
        reasoning: str | None,
        tool_calls: list[ToolCall],
        tool_results: list[ToolResult],
        finish_reason: FinishReason,
        usage: Usage,
        total_usage: Usage,
        steps: list[StepResult],
        response: Response,
    ):
        self.text = text
        self.reasoning = reasoning
        self.tool_calls = tool_calls
        self.tool_results = tool_results
        self.finish_reason = finish_reason
        self.usage = usage
        self.total_usage = total_usage
        self.steps = steps
        self.response = response


async def _execute_tool(
    tool: Tool, tool_call: ToolCall
) -> ToolResult:
    try:
        if tool.execute is None:
            return ToolResult(
                tool_call_id=tool_call.id,
                content=f"Tool '{tool_call.name}' has no execute handler",
                is_error=True,
            )
        result = tool.execute(**tool_call.arguments)
        if asyncio.iscoroutine(result):
            result = await result
        content = result if isinstance(result, (str, dict, list)) else str(result)
        return ToolResult(tool_call_id=tool_call.id, content=content)
    except Exception as e:
        return ToolResult(tool_call_id=tool_call.id, content=str(e), is_error=True)


async def _execute_all_tools(
    tools: list[Tool], tool_calls: list[ToolCall]
) -> list[ToolResult]:
    tool_map = {t.name: t for t in tools}
    tasks = []
    for tc in tool_calls:
        tool = tool_map.get(tc.name)
        if tool:
            tasks.append(_execute_tool(tool, tc))
        else:
            tasks.append(
                asyncio.coroutine(lambda tc=tc: ToolResult(
                    tool_call_id=tc.id,
                    content=f"Unknown tool: {tc.name}",
                    is_error=True,
                ))()
            )

    return list(await asyncio.gather(*tasks))


async def generate(
    model: str,
    prompt: str | None = None,
    messages: list[Message] | None = None,
    system: str | None = None,
    tools: list[Tool] | None = None,
    tool_choice: ToolChoice | None = None,
    max_tool_rounds: int = 1,
    temperature: float | None = None,
    max_tokens: int | None = None,
    reasoning_effort: str | None = None,
    provider: str | None = None,
    provider_options: dict[str, Any] | None = None,
    max_retries: int = 2,
    client: Client | None = None,
) -> GenerateResult:
    """High-level generate with automatic tool execution loop."""
    active_client = client or get_default_client()

    # Build initial messages
    conversation: list[Message] = []
    if system:
        conversation.append(Message.system(system))
    if messages:
        conversation.extend(messages)
    elif prompt:
        conversation.append(Message.user(prompt))

    # Find active tools (those with execute handlers)
    active_tools = [t for t in (tools or []) if t.execute is not None]
    tool_defs = tools  # Pass all tools to the model (active and passive)

    steps: list[StepResult] = []
    total_usage = Usage()
    retry_policy = RetryPolicy(max_retries=max_retries)

    for round_num in range(max_tool_rounds + 1):
        request = Request(
            model=model,
            messages=conversation,
            tools=tool_defs,
            tool_choice=tool_choice,
            temperature=temperature,
            max_tokens=max_tokens,
            reasoning_effort=reasoning_effort,
            provider=provider,
            provider_options=provider_options,
        )

        response = await retry(lambda r=request: active_client.complete(r), policy=retry_policy)
        tool_calls = response.tool_calls
        tool_results: list[ToolResult] = []

        if tool_calls and response.finish_reason.reason == "tool_calls" and active_tools:
            tool_results = await _execute_all_tools(active_tools, tool_calls)

        step = StepResult(
            text=response.text,
            reasoning=response.reasoning,
            tool_calls=tool_calls,
            tool_results=tool_results,
            finish_reason=response.finish_reason,
            usage=response.usage,
            response=response,
            warnings=response.warnings,
        )
        steps.append(step)
        total_usage = total_usage + response.usage

        # Check if we should stop
        if not tool_calls or response.finish_reason.reason != "tool_calls":
            break
        if round_num >= max_tool_rounds:
            break
        if not tool_results:
            break

        # Continue conversation with assistant message and tool results
        conversation.append(response.message)
        for tr in tool_results:
            conversation.append(Message.tool_result(
                tool_call_id=tr.tool_call_id,
                content=tr.content,
                is_error=tr.is_error,
            ))

    final_step = steps[-1]
    return GenerateResult(
        text=final_step.text,
        reasoning=final_step.reasoning,
        tool_calls=final_step.tool_calls,
        tool_results=final_step.tool_results,
        finish_reason=final_step.finish_reason,
        usage=final_step.usage,
        total_usage=total_usage,
        steps=steps,
        response=final_step.response,
    )
