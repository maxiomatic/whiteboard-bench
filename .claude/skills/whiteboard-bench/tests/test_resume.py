import json

import pytest
import wb
from test_watch import set_state


def test_next_respects_concurrency_and_never_repeats(make_run):
    run = make_run("dg_org_chart", "bs_yes_and", "pl_kanban_updates")  # concurrency 2
    assert wb.next_tasks(run) == ["dg_org_chart", "bs_yes_and"]
    assert wb.next_tasks(run) == []
    set_state(run, "dg_org_chart", "done")
    assert wb.next_tasks(run) == ["pl_kanban_updates"]
    assert wb.next_tasks(run) == []


def test_stalled_players_free_their_slot(make_run):
    run = make_run("dg_org_chart", "bs_yes_and", "pl_kanban_updates")
    wb.next_tasks(run)
    set_state(run, "dg_org_chart", "playing", age=11 * 60)
    assert wb.next_tasks(run) == ["pl_kanban_updates"]


def test_retry_requeues_then_fails(make_run):
    run = make_run("dg_org_chart")  # retries 1
    set_state(run, "dg_org_chart", "abandoned")
    assert wb.retry(run, "dg_org_chart") == "pending"
    assert wb.status(run, "dg_org_chart")["state"] == "pending"
    assert (run / ".attempts" / "dg_org_chart-1" / "status.json").exists()
    assert wb.next_tasks(run) == ["dg_org_chart"]
    set_state(run, "dg_org_chart", "error")
    assert wb.retry(run, "dg_org_chart") == "failed"
    assert wb.status(run, "dg_org_chart")["state"] == "failed"


def test_retry_refuses_done_and_unknown_tasks(make_run):
    run = make_run("dg_org_chart")
    set_state(run, "dg_org_chart", "done")
    with pytest.raises(SystemExit, match="already done"):
        wb.retry(run, "dg_org_chart")
    with pytest.raises(SystemExit, match="not part of"):
        wb.retry(run, "bs_yes_and")


def test_resume_requeues_unfinished_with_fresh_budget(make_run, monkeypatch, tmp_path):
    monkeypatch.setattr(wb, "RUNS", tmp_path / "runs")
    (tmp_path / "runs").mkdir()
    run = make_run("dg_org_chart", "bs_yes_and", "pl_kanban_updates")
    set_state(run, "dg_org_chart", "done")
    set_state(run, "bs_yes_and", "abandoned")
    wb.retry(run, "bs_yes_and")
    set_state(run, "bs_yes_and", "failed")
    assert wb.resume(run) == ["bs_yes_and", "pl_kanban_updates"]
    assert wb.status(run, "bs_yes_and")["state"] == "pending"
    assert (tmp_path / "runs" / ".active").read_text() == str(run)
    set_state(run, "bs_yes_and", "abandoned")
    assert wb.retry(run, "bs_yes_and") == "pending"  # budget counted from the resume
    assert json.loads((run / "manifest.json").read_text())["config"]["retries"] == 1  # recorded config untouched


def test_timing_is_recorded(make_run, capsys):
    run = make_run("dg_org_chart")
    wb.main(["timing", str(run), "dg_org_chart", "--tokens", "1234", "--ms", "5678"])
    assert json.loads((run / "dg_org_chart" / "timing.json").read_text()) == {"total_tokens": 1234, "duration_ms": 5678}
