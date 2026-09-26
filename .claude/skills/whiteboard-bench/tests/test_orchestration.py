"""The whole /whiteboard-bench loop with scripted players instead of subagents.

Mirrors SKILL.md: next -> spawn players -> react to watch events -> aggregate.
Players replay reference solutions over real MCP stdio, in parallel threads.
"""
import json
import threading

import wb
from test_mcp_server import replay_through_mcp


def test_run_a_category_in_parallel_with_one_abandoned_player(make_run, capsys):
    tasks = ["dg_org_chart", "bs_yes_and", "co_protected_region", "pl_kanban_updates"]
    run = make_run(*tasks)  # concurrency 2, retries 1
    flaky = {"bs_yes_and"}  # first player for this task gives up without playing
    threads, events = [], []
    watcher = wb.Watcher(run)
    watcher.poll()

    def player(task):
        if task in flaky:
            flaky.discard(task)
            wb.write_status(run, task, "abandoned")
            return
        replay_through_mcp(run, task)

    def spawn():
        for task in wb.next_tasks(run):
            t = threading.Thread(target=player, args=(task,))
            t.start()
            threads.append(t)

    spawn()
    for _ in range(200):
        for t in threads:
            t.join(timeout=0.05)
        for line in watcher.poll():
            events.append(line)
            kind, task = line.split()[0], line.split()[1]
            if kind == "done":
                spawn()
            elif kind in ("abandoned", "error", "stalled"):
                assert wb.retry(run, task) == "pending"
                spawn()
        if events and events[-1].startswith("all done"):
            break
    for t in threads:
        t.join()

    assert events[-1] == "all done 4/4"
    assert "abandoned bs_yes_and" in events
    assert (run / ".attempts" / "bs_yes_and-1").exists()
    wb.main(["aggregate", str(run)])
    out = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert out["overall"] == 1.0 and out["tasks"] == 4 and out["missing"] == []
