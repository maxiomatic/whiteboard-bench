import json

import pytest
import wb


def ids(selector):
    return [t["id"] for t in wb.resolve(selector)]


def test_single_task_forms():
    for sel in ["08", "8", "dg_org_chart", "08_dg_org_chart"]:
        assert ids(sel) == ["dg_org_chart"], sel


def test_list_keeps_task_order_and_dedupes():
    assert ids("16,04,4") == ["dg_login_flowchart", "co_protected_region"]


def test_category():
    got = ids("diagramming")
    assert len(got) == 5 and all(t.startswith("dg_") for t in got)


def test_category_mixed_with_task():
    assert ids("diagramming,09")[-1] == "bs_divergent_ideas"


def test_smoke_is_one_task_per_category():
    index = {t["id"]: t for t in wb.task_index()}
    got = ids("smoke")
    cats = [index[t]["category"] for t in got]
    assert len(got) == 6 and len(set(cats)) == 6


def test_all():
    assert len(ids("all")) == 22


@pytest.mark.parametrize("bad", ["99", "nope", "diagram", "08,nope"])
def test_unknown_selector_is_an_error(bad):
    with pytest.raises(SystemExit, match="unknown selector"):
        wb.resolve(bad)


def test_list_marks_rubric_tasks(capsys):
    wb.main(["list"])
    lines = capsys.readouterr().out.splitlines()[1:]
    assert len(lines) == 22
    assert sum(line.rstrip().endswith("yes") for line in lines) == 6


def new(tmp_path, monkeypatch, capsys, *args, config=None):
    monkeypatch.setattr(wb, "RUNS", tmp_path / "runs")
    argv = ["new", *args]
    if config is not None:
        cfg = tmp_path / "config.toml"
        cfg.write_text(config)
        argv += ["--config", str(cfg)]
    wb.main(argv)
    return json.loads(capsys.readouterr().out)


def test_config_supplies_defaults(tmp_path, monkeypatch, capsys):
    out = new(tmp_path, monkeypatch, capsys, "--dry-run", config='select = "09"\nmodel = "haiku"\n')
    assert out["tasks"] == ["bs_divergent_ideas"] and out["model"] == "haiku"


def test_flags_override_config(tmp_path, monkeypatch, capsys):
    out = new(tmp_path, monkeypatch, capsys, "08", "--model", "sonnet", "--dry-run",
              config='select = "09"\nmodel = "haiku"\n')
    assert out["tasks"] == ["dg_org_chart"] and out["model"] == "sonnet"


def test_dry_run_creates_nothing(tmp_path, monkeypatch, capsys):
    new(tmp_path, monkeypatch, capsys, "smoke", "--dry-run")
    assert not (tmp_path / "runs").exists()


def test_new_records_resolved_config(tmp_path, monkeypatch, capsys):
    out = new(tmp_path, monkeypatch, capsys, "diagramming", "--model", "haiku", config='select = "09"\n')
    manifest = json.loads((tmp_path / "runs" / out["run"].split("/")[-1] / "manifest.json").read_text())
    assert manifest["config"] == {**wb.DEFAULTS, "select": "diagramming", "model": "haiku"}
    assert manifest["tasks"] == out["tasks"] and len(out["tasks"]) == 5
    assert (tmp_path / "runs" / ".active").read_text() == out["run"]


def test_unknown_config_key_is_an_error(tmp_path, monkeypatch, capsys):
    with pytest.raises(SystemExit, match="unknown key"):
        new(tmp_path, monkeypatch, capsys, "--dry-run", config='modle = "haiku"\n')


def test_shipped_config_is_valid():
    cfg = wb.load_config()
    assert set(cfg) == set(wb.DEFAULTS)
    wb.resolve(cfg["select"])


@pytest.mark.parametrize("line", ["concurrency = 0", "retries = -1", 'stall_minutes = "ten"'])
def test_bad_numbers_are_errors(tmp_path, monkeypatch, capsys, line):
    with pytest.raises(SystemExit, match="whole number"):
        new(tmp_path, monkeypatch, capsys, "--dry-run", config=line + "\n")
