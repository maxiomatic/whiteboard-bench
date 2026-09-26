import json
import time

import wb


def set_state(run, task, state, age=0.0):
    wb.write_status(run, task, state)
    f = run / task / "status.json"
    d = json.loads(f.read_text())
    d["updated"] = time.time() - age
    f.write_text(json.dumps(d))


def test_first_poll_summarises_then_reports_changes(make_run):
    run = make_run("dg_org_chart", "bs_yes_and", "pl_kanban_updates")
    w = wb.Watcher(run)
    assert w.poll() == ["status 3 pending"]
    set_state(run, "dg_org_chart", "spawned")
    assert w.poll() == []  # bookkeeping state: not worth an event
    set_state(run, "dg_org_chart", "playing")
    assert w.poll() == ["playing dg_org_chart"]
    set_state(run, "dg_org_chart", "done")
    assert w.poll() == ["done dg_org_chart (1/3 finished)"]
    assert w.poll() == []


def test_stall_is_reported_once(make_run):
    run = make_run("dg_org_chart", "bs_yes_and")
    w = wb.Watcher(run)
    w.poll()
    set_state(run, "dg_org_chart", "playing", age=11 * 60)  # stall_minutes is 10 in the fixture
    assert w.poll() == ["stalled dg_org_chart"]
    assert w.poll() == []


def test_abandoned_and_error_are_reported(make_run):
    run = make_run("dg_org_chart", "bs_yes_and")
    w = wb.Watcher(run)
    w.poll()
    set_state(run, "dg_org_chart", "abandoned")
    set_state(run, "bs_yes_and", "error")
    assert sorted(w.poll()) == ["abandoned dg_org_chart", "error bs_yes_and"]


def test_all_done_counts_failed_as_finished(make_run):
    run = make_run("dg_org_chart", "bs_yes_and")
    w = wb.Watcher(run)
    w.poll()
    set_state(run, "dg_org_chart", "done")
    set_state(run, "bs_yes_and", "failed")
    lines = w.poll()
    assert lines[-1] == "all done 2/2"


def test_watch_exits_when_everything_is_finished(make_run, capsys):
    run = make_run("dg_org_chart")
    set_state(run, "dg_org_chart", "done")
    wb.main(["watch", str(run), "--interval", "0"])
    assert capsys.readouterr().out.splitlines() == ["status 1 done", "all done 1/1"]
