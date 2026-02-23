"""Tests for the local execution environment."""

import os
import tempfile

import pytest

from attractor.agent.execution.local import LocalExecutionEnvironment


@pytest.fixture
def tmp_dir():
    with tempfile.TemporaryDirectory() as d:
        yield d


@pytest.fixture
def env(tmp_dir):
    return LocalExecutionEnvironment(working_dir=tmp_dir)


class TestReadFile:
    @pytest.mark.asyncio
    async def test_read_simple_file(self, env, tmp_dir):
        path = os.path.join(tmp_dir, "test.txt")
        with open(path, "w") as f:
            f.write("line1\nline2\nline3\n")

        result = await env.read_file(path)
        assert "   1 | line1" in result
        assert "   2 | line2" in result
        assert "   3 | line3" in result

    @pytest.mark.asyncio
    async def test_read_with_offset(self, env, tmp_dir):
        path = os.path.join(tmp_dir, "test.txt")
        with open(path, "w") as f:
            f.write("line1\nline2\nline3\nline4\n")

        result = await env.read_file(path, offset=1, limit=2)
        assert "   2 | line2" in result
        assert "   3 | line3" in result
        assert "line1" not in result
        assert "line4" not in result

    @pytest.mark.asyncio
    async def test_read_nonexistent_file(self, env):
        with pytest.raises(FileNotFoundError):
            await env.read_file("/nonexistent/file.txt")


class TestWriteFile:
    @pytest.mark.asyncio
    async def test_write_new_file(self, env, tmp_dir):
        path = os.path.join(tmp_dir, "new.txt")
        bytes_written = await env.write_file(path, "hello world")
        assert bytes_written == 11
        assert os.path.exists(path)
        with open(path) as f:
            assert f.read() == "hello world"

    @pytest.mark.asyncio
    async def test_write_creates_dirs(self, env, tmp_dir):
        path = os.path.join(tmp_dir, "sub", "dir", "file.txt")
        await env.write_file(path, "content")
        assert os.path.exists(path)


class TestEditFile:
    @pytest.mark.asyncio
    async def test_edit_single_occurrence(self, env, tmp_dir):
        path = os.path.join(tmp_dir, "test.txt")
        with open(path, "w") as f:
            f.write("hello world")

        count = await env.edit_file(path, "world", "there")
        assert count == 1
        with open(path) as f:
            assert f.read() == "hello there"

    @pytest.mark.asyncio
    async def test_edit_not_found(self, env, tmp_dir):
        path = os.path.join(tmp_dir, "test.txt")
        with open(path, "w") as f:
            f.write("hello world")

        with pytest.raises(ValueError, match="not found"):
            await env.edit_file(path, "xyz", "abc")

    @pytest.mark.asyncio
    async def test_edit_multiple_without_replace_all(self, env, tmp_dir):
        path = os.path.join(tmp_dir, "test.txt")
        with open(path, "w") as f:
            f.write("aaa bbb aaa")

        with pytest.raises(ValueError, match="2 times"):
            await env.edit_file(path, "aaa", "ccc")

    @pytest.mark.asyncio
    async def test_edit_replace_all(self, env, tmp_dir):
        path = os.path.join(tmp_dir, "test.txt")
        with open(path, "w") as f:
            f.write("aaa bbb aaa")

        count = await env.edit_file(path, "aaa", "ccc", replace_all=True)
        assert count == 2
        with open(path) as f:
            assert f.read() == "ccc bbb ccc"


class TestShell:
    @pytest.mark.asyncio
    async def test_simple_command(self, env):
        result = await env.shell("echo hello")
        assert result.stdout.strip() == "hello"
        assert result.exit_code == 0

    @pytest.mark.asyncio
    async def test_exit_code(self, env):
        result = await env.shell("exit 42")
        assert result.exit_code == 42

    @pytest.mark.asyncio
    async def test_timeout(self, env):
        result = await env.shell("sleep 10", timeout_ms=100)
        assert result.timed_out is True


class TestGlob:
    @pytest.mark.asyncio
    async def test_find_files(self, env, tmp_dir):
        for name in ["a.py", "b.py", "c.txt"]:
            with open(os.path.join(tmp_dir, name), "w") as f:
                f.write("x")

        matches = await env.glob("*.py")
        assert len(matches) == 2
        assert all(m.endswith(".py") for m in matches)


class TestGrep:
    @pytest.mark.asyncio
    async def test_search_pattern(self, env, tmp_dir):
        path = os.path.join(tmp_dir, "test.py")
        with open(path, "w") as f:
            f.write("def hello():\n    pass\ndef goodbye():\n    pass\n")

        result = await env.grep("def .*\\(\\)")
        assert "hello" in result
        assert "goodbye" in result

    @pytest.mark.asyncio
    async def test_case_insensitive(self, env, tmp_dir):
        path = os.path.join(tmp_dir, "test.txt")
        with open(path, "w") as f:
            f.write("Hello\nhello\nHELLO\n")

        result = await env.grep("hello", case_insensitive=True)
        lines = result.strip().split("\n")
        assert len(lines) == 3
