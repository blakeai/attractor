"""Tests for the pipeline execution engine."""

import os
import tempfile

import pytest

from attractor.pipeline.context import Context
from attractor.pipeline.engine import Engine
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
