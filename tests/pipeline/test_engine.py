"""Tests for the pipeline execution engine."""

import os
import tempfile

import pytest

from attractor.pipeline.context import Context
from attractor.pipeline.engine import Engine, EngineError
from attractor.pipeline.interviewer.auto import AutoApproveInterviewer
from attractor.pipeline.interviewer.base import Answer
from attractor.pipeline.interviewer.queue import QueueInterviewer
from attractor.pipeline.outcome import Outcome, StageStatus
from attractor.pipeline.parser import parse_dot, parse_dot_file

FIXTURES = os.path.join(os.path.dirname(__file__), "..", "fixtures", "pipelines")


class TestEngineLinear:
    @pytest.mark.asyncio
    async def test_simple_linear_pipeline(self):
        graph = parse_dot_file(os.path.join(FIXTURES, "simple_linear.dot"))
        with tempfile.TemporaryDirectory() as logs:
            engine = Engine(logs_root=logs)
            outcome = await engine.run(graph)
            assert outcome.status == StageStatus.SUCCESS

            # Check that stage directories were created
            assert os.path.exists(os.path.join(logs, "run_tests", "prompt.md"))
            assert os.path.exists(os.path.join(logs, "run_tests", "response.md"))
            assert os.path.exists(os.path.join(logs, "report", "prompt.md"))
            assert os.path.exists(os.path.join(logs, "checkpoint.json"))

    @pytest.mark.asyncio
    async def test_variable_expansion(self):
        graph = parse_dot('''
            digraph Test {
                graph [goal="Fix the bug"]
                start [shape=Mdiamond]
                exit [shape=Msquare]
                work [label="Work", prompt="Goal is: $goal"]
                start -> work -> exit
            }
        ''')
        with tempfile.TemporaryDirectory() as logs:
            engine = Engine(logs_root=logs)
            await engine.run(graph)

            with open(os.path.join(logs, "work", "prompt.md")) as f:
                prompt = f.read()
            assert "Fix the bug" in prompt


class TestEngineConditional:
    @pytest.mark.asyncio
    async def test_conditional_routing(self):
        graph = parse_dot('''
            digraph Test {
                start [shape=Mdiamond]
                exit [shape=Msquare]
                work [label="Work", prompt="Do something"]
                gate [shape=diamond, label="Check"]
                done [label="Done", prompt="Finish up"]

                start -> work -> gate
                gate -> done [condition="outcome=success"]
                gate -> exit [condition="outcome!=success"]
                done -> exit
            }
        ''')
        with tempfile.TemporaryDirectory() as logs:
            engine = Engine(logs_root=logs)
            outcome = await engine.run(graph)
            assert outcome.status == StageStatus.SUCCESS


class TestEngineEdgeSelection:
    @pytest.mark.asyncio
    async def test_weight_based_selection(self):
        graph = parse_dot('''
            digraph Test {
                start [shape=Mdiamond]
                exit [shape=Msquare]
                a [label="A", prompt="Path A"]
                b [label="B", prompt="Path B"]
                start -> a [weight=10]
                start -> b [weight=1]
                a -> exit
                b -> exit
            }
        ''')
        with tempfile.TemporaryDirectory() as logs:
            engine = Engine(logs_root=logs)
            outcome = await engine.run(graph)
            assert outcome.status == StageStatus.SUCCESS
            # Should have taken path A (higher weight)
            assert os.path.exists(os.path.join(logs, "a", "prompt.md"))


class TestEngineHumanGate:
    @pytest.mark.asyncio
    async def test_auto_approve(self):
        graph = parse_dot_file(os.path.join(FIXTURES, "human_gate.dot"))
        with tempfile.TemporaryDirectory() as logs:
            engine = Engine(
                logs_root=logs,
                interviewer=AutoApproveInterviewer(),
            )
            outcome = await engine.run(graph)
            assert outcome.status == StageStatus.SUCCESS

    @pytest.mark.asyncio
    async def test_queue_interviewer(self):
        graph = parse_dot_file(os.path.join(FIXTURES, "human_gate.dot"))
        queue = QueueInterviewer([Answer(value="A")])

        with tempfile.TemporaryDirectory() as logs:
            engine = Engine(logs_root=logs, interviewer=queue)
            outcome = await engine.run(graph)
            assert outcome.status == StageStatus.SUCCESS


class TestCheckpoint:
    @pytest.mark.asyncio
    async def test_checkpoint_created(self):
        graph = parse_dot('''
            digraph Test {
                start [shape=Mdiamond]
                exit [shape=Msquare]
                work [label="Work", prompt="Do work"]
                start -> work -> exit
            }
        ''')
        with tempfile.TemporaryDirectory() as logs:
            engine = Engine(logs_root=logs)
            await engine.run(graph)

            import json
            cp_path = os.path.join(logs, "checkpoint.json")
            assert os.path.exists(cp_path)
            with open(cp_path) as f:
                data = json.loads(f.read())
            assert "completed_nodes" in data
            assert "work" in data["completed_nodes"]


