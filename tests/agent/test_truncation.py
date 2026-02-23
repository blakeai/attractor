"""Tests for tool output truncation."""

from attractor.agent.truncation import truncate_tool_output


class TestTruncation:
    def test_short_output_unchanged(self):
        result = truncate_tool_output("hello", "read_file")
        assert result == "hello"

    def test_long_output_truncated(self):
        output = "x" * 200_000
        result = truncate_tool_output(output, "read_file")
        assert len(result) < len(output)
        assert "truncated" in result

    def test_custom_limits(self):
        output = "x" * 1000
        result = truncate_tool_output(output, "custom_tool", limits={"custom_tool": 500})
        assert len(result) < len(output)
        assert "truncated" in result

    def test_head_tail_preserved(self):
        lines = [f"line {i}" for i in range(10000)]
        output = "\n".join(lines)
        result = truncate_tool_output(output, "shell", limits={"shell": 1000})
        assert result.startswith("line 0")
        assert "line 9999" in result
