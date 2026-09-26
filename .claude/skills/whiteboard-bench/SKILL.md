---
name: whiteboard-bench
description: Run the WhiteboardBench eval with Claude Code subagents instead of the API. One wbench-player subagent plays each task against its own board server; results are graded by the benchmark's harness and merged into an HTML report.
argument-hint: "[selector] [--model M] [--dry-run] | resume <run>"
disable-model-invocation: true
allowed-tools: Bash(just sub-*) Agent Monitor TaskStop
---

# /whiteboard-bench

Runs WhiteboardBench tasks with Claude Code subagents. You orchestrate: create the run, keep players running, aggregate. You never play a task yourself and never read files under `tasks/` or the run directory. The `just sub-*` recipes decide what to spawn and track state, so follow their output rather than your own bookkeeping.

Arguments: `$ARGUMENTS`

| Argument | Meaning | Default |
|---|---|---|
| selector | a task (`09`, `bs_divergent_ideas`), a list (`04,09,16`), a category (`diagramming`), `smoke` (first task of each category) or `all` | `select` in `config.toml` (`smoke`) |
| `--model M` | the model the players run on (`haiku`, `sonnet`, `opus`, or a full model id) | `model` in `config.toml` (`inherit`, meaning this session's model) |
| `--dry-run` | show what would run and how many players it would spawn, then stop | off |
| `resume <run>` | continue an earlier run: requeue its unfinished tasks, keep its settings | — |

Defaults, including `concurrency`, `retries` and `stall_minutes`, live in `.claude/skills/whiteboard-bench/config.toml`. `just sub-list` shows every task.

## Steps

1. **Create the run.** Run `just sub-new <arguments as given>`, or `just sub-resume <run>` for `resume`. It prints the run path, the model and the task list. Tell the user in one line what will run: the task count, the model and the concurrency. With `--dry-run`, stop here.

2. **Watch it.** Start the Monitor tool on `just sub-watch <run>` with the longest timeout it allows. Each line is an event (see step 4). If the watch hits its deadline before `all done`, start it again; its first line is a status summary, not new events.

3. **Spawn.** Run `just sub-next <run>`. For every id in `spawn`, launch a background Agent with `subagent_type: "wbench-player"`, `run_in_background: true`, `model` set to the run's model unless it is `inherit`, and a prompt of exactly `Task id: <id>`. Nothing else goes in the prompt: the board server gives the player everything it needs, and anything you add would contaminate the run. Remember which agent plays which task.

4. **React to events** until `all done`:

   | Event | Do |
   |---|---|
   | `playing <task>` | nothing |
   | `done <task> (k/n finished)` | `just sub-next <run>` and spawn what it lists |
   | `abandoned <task>` or `error <task>` | `just sub-retry <run> <task>`, then `just sub-next <run>` and spawn what it lists |
   | `stalled <task>` | stop that task's agent with TaskStop if it is still running, then handle it like `abandoned` |
   | `failed <task>` | nothing: its retries are used up, and it will show as missing in the report |
   | `all done n/n` | go to step 5 |

   When a player's completion notification arrives, record its cost with `just sub-timing <run> <task> <total_tokens> <duration_ms>`. Don't narrate routine events to the user. Only mention failures.

5. **Aggregate.** Run `just sub-aggregate <run>`. It prints the overall score, category scores, `missing` tasks, `total_tokens` and the report path.

6. **Report** to the user in a few lines: the model, the overall score, the category scores, total tokens and the report path. Name any missing tasks and say that `/whiteboard-bench resume <run>` retries them.

To combine separate runs (for example one category at a time) into one report: `just sub-aggregate <run> <run> ...`.

Subagent runs use Claude Code's agent loop, so compare their scores with other subagent runs rather than with API runs (`just run anthropic ...`).
