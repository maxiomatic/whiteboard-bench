# WhiteboardBench commands. Run `just` to list them.

set shell := ["bash", "-euo", "pipefail", "-c"]

default:
    @just --list

# Install the dev toolchain (pytest, ruff) into .venv
setup:
    uv sync

# Core benchmark tests
test *args:
    uv run pytest tests {{args}}

# Lint
lint:
    uv run ruff check .

# Every reference solution must score 1.0 through the real harness
gate-replay:
    #!/usr/bin/env bash
    set -euo pipefail
    out=$(mktemp -d)
    uv run python -m wbench.run --agent replay --quiet --out "$out" > /dev/null
    uv run python -c 'import json,sys; s=json.load(open(sys.argv[1]))["summary"]; \
        assert s["overall"] == 1.0, s; print("replay overall", s["overall"])' "$out/results.json"
    rm -rf "$out"

# The gate every change must pass before it is committed
check: lint test gate-replay

# Run the benchmark: just run replay | just run null | just run anthropic --model claude-sonnet-5 --judge
run agent="replay" *args:
    uv run python -m wbench.run --agent {{agent}} {{args}}

# Regenerate tasks/*.json from scripts/build_tasks.py
build-tasks:
    uv run python scripts/build_tasks.py
