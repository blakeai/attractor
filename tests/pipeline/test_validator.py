"""Tests for pipeline validation."""

import pytest

from attractor.pipeline.parser import parse_dot
from attractor.pipeline.validator import Severity, ValidationError, validate, validate_or_raise


class TestValidator:
    def test_valid_pipeline(self):
        graph = parse_dot('''
            digraph Test {
                start [shape=Mdiamond]
                exit [shape=Msquare]
                work [label="Work"]
                start -> work -> exit
            }
        ''')
        diagnostics = validate(graph)
        errors = [d for d in diagnostics if d.severity == Severity.ERROR]
        assert len(errors) == 0

    def test_no_start_node(self):
        graph = parse_dot('''
            digraph Test {
                exit [shape=Msquare]
                work [label="Work"]
                work -> exit
            }
        ''')
        diagnostics = validate(graph)
        errors = [d for d in diagnostics if d.rule == "start_node"]
        assert len(errors) >= 1

    def test_no_exit_node(self):
        graph = parse_dot('''
            digraph Test {
                start [shape=Mdiamond]
                work [label="Work"]
                start -> work
            }
        ''')
        diagnostics = validate(graph)
        errors = [d for d in diagnostics if d.rule == "terminal_node"]
        assert len(errors) >= 1

    def test_unreachable_node(self):
        graph = parse_dot('''
            digraph Test {
                start [shape=Mdiamond]
                exit [shape=Msquare]
                work [label="Work"]
                orphan [label="Orphan"]
                start -> work -> exit
            }
        ''')
        diagnostics = validate(graph)
        reachability = [d for d in diagnostics if d.rule == "reachability"]
        assert len(reachability) >= 1
        assert any("orphan" in d.node_id for d in reachability)

    def test_start_has_incoming_edges(self):
        graph = parse_dot('''
            digraph Test {
                start [shape=Mdiamond]
                exit [shape=Msquare]
                work [label="Work"]
                start -> work -> exit
                work -> start
            }
        ''')
        diagnostics = validate(graph)
        errors = [d for d in diagnostics if d.rule == "start_no_incoming"]
        assert len(errors) >= 1

    def test_validate_or_raise(self):
        graph = parse_dot('''
            digraph Test {
                work [label="Work"]
            }
        ''')
        with pytest.raises(ValidationError):
            validate_or_raise(graph)

    def test_prompt_warning(self):
        graph = parse_dot('''
            digraph Test {
                start [shape=Mdiamond]
                exit [shape=Msquare]
                no_prompt_node [shape=box]
                start -> no_prompt_node -> exit
            }
        ''')
        diagnostics = validate(graph)
        warnings = [d for d in diagnostics if d.rule == "prompt_on_llm_nodes"]
        assert len(warnings) >= 1