class TestConditionEvaluator:
    def test_simple_equality(self):
        from attractor.pipeline.conditions import evaluate_condition

        outcome = Outcome(status=StageStatus.SUCCESS)
        context = Context()
        assert evaluate_condition("outcome=success", outcome, context) is True
        assert evaluate_condition("outcome=fail", outcome, context) is False

    def test_inequality(self):
        from attractor.pipeline.conditions import evaluate_condition

        outcome = Outcome(status=StageStatus.SUCCESS)
        context = Context()
        assert evaluate_condition("outcome!=fail", outcome, context) is True
        assert evaluate_condition("outcome!=success", outcome, context) is False

    def test_context_variable(self):
        from attractor.pipeline.conditions import evaluate_condition

        outcome = Outcome(status=StageStatus.SUCCESS)
        context = Context({"last_stage": "validate"})
        assert evaluate_condition("last_stage=validate", outcome, context) is True

    def test_and_condition(self):
        from attractor.pipeline.conditions import evaluate_condition

        outcome = Outcome(status=StageStatus.SUCCESS)
        context = Context({"last_stage": "validate"})
        assert (
            evaluate_condition("outcome=success AND last_stage=validate", outcome, context) is True
        )
        assert (
            evaluate_condition("outcome=fail AND last_stage=validate", outcome, context) is False
        )


class TestVariableExpansion:
    @pytest.mark.asyncio
    async def test_expand_repo_variable(self):
        graph = parse_dot('''
            digraph Test {
                graph [goal="Fix bug", repo="/tmp/my-repo"]
                start [shape=Mdiamond]
                exit [shape=Msquare]
                work [label="Work", prompt="Repo is: $repo"]
                start -> work -> exit
            }
        ''')
        with tempfile.TemporaryDirectory() as logs:
            engine = Engine(logs_root=logs)
            await engine.run(graph)

            with open(os.path.join(logs, "work", "prompt.md")) as f:
                prompt = f.read()
            assert "/tmp/my-repo" in prompt

    @pytest.mark.asyncio
    async def test_expand_custom_variable(self):
        graph = parse_dot('''
            digraph Test {
                graph [goal="Fix bug", author="Alice"]
                start [shape=Mdiamond]
                exit [shape=Msquare]
                work [label="Work", prompt="Author: $author, Goal: $goal"]
                start -> work -> exit
            }
        ''')
        with tempfile.TemporaryDirectory() as logs:
            engine = Engine(logs_root=logs)
            await engine.run(graph)

            with open(os.path.join(logs, "work", "prompt.md")) as f:
                prompt = f.read()
            assert "Alice" in prompt
            assert "Fix bug" in prompt

    @pytest.mark.asyncio
    async def test_unknown_variable_left_as_is(self):
        graph = parse_dot('''
            digraph Test {
                graph [goal="Fix bug"]
                start [shape=Mdiamond]
                exit [shape=Msquare]
                work [label="Work", prompt="Unknown: $nope"]
                start -> work -> exit
            }
        ''')
        with tempfile.TemporaryDirectory() as logs:
            engine = Engine(logs_root=logs)
            await engine.run(graph)

            with open(os.path.join(logs, "work", "prompt.md")) as f:
                prompt = f.read()
            assert "$nope" in prompt


class TestMaxSteps:
    @pytest.mark.asyncio
    async def test_max_steps_stops_engine(self):
        """Engine should raise EngineError when max_steps is exceeded."""
        graph = parse_dot('''
            digraph Test {
                graph [goal="Loop forever"]
                start [shape=Mdiamond]
                exit [shape=Msquare]
                a [label="A", prompt="Do A"]
                b [label="B", prompt="Do B"]
                start -> a -> b -> a
                b -> exit [condition="outcome=fail"]
            }
        ''')
        with tempfile.TemporaryDirectory() as logs:
            engine = Engine(logs_root=logs, max_steps=2)
            with pytest.raises(EngineError, match="max steps"):
                await engine.run(graph)

    @pytest.mark.asyncio
    async def test_max_steps_default_allows_normal_pipeline(self):
        """Normal pipelines should complete fine with the default max_steps."""
        graph = parse_dot('''
            digraph Test {
                start [shape=Mdiamond]
                exit [shape=Msquare]
                work [label="Work", prompt="Do work"]
                start -> work -> exit
            }
        ''')
        with tempfile.TemporaryDirectory() as logs:
            engine = Engine(logs_root=logs)
            outcome = await engine.run(graph)
            assert outcome.status == StageStatus.SUCCESS


