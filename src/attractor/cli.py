"""Attractor CLI — run and validate DOT pipelines."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from attractor.pipeline.engine import Engine, EngineError
from attractor.pipeline.interviewer.auto import AutoApproveInterviewer
from attractor.pipeline.interviewer.console import ConsoleInterviewer
from attractor.pipeline.outcome import StageStatus
from attractor.pipeline.parser import ParseError, parse_dot_file
from attractor.pipeline.validator import Severity, validate


def cmd_run(args: argparse.Namespace) -> int:
    """Run a pipeline from a DOT file."""
    dot_path = args.pipeline
    if not Path(dot_path).exists():
        print(f"Error: File not found: {dot_path}", file=sys.stderr)
        return 1

    try:
        graph = parse_dot_file(dot_path)
    except ParseError as e:
        print(f"Parse error: {e}", file=sys.stderr)
        return 1

    interviewer = AutoApproveInterviewer() if args.auto_approve else ConsoleInterviewer()

    logs_root = args.logs or f"./logs/{Path(dot_path).stem}"

    engine = Engine(
        interviewer=interviewer,
        logs_root=logs_root,
    )

    print(f"Running pipeline: {graph.name or dot_path}")
    if graph.goal:
        print(f"Goal: {graph.goal}")
    print(f"Logs: {logs_root}")
    print()

    try:
        outcome = asyncio.run(engine.run(graph))
    except EngineError as e:
        print(f"\nPipeline error: {e}", file=sys.stderr)
        return 1

    status_icon = {
        StageStatus.SUCCESS: "[OK]",
        StageStatus.PARTIAL_SUCCESS: "[PARTIAL]",
        StageStatus.FAIL: "[FAIL]",
    }.get(outcome.status, f"[{outcome.status.value.upper()}]")

    print(f"\nPipeline complete: {status_icon} {outcome.notes}")
    if outcome.failure_reason:
        print(f"Failure: {outcome.failure_reason}", file=sys.stderr)

    return 0 if outcome.status in (StageStatus.SUCCESS, StageStatus.PARTIAL_SUCCESS) else 1


def cmd_validate(args: argparse.Namespace) -> int:
    """Validate a DOT pipeline file."""
    dot_path = args.pipeline
    if not Path(dot_path).exists():
        print(f"Error: File not found: {dot_path}", file=sys.stderr)
        return 1

    try:
        graph = parse_dot_file(dot_path)
    except ParseError as e:
        print(f"Parse error: {e}", file=sys.stderr)
        return 1

    diagnostics = validate(graph)

    if not diagnostics:
        print(f"Valid: {dot_path} ({len(graph.nodes)} nodes, {len(graph.edges)} edges)")
        return 0

    errors = [d for d in diagnostics if d.severity == Severity.ERROR]
    warnings = [d for d in diagnostics if d.severity == Severity.WARNING]

    for d in diagnostics:
        icon = {"error": "ERROR", "warning": "WARN", "info": "INFO"}[d.severity.value]
        node_info = f" ({d.node_id})" if d.node_id else ""
        print(f"  [{icon}] {d.rule}{node_info}: {d.message}")
        if d.fix:
            print(f"         Fix: {d.fix}")

    print()
    print(
        f"Summary: {len(errors)} error(s), {len(warnings)} warning(s) "
        f"in {dot_path} ({len(graph.nodes)} nodes, {len(graph.edges)} edges)"
    )

    return 1 if errors else 0


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="attractor",
        description="Attractor — DOT-based pipeline engine for AI workflows",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Run command
    run_parser = subparsers.add_parser("run", help="Run a pipeline")
    run_parser.add_argument("pipeline", help="Path to the .dot pipeline file")
    run_parser.add_argument(
        "--auto-approve",
        action="store_true",
        help="Auto-approve all human gates",
    )
    run_parser.add_argument(
        "--logs",
        help="Directory for logs and checkpoints (default: ./logs/<pipeline>)",
    )

    # Validate command
    validate_parser = subparsers.add_parser("validate", help="Validate a pipeline")
    validate_parser.add_argument("pipeline", help="Path to the .dot pipeline file")

    args = parser.parse_args()

    if args.command == "run":
        sys.exit(cmd_run(args))
    elif args.command == "validate":
        sys.exit(cmd_validate(args))


if __name__ == "__main__":
    main()
