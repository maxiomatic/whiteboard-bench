# WhiteboardBench

WhiteboardBench measures how well an AI agent works at a shared whiteboard with people. The agent gets a spoken or typed request, reads the board, and changes it through a tool API: sticky notes, shapes, frames, connectors, freehand strokes, layout helpers, comments, undo and speech. Scripted human collaborators keep editing the board, voting, pointing and talking between turns and sometimes in the middle of one. Deterministic checks grade the result, and an optional LLM judge scores the few things that need taste.

The benchmark itself is Python standard library only. Commands run through [just](https://just.systems) and [uv](https://docs.astral.sh/uv/), which also installs the dev tools (pytest, ruff). Install just with `uv tool install rust-just`, then:

```bash
just setup                                 # create .venv with the dev tools
just run replay                            # reference solutions, should score 1.0
just run null                              # does nothing, sets the floor
export ANTHROPIC_API_KEY=...
just run anthropic --model claude-sonnet-5 --judge
just check                                 # lint, tests, and the replay-scores-1.0 gate
```

Run `just` to list every command.

Each run writes `runs/<agent>-<timestamp>/results.json` and a self-contained `report.html` with per-check scores and an SVG snapshot of the board after every turn. To see what a report looks like without running anything, open [`docs/sample-report.html`](docs/sample-report.html), a run of the replay agent.

## Run with Claude Code subagents (no API key)

The `/whiteboard-bench` skill in `.claude/skills/whiteboard-bench/` runs tasks with Claude Code subagents instead of the API. Each task gets one `wbench-player` subagent (`.claude/agents/wbench-player.md`). The player talks to its own board server over MCP, sees only the whiteboard tools, and gets the same instructions an API run gets. The unmodified harness grades the result, and scores never reach the player.

In Claude Code, from the repo root:

```
/whiteboard-bench 08                          # one task, player on this session's model
/whiteboard-bench 08 --model haiku            # choose the player's model
/whiteboard-bench 04,09,16                    # a few tasks
/whiteboard-bench diagramming --model sonnet  # a category
/whiteboard-bench all                         # all 22
/whiteboard-bench all --dry-run               # show what would run, spawn nothing
/whiteboard-bench 10 --judge human            # you score the rubric check afterwards
```

`just sub-list` shows every task with its number, category, turn count and whether it has a rubric check. A selector is always required, so nothing runs by accident. Defaults live in `.claude/skills/whiteboard-bench/config.toml`: the model, how many players run at once (`concurrency`), how often a failed task is retried (`retries`) and when a silent player counts as stalled (`stall_minutes`). Each run records the settings it used in its `manifest.json`.

Players run in parallel up to `concurrency`. The orchestrator follows a Monitor feed (`just sub-watch <run>`) instead of polling. A player that disconnects, errors or stalls is retried, and its files are archived first, so a stale player can't write into the new attempt. Token use per task comes from each player's completion notice and is summed in the report. `/whiteboard-bench resume <run>` requeues whatever didn't finish, and `just sub-aggregate <run> <run> ...` merges separate runs (say, one category at a time) into one report.

### How the judge affects scores

Only 6 of the 22 tasks have a `rubric` check, a taste question that code can't grade:

| # | Task | Rubric question |
|---|---|---|
| 09 | Divergent ideas | Are the ideas varied, specific enough to act on, and plausible for a public library? |
| 10 | Affinity map | Do the theme titles name the underlying user need clearly? |
| 11 | "Yes, and" | Does each new sticky genuinely extend the idea it's connected to? |
| 13 | Sprint retro | Are the action items concrete, owned or time-bound, and aimed at the problems? |
| 18 | Conflicting requests | Did the AI present both proposals fairly and hand the decision back to the group? |
| 22 | Focus layers | Does the focus note frame the pricing decision and name the options? |

For subagent runs, `judge` in `config.toml`, or `--judge` per run, decides who answers them:

- `llm` (default): a `wbench-judge` subagent per rubric task, with the same prompt as the API judge. At most 6 small subagents per full run.
- `human`: nobody during the run. Afterwards, `just sub-judge <run>` opens a review page per item (the requests, the final board, what the AI said, the question) and asks you for a score from 0 to 10 and a one-line reason. It costs no tokens, and you can stop and pick up later.
- `off`: rubric checks are left out of the score, not scored zero.

Turning the judge off changes scores, not just cost. Take task 09, where the rubric carries weight 3 of 9. If the agent writes 15 distinct but generic ideas that a judge would rate 4/10, the task scores 0.80 with a judge and 1.00 without one. So compare scores only across runs that used the same mode. The report's title states it. A task still awaiting a score is left out of the overall score until it has one. `just sub-judge <run> --rejudge` lets you score items an LLM judge already scored: both scores are kept and shown side by side, and the human score counts.

Two hooks in the player's definition enforce the rules at runtime. `guard_tools.py` denies any tool that isn't a board tool, and `stop_gate.py` stops the player from quitting before the session is over (it blocks once, then lets a stuck player go). Each run writes `runs/subagents-<model>-<timestamp>/` with a `result.json` per task, plus `results.json` and `report.html` in the same format as API runs. Claude Code only starts the player's board server and hooks after you trust the repo folder. Subagent runs use Claude Code's agent loop, so compare them with other subagent runs rather than with API runs.

## What it tests

Real whiteboard sessions are social and iterative. Someone talks while someone else writes, the plan changes halfway through, a colleague is still presenting from one corner, and "put it here" only makes sense if you saw where they pointed. The tasks are built around those situations rather than around drawing a single perfect diagram.

The design follows five principles.

1. **Grade the board state.** Checks look at what ended up on the board, so any sequence of tool calls that produces a good board scores well.
2. **Match content loosely and structure strictly.** Text matching uses stemmed token recall with alternatives, so "Activation dashboard" matches "Build an activation dashboard by Friday". Graph edges, frame membership, spatial relations and reading order are checked exactly.
3. **Treat other people's work as theirs.** Every element records its author. Deleting, moving or rewriting human content without being asked costs points.
4. **Make the board move.** Human events fire before turns and, with `at_call`, after the agent's k-th tool call, so an agent that plans once and executes blindly will clobber changes.
5. **Doing nothing scores close to zero.** Constraint checks such as "no overlaps" or "human work preserved" are guards. An empty board satisfies them trivially, so they can reduce a score but never earn points alone.

## Tasks

22 tasks in six categories. Turns counts the number of requests in the session. Events counts scripted human actions; "mid" events land inside a turn.

| # | Category | Task | Difficulty | Turns | Events | Skills |
|---|---|---|---|---|---|---|
| 01 | note_taking | Capture a product sync into decisions, actions, questions | easy | 1 | 0 | summarization, categorization, attribution |
| 02 | note_taking | Live lecture notes with a correction | medium | 3 | 0 | incremental capture, hierarchy, revision in place |
| 03 | note_taking | Consolidate duplicate feedback stickies | medium | 1 | 0 | deduplication, attribution, layout |
| 04 | diagramming | Flowchart from a verbal description | medium | 1 | 0 | flowcharts, notation, layout |
| 05 | diagramming | Tiered system architecture diagram | medium | 1 | 0 | architecture diagrams, grouping, notation |
| 06 | diagramming | Clean up a hand-drawn sketch into a diagram | hard | 1 | 0 | sketch interpretation, spatial reasoning, cleanup |
| 07 | diagramming | Evolve a state machine with a collaborator | medium | 3 | 1 | iteration, respecting collaborator input |
| 08 | diagramming | Org chart with tree layout | easy | 1 | 0 | hierarchies, tree layout |
| 09 | brainstorming | Divergent idea generation | easy | 1 | 0 | ideation, divergence |
| 10 | brainstorming | Affinity map of user-research quotes | hard | 1 | 0 | synthesis, clustering, labeling |
| 11 | brainstorming | Build on teammates' ideas ("yes, and") | medium | 1 | 0 | generative building, linking |
| 12 | brainstorming | Converge after dot voting, then handle late votes | medium | 2 | 1 | convergence, reacting to change |
| 13 | planning | Run a sprint retro across three rounds | hard | 3 | 7 | facilitation, clustering others' notes, action planning |
| 14 | planning | Impact/effort 2x2 prioritization | medium | 1 | 0 | prioritization frameworks, spatial semantics |
| 15 | planning | Kanban board kept in sync with status updates | medium | 3 | 2 | state tracking, inferring intent from speech |
| 16 | collaboration | Tidy one area while a colleague presents from another | medium | 1 | 1 mid | scoped edits, concurrent editing |
| 17 | collaboration | Reorganize, then restore on request | easy | 2 | 0 | undo, memory of prior state |
| 18 | collaboration | Mediate conflicting requests from two people | hard | 1 | 2 | mediation, neutrality |
| 19 | xr_spatial | Resolve "here", "this" and "that" from pointing | medium | 3 | 4 | deixis, multimodal grounding |
| 20 | xr_spatial | Hand out items within each person's reach | medium | 1 | 0 | embodied ergonomics, ownership |
| 21 | xr_spatial | Capture a noisy multi-speaker conversation | medium | 1 | 6 | speech capture, speaker attribution, filtering |
| 22 | xr_spatial | Use depth layers to focus the room | easy | 1 | 0 | attention management, 3D affordances |

### XR and spatial tasks

These anticipate an AI sharing a room-scale board in mixed reality.

Pointing and gaze arrive as board coordinates with jitter, for example `Maya points at board position (1412, 655)`. The agent has to call `get_elements_at` and work out what "this" or "over there" refers to.

Participants have a standing position and an arm's reach radius. Task 20 asks the agent to put each person's action items where that person can physically touch them.

Every element has an integer `layer` for depth. Task 22 asks the agent to push background material back and bring the decision under discussion forward.

Speech arrives as transcript lines from several speakers, including crosstalk and off-topic remarks that should not end up on the board.

## How a task runs

A task file in `tasks/` defines participants, the initial board, a list of turns and final checks. Each turn has a prompt from a named speaker, optional human events, and checks graded when the agent calls `finish_turn` or runs out of budget.

```
build board from initial_elements
for each turn:
    apply pre-turn events           -> described to the agent as board activity
    send prompt + activity + board summary
    agent calls tools until finish_turn or max_calls_per_turn
        mid-turn events fire after call k and ride along in that tool result
        if the agent finished before call k, the event is delivered afterwards
        and the agent gets one more chance to respond
    grade the turn's checks, snapshot the board, render SVG
grade final_checks
```

Human event types are `create`, `update`, `move`, `delete`, `vote`, `comment`, `say` and `point`. Targets are resolved by content, so events work wherever the agent placed things. If an event's target does not exist because the agent never drew it, the event is skipped and listed in `skipped_events`.

## Tool API

Tools use Anthropic-style JSON schemas, defined in `wbench/tools.py`. Every call runs in a transaction. A call that fails validation leaves the board untouched and returns an error message the agent can learn from.

| Tool | Purpose |
|---|---|
| `get_board` | Full board description, optionally limited to a frame or region |
| `find_elements` | Fuzzy text search plus filters on type, color, author, frame and layer |
| `get_elements_at` | Elements near a point, nearest first. Used for pointing and gaze |
| `create_sticky`, `create_shape`, `create_text`, `create_frame` | Content. Shapes include rect, rounded_rect, ellipse, diamond, triangle, cylinder, parallelogram, hexagon and cloud |
| `create_connector` | Line or arrow between two elements, with optional label |
| `draw_stroke` | Freehand ink for circling or underlining |
| `update_element` | Text, color, shape kind, layer, tags, connector label and direction |
| `move_elements`, `translate_elements`, `resize_element` | Geometry. Moving a frame carries its contents |
| `arrange`, `align` | Row, column and grid layout, plus edge and center alignment |
| `delete_elements`, `group`, `ungroup`, `add_comment` | Housekeeping |
| `undo` | Reverts the agent's own last call. Elements someone else edited since then are kept and reported as conflicts |
| `say` | Speak to the room |
| `finish_turn` | End the turn with a short summary |

## Scoring

Each check returns a score from 0 to 1 and a readable explanation. The check library lives in `wbench/checks.py`.

| Check | What it measures |
|---|---|
| `texts_present`, `texts_absent` | Fuzzy content recall, and that wrong or retracted text is gone |
| `count`, `distinct`, `max_words` | Quantity, duplicate detection, sticky brevity |
| `said` | The agent said something containing the expected points |
| `frames`, `in_frame` | Frames exist and items sit inside the right one |
| `clusters` | Pairwise F1 between the expected grouping and the board's grouping by frame, group or spatial proximity |
| `graph` | Node recall plus edge F1 over connectors. Reversed or undirected edges get partial credit |
| `node_kinds` | Diagram notation, such as decisions drawn as diamonds and databases as cylinders |
| `relation`, `order`, `aligned`, `grid_aligned`, `no_overlap` | Spatial layout |
| `quadrants`, `near_point`, `nearest_label`, `in_region` | 2x2 placement, deixis targets and reach zones |
| `each_connected` | Every seed idea has enough connected builds nearby |
| `property` | A field such as color, type or layer has the expected value |
| `preserve_human`, `matches_snapshot` | Human work kept intact, and a prior state restored |
| `rubric` | LLM judge question scored 0 to 10. Skipped when `--judge` is off |

A set of checks is scored as `progress * (0.5 + 0.5 * guards)`, where progress is the weighted mean of ordinary checks and guards is the weighted mean of `preserve_human`, `no_overlap`, `texts_absent`, max-only `count`, and anything marked `"guard": true`. A check can also carry `"requires_change": ["initial", "turn1_end"]`, which withholds credit unless the board actually changed between those snapshots. That stops the null agent from "restoring" a board it never touched.

The task score is the combined score of every turn check and final check. The overall score is the mean of the six category means, so categories with more tasks don't dominate. The report also lists tool calls, tool error rate and efficiency, which is the reference solution's call count divided by the agent's. Efficiency is reported alongside the score and does not change it.

Current baselines:

| Agent | Overall | Notes |
|---|---|---|
| replay | 1.00 | Every reference solution passes every check with zero tool errors |
| null | 0.04 | No task above 0.5 |

The test suite also runs a "vandal" agent that solves each task and then deletes all human content. It scores below 0.6 on 12 of the 13 tasks that start with human content. The exception is the sketch cleanup task, where removing the human's rough sketch is part of the request.

## Adding a task

`scripts/build_tasks.py` is the source of truth. Add a `task(...)` call there with its turns, checks, events, participants, initial elements and a reference solution, then run:

```bash
just build-tasks
just check
```

The tests fail if the reference solution scores below 1.0, which catches both broken checks and impossible tasks. Reference solution steps are ordinary tool calls. Arguments can refer to earlier results with `"$name"`, look things up with `{"$find": selector}` or `{"$find_all": selector}`, and resolve a point with `{"$at": [x, y]}`.

## Adding an agent

Subclass `wbench.agents.base.Agent`:

```python
class MyAgent(Agent):
    name = "mine"

    def start(self, briefing):
        ...  # task title, participants, tool schemas, conventions

    def run_turn(self, message, env):
        result = env.call("find_elements", {"query": "checkout"})
        # result may include "board_activity" if humans acted mid-turn
        env.call("finish_turn", {"summary": "..."})
```

Register it in `wbench/agents/__init__.py`. `wbench/agents/anthropic_agent.py` is a complete example that keeps the conversation history across turns and supports extended thinking with `--thinking <tokens>`.

## Layout

```
wbench/
  board.py        element model, transactions, per-actor undo, frame containment
  tools.py        tool schemas and executor
  events.py       scripted human collaborators
  checks.py       grading library
  textmatch.py    fuzzy text matching
  harness.py      turn loop, guards, scoring
  render.py       SVG snapshots
  report.py       HTML report
  judge.py        optional LLM rubric judge
  run.py          CLI
  agents/         null, replay, anthropic
scripts/build_tasks.py
tasks/*.json
tests/test_smoke.py
justfile          every command
.claude/skills/whiteboard-bench/   /whiteboard-bench: run with Claude Code subagents
.claude/agents/wbench-player.md    the subagent under test
.claude/agents/wbench-judge.md     the rubric grader (judge = "llm")
pyproject.toml    uv project and dev tools
```

## Limitations and next steps

Agents see the board as structured text. A vision track that sends rendered snapshots instead would test whether models can read a messy board the way people do, and the SVG renderer is already in place for it.

The board is 2D with depth layers. Full 3D placement, occlusion and head-relative anchoring would need a richer spatial model.

Speech and pointing are delivered as text. Streaming audio with timing, interruptions and gestures that overlap speech would be closer to a live XR session.

Human collaborators are scripted and do not react to what the agent does. Simulated participants driven by a model would allow open-ended sessions but would make scores less reproducible.

Rubric checks depend on the judge model, so scores with `--judge` should be compared only across runs that used the same judge.
