"""Core agent tools — bridges LLM tool definitions to the execution environment."""

from __future__ import annotations

from attractor.agent.execution.base import ExecutionEnvironment
from attractor.llm.types import Tool


def make_read_file_tool(env: ExecutionEnvironment) -> Tool:
    async def execute(file_path: str, offset: int = 0, limit: int = 2000) -> str:
        return await env.read_file(file_path, offset=offset, limit=limit)

    return Tool(
        name="read_file",
        description="Read a file from the filesystem. Returns line-numbered content.",
        parameters={
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "Absolute path to the file"},
                "offset": {
                    "type": "integer",
                    "description": "1-based line number to start from",
                    "default": 0,
                },
                "limit": {
                    "type": "integer",
                    "description": "Max lines to read",
                    "default": 2000,
                },
            },
            "required": ["file_path"],
        },
        execute=execute,
    )


def make_write_file_tool(env: ExecutionEnvironment) -> Tool:
    async def execute(file_path: str, content: str) -> str:
        bytes_written = await env.write_file(file_path, content)
        return f"Wrote {bytes_written} bytes to {file_path}"

    return Tool(
        name="write_file",
        description="Write content to a file. Creates the file and parent directories if needed.",
        parameters={
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "Absolute path"},
                "content": {"type": "string", "description": "The full file content"},
            },
            "required": ["file_path", "content"],
        },
        execute=execute,
    )


def make_edit_file_tool(env: ExecutionEnvironment) -> Tool:
    async def execute(
        file_path: str,
        old_string: str,
        new_string: str,
        replace_all: bool = False,
    ) -> str:
        count = await env.edit_file(file_path, old_string, new_string, replace_all=replace_all)
        return f"Replaced {count} occurrence(s) in {file_path}"

    return Tool(
        name="edit_file",
        description="Replace an exact string occurrence in a file.",
        parameters={
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "Absolute path"},
                "old_string": {"type": "string", "description": "Exact text to find"},
                "new_string": {"type": "string", "description": "Replacement text"},
                "replace_all": {
                    "type": "boolean",
                    "description": "Replace all occurrences",
                    "default": False,
                },
            },
            "required": ["file_path", "old_string", "new_string"],
        },
        execute=execute,
    )


def make_shell_tool(env: ExecutionEnvironment, default_timeout_ms: int = 10000) -> Tool:
    async def execute(command: str, timeout_ms: int | None = None) -> str:
        timeout = timeout_ms or default_timeout_ms
        result = await env.shell(command, timeout_ms=timeout)
        output = result.stdout
        if result.stderr:
            output += f"\nSTDERR:\n{result.stderr}"
        if result.timed_out:
            output += f"\n[Timed out after {timeout}ms]"
        output += f"\n[exit code: {result.exit_code}]"
        return output

    return Tool(
        name="shell",
        description="Execute a shell command. Returns stdout, stderr, and exit code.",
        parameters={
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "The command to run"},
                "timeout_ms": {
                    "type": "integer",
                    "description": "Override default timeout in milliseconds",
                },
            },
            "required": ["command"],
        },
        execute=execute,
    )


def make_grep_tool(env: ExecutionEnvironment) -> Tool:
    async def execute(
        pattern: str,
        path: str | None = None,
        glob_filter: str | None = None,
        case_insensitive: bool = False,
        max_results: int = 100,
    ) -> str:
        return await env.grep(
            pattern,
            path=path,
            glob_filter=glob_filter,
            case_insensitive=case_insensitive,
            max_results=max_results,
        )

    return Tool(
        name="grep",
        description="Search file contents using regex patterns.",
        parameters={
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Regex pattern"},
                "path": {"type": "string", "description": "Directory or file to search"},
                "glob_filter": {"type": "string", "description": "File pattern filter (e.g. *.py)"},
                "case_insensitive": {"type": "boolean", "default": False},
                "max_results": {"type": "integer", "default": 100},
            },
            "required": ["pattern"],
        },
        execute=execute,
    )


def make_glob_tool(env: ExecutionEnvironment) -> Tool:
    async def execute(pattern: str, path: str | None = None) -> str:
        matches = await env.glob(pattern, path=path)
        return "\n".join(matches) if matches else "No files found"

    return Tool(
        name="glob",
        description="Find files matching a glob pattern.",
        parameters={
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Glob pattern (e.g. **/*.py)"},
                "path": {"type": "string", "description": "Base directory"},
            },
            "required": ["pattern"],
        },
        execute=execute,
    )


def make_all_tools(env: ExecutionEnvironment, default_timeout_ms: int = 10000) -> list[Tool]:
    return [
        make_read_file_tool(env),
        make_write_file_tool(env),
        make_edit_file_tool(env),
        make_shell_tool(env, default_timeout_ms),
        make_grep_tool(env),
        make_glob_tool(env),
    ]
