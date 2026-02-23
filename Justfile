# Default recipe — show available commands
default:
    @just --list

# Install/sync all dependencies (including dev)
install:
    uv sync

# Regenerate lockfile after editing pyproject.toml
lock:
    uv lock

# Run all tests
test:
    uv run pytest

# Run unit tests only (excludes integration)
unit:
    uv run pytest -m "not integration"

# Run e2e / integration tests only
e2e:
    uv run pytest -m integration || if [ $? -eq 5 ]; then echo "No integration tests found"; fi

# Lint
lint:
    uv run ruff check src/ tests/

# Format
fmt:
    uv run ruff format src/ tests/

# Run the attractor CLI
run *ARGS:
    uv run attractor {{ ARGS }}

# Validate a pipeline file
validate PIPELINE:
    uv run attractor validate {{ PIPELINE }}
