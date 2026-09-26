# WhiteboardBench commands. Run `just` to list them.

set shell := ["bash", "-eo", "pipefail", "-c"]

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

skill := ".claude/skills/whiteboard-bench"

# Tests for the /whiteboard-bench subagent skill (own deps, isolated from the core project)
test-skill *args:
    uv run --quiet --no-project --with 'mcp>=2.2,<3' --with pytest --with pyyaml pytest {{skill}}/tests {{args}}

# The gate every change must pass before it is committed
check: lint test gate-replay test-skill

# Run the benchmark: just run replay | just run null | just run anthropic --model claude-sonnet-5 --judge
run agent="replay" *args:
    uv run python -m wbench.run --agent {{agent}} {{args}}

# Regenerate tasks/*.json from scripts/build_tasks.py
build-tasks:
    uv run python scripts/build_tasks.py

# --- /whiteboard-bench: run the benchmark with Claude Code subagents ---

# List every task: number, id, category, turns, rubric check (no tokens)
sub-list:
    @uv run --quiet --script {{skill}}/scripts/wb.py list

# Create a run and make it active: just sub-new <selector> [--model M] [--judge llm|human|off] [--dry-run]
sub-new *args:
    @uv run --quiet --script {{skill}}/scripts/wb.py new {{args}}

# Task ids to spawn now, within the run's concurrency
sub-next run:
    @uv run --quiet --script {{skill}}/scripts/wb.py next {{run}}

# Archive a task's failed attempt, then requeue it or mark it failed
sub-retry run task:
    @uv run --quiet --script {{skill}}/scripts/wb.py retry {{run}} {{task}}

# Record what a player or judge cost (from the Agent completion notification)
sub-timing run task tokens ms role="player":
    @uv run --quiet --script {{skill}}/scripts/wb.py timing {{run}} {{task}} --tokens {{tokens}} --ms {{ms}} --role {{role}}

# Score rubric checks yourself at the terminal (judge = "human", or --rejudge an LLM-judged run)
sub-judge run *args:
    @uv run --quiet --script {{skill}}/scripts/wb.py judge {{run}} {{args}}

# What the LLM judge grades for a task (used by wbench-judge)
sub-rubric run task:
    @uv run --quiet --script {{skill}}/scripts/wb.py rubric {{run}} {{task}}

# Record a rubric score (used by wbench-judge)
sub-score run task item score reason:
    @uv run --quiet --script {{skill}}/scripts/wb.py score {{run}} {{task}} {{item}} {{score}} "{{reason}}"

# Make an earlier run active again and requeue its unfinished tasks
sub-resume run:
    @uv run --quiet --script {{skill}}/scripts/wb.py resume {{run}}

# One line per task state change until the run finishes (what the Monitor tool runs)
sub-watch run:
    @uv run --quiet --script {{skill}}/scripts/wb.py watch {{run}}

# Merge one or more runs into results.json + report.html
sub-aggregate +runs:
    @uv run --quiet --script {{skill}}/scripts/wb.py aggregate {{runs}}

# Board server for one player. Claude Code starts this for each wbench-player; never run it by hand
sub-server:
    @uv run --quiet --script {{skill}}/scripts/mcp_server.py
