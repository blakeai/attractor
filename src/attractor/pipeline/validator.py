"""Pipeline validation — lint rules from spec Section 7.2."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from enum import StrEnum

from attractor.pipeline.graph import Graph


class Severity(StrEnum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


@dataclass
class Diagnostic:
    rule: str
    severity: Severity
    message: str
    node_id: str = ""
    edge: tuple[str, str] | None = None
    fix: str = ""


class ValidationError(Exception):
    def __init__(self, diagnostics: list[Diagnostic]):
        self.diagnostics = diagnostics
        messages = [d.message for d in diagnostics]
        super().__init__(f"Validation failed: {'; '.join(messages)}")


def validate(graph: Graph) -> list[Diagnostic]:
    """Run all built-in lint rules and return diagnostics."""
    diagnostics: list[Diagnostic] = []

    # Rule: start_node — exactly one start node
    start_nodes = [n for n in graph.nodes.values() if n.shape == "Mdiamond"]
    if not start_nodes:
        # Check for id-based fallback
        for n in graph.nodes.values():
            if n.id.lower() == "start":
                start_nodes = [n]
                break
    if len(start_nodes) == 0:
        diagnostics.append(Diagnostic(
            rule="start_node",
            severity=Severity.ERROR,
            message="Pipeline must have exactly one start node (shape=Mdiamond)",
            fix="Add a node with shape=Mdiamond",
        ))
    elif len(start_nodes) > 1:
        diagnostics.append(Diagnostic(
            rule="start_node",
            severity=Severity.ERROR,
            message=f"Pipeline has {len(start_nodes)} start nodes, expected exactly 1",
        ))

    # Rule: terminal_node — at least one exit node
    exit_nodes = [n for n in graph.nodes.values() if n.shape == "Msquare"]
    if not exit_nodes:
        for n in graph.nodes.values():
            if n.id.lower() in ("exit", "end"):
                exit_nodes = [n]
                break
    if not exit_nodes:
        diagnostics.append(Diagnostic(
            rule="terminal_node",
            severity=Severity.ERROR,
            message="Pipeline must have at least one terminal node (shape=Msquare)",
            fix="Add a node with shape=Msquare",
        ))

    # Rule: edge_target_exists
    node_ids = set(graph.nodes.keys())
    for edge in graph.edges:
        if edge.from_node not in node_ids:
            diagnostics.append(Diagnostic(
                rule="edge_target_exists",
                severity=Severity.ERROR,
                message=f"Edge source '{edge.from_node}' does not exist",
                edge=(edge.from_node, edge.to_node),
            ))
        if edge.to_node not in node_ids:
            diagnostics.append(Diagnostic(
                rule="edge_target_exists",
                severity=Severity.ERROR,
                message=f"Edge target '{edge.to_node}' does not exist",
                edge=(edge.from_node, edge.to_node),
            ))

    # Rule: start_no_incoming
    if start_nodes:
        start_id = start_nodes[0].id
        incoming = [e for e in graph.edges if e.to_node == start_id]
        if incoming:
            diagnostics.append(Diagnostic(
                rule="start_no_incoming",
                severity=Severity.ERROR,
                message=f"Start node '{start_id}' has incoming edges",
                node_id=start_id,
            ))

    # Rule: exit_no_outgoing
    if exit_nodes:
        exit_id = exit_nodes[0].id
        outgoing = [e for e in graph.edges if e.from_node == exit_id]
        if outgoing:
            diagnostics.append(Diagnostic(
                rule="exit_no_outgoing",
                severity=Severity.ERROR,
                message=f"Exit node '{exit_id}' has outgoing edges",
                node_id=exit_id,
            ))

    # Rule: reachability
    if start_nodes:
        reachable = _bfs_reachable(graph, start_nodes[0].id)
        for node_id in graph.nodes:
            if node_id not in reachable:
                diagnostics.append(Diagnostic(
                    rule="reachability",
                    severity=Severity.ERROR,
                    message=f"Node '{node_id}' is not reachable from start",
                    node_id=node_id,
                ))

    # Rule: retry_target_exists (WARNING)
    for node in graph.nodes.values():
        if node.retry_target and node.retry_target not in node_ids:
            diagnostics.append(Diagnostic(
                rule="retry_target_exists",
                severity=Severity.WARNING,
                message=f"Node '{node.id}' has retry_target '{node.retry_target}' which doesn't exist",
                node_id=node.id,
            ))

    # Rule: prompt_on_llm_nodes (WARNING)
    for node in graph.nodes.values():
        if node.handler_type == "codergen" and not node.prompt and node.label == node.id:
                diagnostics.append(Diagnostic(
                    rule="prompt_on_llm_nodes",
                    severity=Severity.WARNING,
                    message=f"LLM node '{node.id}' has no prompt or label",
                    node_id=node.id,
                    fix="Add a prompt or label attribute",
                ))

    return diagnostics


def validate_or_raise(graph: Graph) -> list[Diagnostic]:
    """Validate and raise if there are errors."""
    diagnostics = validate(graph)
    errors = [d for d in diagnostics if d.severity == Severity.ERROR]
    if errors:
        raise ValidationError(errors)
    return diagnostics


def _bfs_reachable(graph: Graph, start_id: str) -> set[str]:
    """BFS from start to find all reachable nodes."""
    visited: set[str] = set()
    queue = deque([start_id])
    while queue:
        node_id = queue.popleft()
        if node_id in visited:
            continue
        visited.add(node_id)
        for edge in graph.outgoing_edges(node_id):
            if edge.to_node not in visited:
                queue.append(edge.to_node)
    return visited
