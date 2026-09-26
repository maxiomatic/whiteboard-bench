import json
import pathlib
import sys

SKILL = pathlib.Path(__file__).resolve().parents[1]
ROOT = SKILL.parents[2]
SCRIPTS = SKILL / "scripts"
sys.path[:0] = [str(ROOT), str(SCRIPTS)]

import pytest  # noqa: E402


@pytest.fixture
def make_run(tmp_path):
    """Create a run dir for the given task ids, the way `wb.py new` does."""
    def _make(*task_ids):
        import wb
        index = {t["id"]: t for t in wb.task_index()}
        run = tmp_path / "run"
        run.mkdir()
        (run / "manifest.json").write_text(json.dumps({
            "config": {"select": ",".join(task_ids), "model": "test"}, "tasks": list(task_ids), "files": {t: index[t]["file"] for t in task_ids}}))
        return run
    return _make
