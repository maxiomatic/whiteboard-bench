---
name: whiteboard-bench
description: Run the WhiteboardBench eval with Claude Code subagents instead of the API. One wbench-player subagent plays each task against its own board server; results are graded by the benchmark's harness and merged into an HTML report.
argument-hint: "<selector> [--model M] [--judge llm|human|off] [--dry-run] | resume <run>"
disable-model-invocation: true
allowed-tools: Bash(just sub-*) Agent Monitor TaskStop
---

# /whiteboard-bench

Runs WhiteboardBench tasks with Claude Code subagents. You orchestrate: create the run, keep players running, aggregate. You never play a task yourself and never read files under `tasks/` or the run directory. The `just sub-*` recipes decide what to spawn and track state, so follow their output rather than your own bookkeeping.

Arguments: `$ARGUMENTS`

| Argument | Meaning | Default |
|---|---|---|
| selector | a task (`09`, `bs_divergent_ideas`), a list (`04,09,16`), a category (`diagramming`) or `all` | required |
| `--model M` | the model the players run on (`haiku`, `sonnet`, `opus`, or a full model id) | `model` in `config.toml` (`inherit`, meaning this session's model) |
| `--judge llm\|human\|off` | who grades the rubric checks (see below) | `judge` in `config.toml` (`llm`) |
| `--dry-run` | show what would run and how many players and judges it would spawn, then stop | off |
| `resume <run>` | continue an earlier run: requeue its unfinished tasks, keep its settings | — |

Defaults, including `judge_model`, `concurrency`, `retries` and `stall_minutes`, live in `.claude/skills/whiteboard-bench/config.toml`. `just sub-list` shows every task.

## Steps

1. **Create the run.** If no selector was given, run `just sub-list`, show the user the tasks, ask what to run and stop there: never guess a selection, since every task costs tokens. Otherwise run `just sub-new <arguments as given>`, or `just sub-resume <run>` for `resume`. It prints the run path, the model, the judge mode and the task list. Tell the user in one line what will run: the task count, the model, the judge mode and the concurrency. With `--dry-run`, stop here.

2. **Watch it.** Start the Monitor tool on `just sub-watch <run>` with the longest timeout it allows. Each line is an event (see step 4). If the watch hits its deadline before `all done`, start it again; its first line is a status summary, not new events.

3. **Spawn.** Run `just sub-next <run>`. It lists players to start (`spawn`) and judges to start (`judge`).
   - For every id in `spawn`, launch a background Agent with `subagent_type: "wbench-player"`, `run_in_background: true`, `model` set to the run's model unless it is `inherit`, and a prompt of exactly `Task id: <id>`. Nothing else goes in the prompt: the board server gives the player everything it needs, and anything you add would contaminate the run.
   - For every id in `judge`, launch a background Agent with `subagent_type: "wbench-judge"`, `run_in_background: true`, `model` set to the run's `judge_model` unless it is `inherit`, and a prompt of exactly `Run: <run>` and `Task id: <id>` on two lines.
   - Remember which agent is doing what for which task.

4. **React to events** until `all done`:

   | Event | Do |
   |---|---|
   | `playing <task>` | nothing |
   | `done <task> (k/n finished)` | `just sub-next <run>` and spawn what it lists |
   | `judging <task>` | the player finished and the task waits on an LLM judge: `just sub-next <run>` and spawn what it lists |
   | `judged <task> (k/n finished)` | nothing |
   | `abandoned <task>` or `error <task>` | `just sub-retry <run> <task>`, then `just sub-next <run>` and spawn what it lists |
   | `stalled <task>` | stop that task's agent with TaskStop if it is still running, then handle it like `abandoned` |
   | `failed <task>` | nothing: its retries are used up, and it will show as missing in the report |
   | `all done n/n` | go to step 5 |

   When an agent's completion notification arrives, record its cost: `just sub-timing <run> <task> <total_tokens> <duration_ms>` for a player, with ` judge` appended for a judge. Don't narrate routine events to the user. Only mention failures.

5. **Aggregate.** Run `just sub-aggregate <run>`. It prints the overall score, category scores, the judge mode, `missing` and `awaiting_judgement` tasks, `total_tokens` and the report path.

6. **Report** to the user in a few lines: the model, the judge mode, the overall score, the category scores, total tokens and the report path.
   - Name any missing tasks and say that `/whiteboard-bench resume <run>` retries them.
   - If tasks are awaiting judgement, which is always the case with `--judge human`, say they are left out of the overall score until scored, and that `just sub-judge <run>` scores them at the terminal.

To combine separate runs (for example one category at a time) into one report: `just sub-aggregate <run> <run> ...`.

Subagent runs use Claude Code's agent loop, so compare their scores with other subagent runs rather than with API runs (`just run anthropic ...`).

## How the judge affects scores

Only 6 of the 22 tasks have a `rubric` check, a question code can't grade: 09 divergent ideas, 10 affinity map, 11 "yes, and", 13 sprint retro, 18 conflicting requests and 22 focus layers. Everything else is graded by code. The `judge` setting decides who answers the rubric question, on a scale of 0 to 10:

| Mode | Who grades | Cost |
|---|---|---|
| `llm` (default) | a `wbench-judge` subagent per rubric task, with the same prompt as the API judge (`wbench/judge.py`) | at most 6 small subagents per full run |
| `human` | you, after the run: `just sub-judge <run>` opens a review page per item (requests, final board, what the AI said, the question) and asks for a score and a one-line reason | no tokens |
| `off` | nobody: rubric checks are left out of the score, not scored zero | none |

Turning the judge off changes scores, not just cost. In task 09 the rubric carries weight 3 of 9. Fifteen distinct but generic ideas that a judge would rate 4/10 score 0.80 with a judge and 1.00 without one. So compare scores only across runs that used the same judge mode. The report's title states the mode.

A task whose rubric check isn't scored yet is shown as awaiting judgement and left out of the overall score until it is. `just sub-judge <run> --rejudge` lets you score items an LLM judge already scored. Both scores are kept, the report shows them side by side, and the human score counts.
