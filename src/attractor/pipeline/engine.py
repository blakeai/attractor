"""Pipeline execution engine — the core traversal and edge selection algorithm."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from attractor.pipeline.checkpoint import Checkpoint
from attractor.pipeline.conditions import evaluate_condition
from attractor.pipeline.context import Context
from attractor.pipeline.graph import Edge, Graph, Node
from attractor.pipeline.handlers.base import HandlerRegistry
from attractor.pipeline.handlers.core import (
    CodergenHandler,
    ConditionalHandler,
    ExitHandler,
    StartHandler,
    WaitForHumanHandler,
)
from attractor.pipeline.interviewer.auto import AutoApproveInterviewer
from attractor.pipeline.interviewer.base import Interviewer
from attractor.pipeline.outcome import Outcome, StageStatus
from attractor.pipeline.validator import validate_or_raise


class EngineError(Exception):
    pass


class Engine:
    def __init__(
        self,
        registry: HandlerRegistry | None = None,
        interviewer: Interviewer | None = None,
        logs_root: str = "./logs",
        codergen_backend: Any = None,
    ):
        self._interviewer = interviewer or AutoApproveInterviewer()
        self._logs_root = logs_root

        if registry:
            self._registry = registry
        else:
            self._registry = self._build_default_registry(codergen_backend)

    def _build_default_registry(self, codergen_backend: Any = None) -> HandlerRegistry:
        codergen = CodergenHandler(backend=codergen_backend)
        registry = HandlerRegistry(default_handler=codergen)
        registry.register("start", StartHandler())
        registry.register("exit", ExitHandler())
        registry.register("conditional", ConditionalHandler())
        registry.register("codergen", codergen)
        registry.register("wait.human", WaitForHumanHandler(self._interviewer))
        return registry

    async def run(
        self,
        graph: Graph,
        checkpoint: Checkpoint | None = None,
    ) -> Outcome:
        """Execute a pipeline graph from start to completion."""
        # Validate
        validate_or_raise(graph)

        # Initialize context
        context = Context()
        if checkpoint and checkpoint.context_values:
            context = Context(checkpoint.context_values)

        # Mirror graph attributes
        if graph.goal:
            context.set("graph.goal", graph.goal)
        for key, value in graph.attrs.items():
            context.set(f"graph.{key}", value)

        # Initialize state
        completed_nodes: list[str] = []
        node_outcomes: dict[str, Outcome] = {}
        node_retries: dict[str, int] = {}

        if checkpoint:
            completed_nodes = list(checkpoint.completed_nodes)
            node_retries = dict(checkpoint.node_retries)

        # Find start node
        start_node = graph.find_start_node()
        if not start_node:
            raise EngineError("No start node found")

        # Resume from checkpoint or start fresh
        if checkpoint and checkpoint.current_node:
            # Find the next node after the checkpoint's current node
            current_node = graph.nodes.get(checkpoint.current_node)
            if not current_node:
                raise EngineError(f"Checkpoint node '{checkpoint.current_node}' not found")
            # If we already completed this node, select next edge
            if checkpoint.current_node in completed_nodes:
                edges = graph.outgoing_edges(checkpoint.current_node)
                if edges:
                    current_node = graph.nodes.get(edges[0].to_node)
                else:
                    return Outcome(status=StageStatus.SUCCESS, notes="Pipeline resumed and complete")
        else:
            current_node = start_node

        last_outcome = Outcome(status=StageStatus.SUCCESS)

        # Create logs directory
        Path(self._logs_root).mkdir(parents=True, exist_ok=True)

        while True:
            node = current_node
            if node is None:
                break

            context.set("current_node", node.id)

            # Step 1: Check for terminal node
            if node.is_terminal():
                gate_ok, failed_gate = self._check_goal_gates(graph, node_outcomes)
                if not gate_ok and failed_gate:
                    retry_target = self._get_retry_target(failed_gate, graph)
                    if retry_target and retry_target in graph.nodes:
                        current_node = graph.nodes[retry_target]
                        continue
                    else:
                        raise EngineError(
                            f"Goal gate '{failed_gate.id}' unsatisfied and no retry target"
                        )
                # Execute exit handler
                handler = self._registry.resolve(node)
                last_outcome = await handler.execute(node, context, graph, self._logs_root)
                break

            # Step 2: Execute with retry
            handler = self._registry.resolve(node)
            max_attempts = node.max_retries + 1
            outcome = Outcome(status=StageStatus.FAIL, failure_reason="Not executed")

            for attempt in range(1, max_attempts + 1):
                try:
                    outcome = await handler.execute(node, context, graph, self._logs_root)
                except Exception as e:
                    outcome = Outcome(status=StageStatus.FAIL, failure_reason=str(e))

                if outcome.status in (StageStatus.SUCCESS, StageStatus.PARTIAL_SUCCESS):
                    node_retries.pop(node.id, None)
                    break
                elif outcome.status == StageStatus.RETRY:
                    if attempt < max_attempts:
                        node_retries[node.id] = node_retries.get(node.id, 0) + 1
                        continue
                    elif node.allow_partial:
                        outcome = Outcome(
                            status=StageStatus.PARTIAL_SUCCESS,
                            notes="Retries exhausted, partial accepted",
                        )
                        break
                    else:
                        outcome = Outcome(
                            status=StageStatus.FAIL, failure_reason="Max retries exceeded"
                        )
                        break
                elif outcome.status == StageStatus.FAIL:
                    break

            # Step 3: Record completion
            completed_nodes.append(node.id)
            node_outcomes[node.id] = outcome
            last_outcome = outcome

            # Step 4: Apply context updates
            if outcome.context_updates:
                context.apply_updates(outcome.context_updates)
            context.set("outcome", outcome.status.value)
            if outcome.preferred_label:
                context.set("preferred_label", outcome.preferred_label)

            # Step 5: Save checkpoint
            cp = Checkpoint(
                current_node=node.id,
                completed_nodes=list(completed_nodes),
                node_retries=dict(node_retries),
                context_values=context.snapshot(),
                logs=context.logs,
            )
            cp.save(str(Path(self._logs_root) / "checkpoint.json"))

            # Step 6: Select next edge
            next_edge = self._select_edge(node, outcome, context, graph)
            if next_edge is None:
                if outcome.status == StageStatus.FAIL:
                    raise EngineError(f"Stage '{node.id}' failed with no outgoing fail edge")
                break

            # Step 7: Handle loop_restart
            if next_edge.loop_restart:
                # For MVP, just advance to the target
                pass

            # Step 8: Advance
            current_node = graph.nodes.get(next_edge.to_node)
            if current_node is None:
                raise EngineError(f"Edge target '{next_edge.to_node}' not found in graph")

        return last_outcome

    def _select_edge(
        self, node: Node, outcome: Outcome, context: Context, graph: Graph
    ) -> Edge | None:
        """Edge selection algorithm — deterministic five-step priority order."""
        edges = graph.outgoing_edges(node.id)
        if not edges:
            return None

        # Step 1: Condition matching
        condition_matched = []
        for edge in edges:
            if edge.condition and evaluate_condition(edge.condition, outcome, context):
                condition_matched.append(edge)
        if condition_matched:
            return self._best_by_weight_then_lexical(condition_matched)

        # Step 2: Preferred label
        if outcome.preferred_label:
            norm_preferred = _normalize_label(outcome.preferred_label)
            for edge in edges:
                if _normalize_label(edge.label) == norm_preferred:
                    return edge

        # Step 3: Suggested next IDs
        if outcome.suggested_next_ids:
            for suggested_id in outcome.suggested_next_ids:
                for edge in edges:
                    if edge.to_node == suggested_id:
                        return edge

        # Step 4 & 5: Weight with lexical tiebreak (unconditional edges only)
        unconditional = [e for e in edges if not e.condition]
        if unconditional:
            return self._best_by_weight_then_lexical(unconditional)

        # Fallback: any edge
        return self._best_by_weight_then_lexical(edges)

    def _best_by_weight_then_lexical(self, edges: list[Edge]) -> Edge:
        return sorted(edges, key=lambda e: (-e.weight, e.to_node))[0]

    def _check_goal_gates(
        self, graph: Graph, node_outcomes: dict[str, Outcome]
    ) -> tuple[bool, Node | None]:
        for node_id, outcome in node_outcomes.items():
            node = graph.nodes.get(node_id)
            if node and node.goal_gate and outcome.status not in (StageStatus.SUCCESS, StageStatus.PARTIAL_SUCCESS):
                return False, node
        return True, None

    def _get_retry_target(self, node: Node, graph: Graph) -> str | None:
        if node.retry_target:
            return node.retry_target
        if node.fallback_retry_target:
            return node.fallback_retry_target
        # Graph-level fallback
        if graph.attrs.get("retry_target"):
            return str(graph.attrs["retry_target"])
        if graph.attrs.get("fallback_retry_target"):
            return str(graph.attrs["fallback_retry_target"])
        return None


def _normalize_label(label: str) -> str:
    """Normalize label for comparison: lowercase, trim, strip accelerator prefixes."""
    label = label.strip().lower()
    # Strip accelerator prefixes like [Y], Y), Y -
    label = re.sub(r"^\[\w\]\s*", "", label)
    label = re.sub(r"^\w\)\s*", "", label)
    label = re.sub(r"^\w\s*-\s*", "", label)
    return label
