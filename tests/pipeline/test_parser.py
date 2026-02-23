"""Tests for the DOT parser."""

import os

import pytest

from attractor.pipeline.parser import ParseError, parse_dot, parse_dot_file

FIXTURES = os.path.join(os.path.dirname(__file__), "..", "fixtures", "pipelines")


class TestParseDot:
    def test_simple_linear(self):
        graph = parse_dot_file(os.path.join(FIXTURES, "simple_linear.dot"))
        assert graph.name == "Simple"
        assert graph.goal == "Run tests and report"
        assert "start" in graph.nodes
        assert "exit" in graph.nodes
        assert "run_tests" in graph.nodes
        assert "report" in graph.nodes
        assert len(graph.edges) == 3

    def test_branching(self):
        graph = parse_dot_file(os.path.join(FIXTURES, "branching.dot"))
        assert graph.name == "Branch"
        assert len(graph.nodes) == 6  # start, exit, plan, implement, validate, gate
        assert graph.nodes["gate"].shape == "diamond"

        # Check edges with conditions
        gate_edges = graph.outgoing_edges("gate")
        assert len(gate_edges) == 2
        conditions = {e.to_node: e.condition for e in gate_edges}
        assert conditions["exit"] == "outcome=success"
        assert conditions["implement"] == "outcome!=success"

    def test_human_gate(self):
        graph = parse_dot_file(os.path.join(FIXTURES, "human_gate.dot"))
        assert "review_gate" in graph.nodes
        assert graph.nodes["review_gate"].shape == "hexagon"

        edges = graph.outgoing_edges("review_gate")
        assert len(edges) == 2
        labels = {e.to_node: e.label for e in edges}
        assert "[A] Approve" in labels.values()

    def test_node_shapes(self):
        graph = parse_dot('''
            digraph Test {
                start [shape=Mdiamond]
                exit [shape=Msquare]
                work [shape=box]
                start -> work -> exit
            }
        ''')
        assert graph.nodes["start"].shape == "Mdiamond"
        assert graph.nodes["exit"].shape == "Msquare"
        assert graph.nodes["work"].shape == "box"

    def test_graph_attributes(self):
        graph = parse_dot('''
            digraph Test {
                graph [goal="My Goal", default_max_retry=5]
                start [shape=Mdiamond]
                exit [shape=Msquare]
                start -> exit
            }
        ''')
        assert graph.attrs["goal"] == "My Goal"
        assert graph.attrs["default_max_retry"] == 5

    def test_edge_attributes(self):
        graph = parse_dot('''
            digraph Test {
                start [shape=Mdiamond]
                exit [shape=Msquare]
                start -> exit [label="done", weight=5]
            }
        ''')
        assert len(graph.edges) == 1
        assert graph.edges[0].label == "done"
        assert graph.edges[0].weight == 5

    def test_chained_edges(self):
        graph = parse_dot('''
            digraph Test {
                start [shape=Mdiamond]
                exit [shape=Msquare]
                a [label="A"]
                b [label="B"]
                start -> a -> b -> exit
            }
        ''')
        assert len(graph.edges) == 3

    def test_comments_stripped(self):
        graph = parse_dot('''
            // This is a comment
            digraph Test {
                /* Block comment */
                start [shape=Mdiamond]
                exit [shape=Msquare]
                start -> exit
            }
        ''')
        assert "start" in graph.nodes
        assert "exit" in graph.nodes

    def test_node_defaults(self):
        graph = parse_dot('''
            digraph Test {
                node [shape=box, timeout="900s"]
                start [shape=Mdiamond]
                exit [shape=Msquare]
                work [label="Work"]
                start -> work -> exit
            }
        ''')
        # 'work' should inherit box shape from defaults
        assert graph.nodes["work"].shape == "box"
        # start overrides the default
        assert graph.nodes["start"].shape == "Mdiamond"

    def test_subgraph(self):
        graph = parse_dot('''
            digraph Test {
                start [shape=Mdiamond]
                exit [shape=Msquare]

                subgraph cluster_loop {
                    node [timeout="900s"]
                    plan [label="Plan"]
                    implement [label="Implement"]
                }

                start -> plan -> implement -> exit
            }
        ''')
        assert "plan" in graph.nodes
        assert "implement" in graph.nodes

    def test_boolean_values(self):
        graph = parse_dot('''
            digraph Test {
                start [shape=Mdiamond]
                exit [shape=Msquare]
                work [goal_gate=true, allow_partial=false]
                start -> work -> exit
            }
        ''')
        assert graph.nodes["work"].goal_gate is True
        assert graph.nodes["work"].allow_partial is False

    def test_string_escapes(self):
        graph = parse_dot('''
            digraph Test {
                start [shape=Mdiamond]
                exit [shape=Msquare]
                work [prompt="Line1\\nLine2"]
                start -> work -> exit
            }
        ''')
        assert "Line1\nLine2" in graph.nodes["work"].prompt


class TestParseErrors:
    def test_missing_digraph(self):
        with pytest.raises(ParseError):
            parse_dot('graph Test { }')

    def test_unterminated_string(self):
        with pytest.raises(ParseError):
            parse_dot('digraph Test { start [label="unterminated] }')