class TestConfigLoading:
    def test_load_config_file(self):
        import json
        from attractor.cli import _load_run_config

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({"goal": "add CSV export", "repo": "/tmp/repo", "max_steps": 50}, f)
            f.flush()

            config = _load_run_config(f.name)
            assert config["goal"] == "add CSV export"
            assert config["repo"] == "/tmp/repo"
            assert config["max_steps"] == 50

        os.unlink(f.name)

    def test_flags_override_config(self):
        import json
        from attractor.cli import _merge_run_config

        config = {"goal": "from config", "repo": "/config/repo", "max_steps": 50}
        flags = {"goal": "from flag", "repo": None, "max_steps": None}

        merged = _merge_run_config(config, flags)
        assert merged["goal"] == "from flag"
        assert merged["repo"] == "/config/repo"
        assert merged["max_steps"] == 50

    def test_config_overrides_dot_attrs(self):
        from attractor.cli import _apply_config_to_graph

        graph = parse_dot('''
            digraph Test {
                graph [goal="from DOT"]
                start [shape=Mdiamond]
                exit [shape=Msquare]
                start -> exit
            }
        ''')
        config = {"goal": "from config", "repo": "/tmp/repo"}
        _apply_config_to_graph(graph, config)

        assert graph.attrs["goal"] == "from config"
        assert graph.attrs["repo"] == "/tmp/repo"

    def test_empty_config_preserves_dot_attrs(self):
        from attractor.cli import _apply_config_to_graph

        graph = parse_dot('''
            digraph Test {
                graph [goal="from DOT"]
                start [shape=Mdiamond]
                exit [shape=Msquare]
                start -> exit
            }
        ''')
        config: dict = {}
        _apply_config_to_graph(graph, config)

        assert graph.attrs["goal"] == "from DOT"


class TestAttractorConfigDiscovery:
    def test_discover_config_from_repo_path(self):
        import json
        from attractor.cli import _discover_repo_config

        with tempfile.TemporaryDirectory() as repo:
            attractor_dir = os.path.join(repo, ".attractor")
            os.makedirs(attractor_dir)
            config_path = os.path.join(attractor_dir, "config.json")
            with open(config_path, "w") as f:
                json.dump({"max_steps": 50, "auto_approve": True}, f)

            config = _discover_repo_config(repo)
            assert config["max_steps"] == 50
            assert config["auto_approve"] is True

    def test_discover_config_missing_dir_returns_empty(self):
        from attractor.cli import _discover_repo_config

        with tempfile.TemporaryDirectory() as repo:
            config = _discover_repo_config(repo)
            assert config == {}

    def test_discover_config_missing_file_returns_empty(self):
        from attractor.cli import _discover_repo_config

        with tempfile.TemporaryDirectory() as repo:
            os.makedirs(os.path.join(repo, ".attractor"))
            config = _discover_repo_config(repo)
            assert config == {}

    def test_three_tier_precedence(self):
        """Precedence: .attractor/config.json < --config < CLI flags."""
        import json
        from attractor.cli import _discover_repo_config, _merge_run_config

        with tempfile.TemporaryDirectory() as repo:
            # .attractor/config.json — lowest priority
            attractor_dir = os.path.join(repo, ".attractor")
            os.makedirs(attractor_dir)
            with open(os.path.join(attractor_dir, "config.json"), "w") as f:
                json.dump({"max_steps": 50, "auto_approve": True, "logs": "./logs/repo"}, f)

            repo_config = _discover_repo_config(repo)

            # --config file — middle priority
            explicit_config = {"max_steps": 75, "logs": "./logs/explicit"}

            # CLI flags — highest priority
            flags = {"max_steps": 200, "logs": None}

            # Merge: repo < explicit < flags
            merged = _merge_run_config(repo_config, explicit_config)
            merged = _merge_run_config(merged, flags)

            assert merged["max_steps"] == 200  # from flags
            assert merged["logs"] == "./logs/explicit"  # from explicit (flag was None)
            assert merged["auto_approve"] is True  # from repo config (not overridden)

    def test_discover_config_from_cwd_when_no_repo(self):
        """When no --repo, discover from CWD."""
        import json
        from attractor.cli import _discover_repo_config

        with tempfile.TemporaryDirectory() as cwd:
            attractor_dir = os.path.join(cwd, ".attractor")
            os.makedirs(attractor_dir)
            with open(os.path.join(attractor_dir, "config.json"), "w") as f:
                json.dump({"max_steps": 42}, f)

            # CWD is just another path — same function works
            config = _discover_repo_config(cwd)
            assert config["max_steps"] == 42
