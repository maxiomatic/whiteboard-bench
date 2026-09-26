---
name: whiteboard-bench
description: Run the WhiteboardBench eval with Claude Code subagents instead of the API. One wbench-player subagent plays each task against its own board server; results are graded by the benchmark's harness and merged into an HTML report.
argument-hint: "<task> [--model M]"
disable-model-invocation: true
allowed-tools: Bash(just sub-*) Agent
---

# /whiteboard-bench

Runs WhiteboardBench tasks with Claude Code subagents. You orchestrate: create the run, spawn the player, aggregate. You never play the task yourself and never read files under `tasks/` or the run directory. The scripts do the bookkeeping, so your context stays small.

Arguments: `$ARGUMENTS`
- `<task>`: a task number (`08`), id (`dg_org_chart`) or file stem (`08_dg_org_chart`). Required.
- `--model M`: the model the player runs on (`haiku`, `sonnet`, `opus`, or a full model id). If omitted, the player inherits this session's model.

## Steps

1. **Create the run**: `just sub-new <task> --label <model or "inherit">`. It prints `{"run": ..., "tasks": [...]}`. Remember `run`.
2. **Spawn the player**: use the Agent tool with `subagent_type: "wbench-player"`, the `model` from the arguments if given, and a prompt of exactly `Task id: <task id from step 1>`. Nothing else goes in the prompt: the board server gives the player everything it needs, and anything you add would contaminate the run.
3. **Aggregate** once the player finishes: `just sub-aggregate <run>`. It prints the overall score, category scores and the report path.
4. **Report** to the user in a few lines: the task, the model, the score, the report path. If `missing` is non-empty, the player stopped before the session completed. Say so; don't retry on your own.

Subagent runs use Claude Code's agent loop, so compare their scores with other subagent runs rather than with API runs (`just run anthropic ...`).
