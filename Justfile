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

# Run a pipeline (e.g. just run discovery)
run NAME *ARGS:
    uv run attractor run pipelines/{{ NAME }}.dot {{ ARGS }}

# Run a pipeline with auto-approve (e.g. just yolo discovery)
yolo NAME *ARGS:
    just run {{ NAME }} --auto-approve {{ ARGS }}

# Validate a pipeline file (e.g. just validate discovery)
validate NAME:
    uv run attractor validate pipelines/{{ NAME }}.dot
