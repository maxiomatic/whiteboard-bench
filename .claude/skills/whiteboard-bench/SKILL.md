---
name: whiteboard-bench
description: Run the WhiteboardBench eval with Claude Code subagents instead of the API. One wbench-player subagent plays each task against its own board server; results are graded by the benchmark's harness and merged into an HTML report.
argument-hint: "[selector] [--model M] [--dry-run]"
disable-model-invocation: true
allowed-tools: Bash(just sub-*) Agent
---

# /whiteboard-bench

Runs WhiteboardBench tasks with Claude Code subagents. You orchestrate: create the run, spawn the players, aggregate. You never play a task yourself and never read files under `tasks/` or the run directory. The scripts do the bookkeeping, so your context stays small.

Arguments: `$ARGUMENTS`

| Argument | Meaning | Default |
|---|---|---|
| selector | a task (`09`, `bs_divergent_ideas`), a list (`04,09,16`), a category (`diagramming`), `smoke` (first task of each category) or `all` | `select` in `config.toml` (`smoke`) |
| `--model M` | the model the players run on (`haiku`, `sonnet`, `opus`, or a full model id) | `model` in `config.toml` (`inherit`, meaning this session's model) |
| `--dry-run` | show what would run and how many players it would spawn, then stop | off |

Defaults live in `.claude/skills/whiteboard-bench/config.toml`. `just sub-list` shows every task.

## Steps

1. **Create the run**: `just sub-new <arguments as given>`. It prints `{"run", "select", "model", "tasks", "players"}`. Tell the user in one line what will run: the task count, the model, the selector. With `--dry-run`, stop here.
2. **Play each task, one at a time, in the order listed**: use the Agent tool with `subagent_type: "wbench-player"` and a prompt of exactly `Task id: <task id>`. Pass `model` unless the run's model is `inherit`. Wait for each player to finish before spawning the next. Nothing else goes in the prompt: the board server gives the player everything it needs, and anything you add would contaminate the run.
3. **Aggregate**: `just sub-aggregate <run>`. It prints the overall score, category scores, `missing` tasks and the report path.
4. **Report** to the user in a few lines: the model, the overall score, the category scores, the report path. If `missing` is non-empty, those players stopped before their session completed. Name them; don't retry on your own.

Subagent runs use Claude Code's agent loop, so compare their scores with other subagent runs rather than with API runs (`just run anthropic ...`).
