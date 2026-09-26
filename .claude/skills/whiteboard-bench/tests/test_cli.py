"""wb.py through its command line, as the just recipes call it: wiring and error paths."""
import json

import pytest
import wb
from test_judge import played
from test_watch import set_state


def run_cli(capsys, *argv):
    wb.main([str(a) for a in argv])
    return json.loads(capsys.readouterr().out.strip().splitlines()[-1])


def test_next_retry_resume_via_cli(make_run, capsys, monkeypatch, tmp_path):
    monkeypatch.setattr(wb, "RUNS", tmp_path / "runs")
    (tmp_path / "runs").mkdir()
    run = make_run("dg_org_chart", "bs_yes_and", "pl_kanban_updates")  # concurrency 2
    out = run_cli(capsys, "next", run)
    assert out == {"spawn": ["dg_org_chart", "bs_yes_and"], "judge": [], "running": 2, "pending": 1,
                   "finished": 0, "total": 3}
    set_state(run, "bs_yes_and", "abandoned")
    assert run_cli(capsys, "retry", run, "bs_yes_and") == {"task": "bs_yes_and", "state": "pending", "attempts": 1}
    out = run_cli(capsys, "resume", run)
    assert out["requeued"] == ["dg_org_chart", "bs_yes_and", "pl_kanban_updates"] and out["model"] == "test"


def test_rubric_score_and_judge_via_cli(make_run, capsys, monkeypatch):
    run = played(make_run, "human", "bs_yes_and")
    wb.main(["rubric", str(run), "bs_yes_and"])
    assert capsys.readouterr().out.startswith("=== item 0 ===\nYou are grading")
    assert run_cli(capsys, "score", run, "bs_yes_and", 0, 7, "solid", "--judge", "human")["score"] == 7
    answers = iter([])
    monkeypatch.setattr("builtins.input", lambda prompt: next(answers))
    wb.main(["judge", str(run)])  # nothing left to score: straight to the report
    lines = capsys.readouterr().out.strip().splitlines()
    assert json.loads(lines[0]) == {"scored": 0, "skipped": 0, "quit": False}
    assert json.loads(lines[-1])["awaiting_judgement"] == []


def test_judge_skips_tasks_without_rubric(make_run):
    run = played(make_run, "human", "dg_org_chart", "bs_yes_and")
    answers = iter(["5", "fine"])
    counts = wb.human_judge(run, ask=lambda prompt: next(answers))
    assert counts["scored"] == 1


def test_bad_answers_are_asked_again(make_run, capsys):
    run = played(make_run, "human", "bs_yes_and")
    answers = iter(["eleven", "-1", "10", "excellent"])
    assert wb.human_judge(run, ask=lambda p: next(answers))["scored"] == 1
    assert capsys.readouterr().out.count("please enter a whole number") == 2
    assert wb.scores(run, "bs_yes_and")["0"]["human"]["score"] == 10


def test_rubric_and_score_errors(make_run, capsys):
    run = played(make_run, "llm", "bs_yes_and", "dg_org_chart")
    with pytest.raises(SystemExit, match="no rubric"):
        wb.main(["rubric", str(run), "dg_org_chart"])
    with pytest.raises(SystemExit, match=r"item must be 0\.\.0"):
        wb.record_score(run, "bs_yes_and", 3, "llm", 5, "x")


def test_aggregate_with_nothing_finished(make_run):
    run = make_run("dg_org_chart")
    with pytest.raises(SystemExit, match="no finished tasks"):
        wb.aggregate([run])


def test_stop_gate_fails_open_on_missing_transcript(tmp_path):
    import subprocess
    import sys

    from conftest import SCRIPTS
    event = {"hook_event_name": "SubagentStop", "stop_hook_active": False,
             "agent_transcript_path": str(tmp_path / "gone.jsonl")}
    p = subprocess.run([sys.executable, str(SCRIPTS / "hooks" / "stop_gate.py")], input=json.dumps(event),
                       capture_output=True, text=True, check=True)
    assert p.stdout == ""
