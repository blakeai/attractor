"""Attractor CLI — run and validate DOT pipelines."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from attractor.pipeline.engine import Engine, EngineError
from attractor.pipeline.graph import Graph
from attractor.pipeline.interviewer.auto import AutoApproveInterviewer
from attractor.pipeline.interviewer.console import ConsoleInterviewer
from attractor.pipeline.outcome import StageStatus
from attractor.pipeline.parser import ParseError, parse_dot_file
from attractor.pipeline.validator import Severity, validate


def _load_run_config(config_path: str) -> dict[str, Any]:
    """Load a JSON run config file."""
    with open(config_path) as f:
        return json.load(f)


def _merge_run_config(config: dict[str, Any], flags: dict[str, Any]) -> dict[str, Any]:
    """Merge CLI flags over config — flags with non-None values win."""
    merged = dict(config)
    for key, value in flags.items():
        if value is not None:
            merged[key] = value
    return merged


def _discover_repo_config(repo_path: str) -> dict[str, Any]:
    """Load .attractor/config.json from a repo if it exists."""
    config_file = Path(repo_path) / ".attractor" / "config.json"
    if config_file.is_file():
        with open(config_file) as f:
            return json.load(f)
    return {}


def _apply_config_to_graph(graph: Graph, config: dict[str, Any]) -> None:
    """Apply run config values into graph attrs (config overrides DOT attrs)."""
    for key, value in config.items():
        if key != "max_steps":
            graph.attrs[key] = value


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

    # Build run config: .attractor/config.json < --config file < CLI flags
    repo_path = args.repo or os.getcwd()
    repo_config = _discover_repo_config(repo_path)

    explicit_config: dict[str, Any] = {}
    if args.config:
        try:
            explicit_config = _load_run_config(args.config)
        except (OSError, json.JSONDecodeError) as e:
            print(f"Config error: {e}", file=sys.stderr)
            return 1

    flags = {
        "goal": args.goal,
        "repo": args.repo,
        "max_steps": args.max_steps,
        "model": args.model,
    }

    config = _merge_run_config(repo_config, explicit_config)
    config = _merge_run_config(config, flags)
    _apply_config_to_graph(graph, config)

    max_steps = config.get("max_steps", 100)
    auto_approve = config.get("auto_approve", False) or args.auto_approve
    interviewer = AutoApproveInterviewer() if auto_approve else ConsoleInterviewer()

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    default_logs = f"{repo_path}/.attractor/logs/{Path(dot_path).stem}-{timestamp}"
    logs_root = args.logs or config.get("logs") or default_logs

    # Wire up LLM backend if an API key is available
    codergen_backend = None
    try:
        from attractor.llm.client import Client
        from attractor.pipeline.handlers.llm_backend import LLMBackend

        client = Client.from_env()
        if client._providers:
            model = config.get("model", "claude-sonnet-4-20250514")
            codergen_backend = LLMBackend(client=client, model=str(model))
            print(f"LLM backend: {model}")
    except ImportError:
        pass

    engine = Engine(
        interviewer=interviewer,
        logs_root=logs_root,
        max_steps=int(max_steps),
        codergen_backend=codergen_backend,
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
        "--config",
        help="Path to JSON run config file",
    )
    run_parser.add_argument(
        "--goal",
        help="Pipeline goal (overrides config and DOT attrs)",
    )
    run_parser.add_argument(
        "--repo",
        help="Target repository path (overrides config and DOT attrs)",
    )
    run_parser.add_argument(
        "--max-steps",
        type=int,
        default=None,
        help="Maximum engine steps before stopping (default: 100)",
    )
    run_parser.add_argument(
        "--model",
        default=None,
        help="LLM model to use (default: claude-sonnet-4-20250514)",
    )
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
