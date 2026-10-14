"""s116 e2e T1-T8: the dashboard fixture is rebuilt from its source sections.

These read real files and run the script as a process.
"""

import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

RUNNER = Path(__file__).resolve().parents[2]
SCRIPT = RUNNER / "scripts" / "make_dashboard_fixture.py"
OLD_CURATED_END = 1791472260.0


@pytest.fixture(scope="module")
def mod() -> ModuleType:
    """The script as a module; fails (without running it) if it has no main guard."""
    assert "__main__" in SCRIPT.read_text(), "the script needs an `if __name__ == '__main__'` guard"
    spec = importlib.util.spec_from_file_location("make_dashboard_fixture", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_script(out: Path) -> None:
    """Run the script as a process, writing to ``out``."""
    subprocess.run([sys.executable, str(SCRIPT), str(out)], check=True)


def test_t1_committed_equals_rebuild(mod):
    assert mod.build(mod.SOURCE) == mod.FIXTURE.read_text(), (
        "snapshot.json differs from a rebuild: edit scripts/dashboard_fixture/ "
        "and run make_dashboard_fixture.py"
    )


def test_t2_twice_is_byte_identical(tmp_path, mod):
    a, b = tmp_path / "a.json", tmp_path / "b.json"
    run_script(a)
    first = a.read_bytes()
    run_script(a)
    assert a.read_bytes() == first
    run_script(b)
    assert b.read_bytes() == first


@pytest.mark.parametrize("junk", ["not json", json.dumps({"events": []})])
def test_t3_existing_file_is_ignored(tmp_path, mod, junk):
    out = tmp_path / "out.json"
    out.write_text(junk)
    run_script(out)
    assert out.read_text() == mod.build(mod.SOURCE)


def test_t4_nothing_is_filtered(mod):
    events = json.loads((mod.SOURCE / "events.json").read_text())
    rebuilt = json.loads(mod.build(mod.SOURCE))["events"]
    assert rebuilt == events
    assert any(e["at"] > OLD_CURATED_END for e in rebuilt)
    assert any(e.get("id") == "e105" for e in rebuilt)


def test_t5_key_order(mod):
    assert list(json.loads(mod.build(mod.SOURCE))) == list(mod.SECTIONS)


def test_t6_source_mismatch_fails_and_writes_nothing(tmp_path, mod, monkeypatch, capsys):
    src = tmp_path / "src"
    shutil.copytree(mod.SOURCE, src)
    (src / "health.json").unlink()
    (src / "extra.json").write_text("{}")
    with pytest.raises(mod.FixtureSourceError) as err:
        mod.load_sections(src)
    assert "health.json" in str(err.value) and "extra.json" in str(err.value)
    out = tmp_path / "out.json"
    out.write_text("keep me")
    monkeypatch.setattr(mod, "SOURCE", src)
    assert mod.main([str(out)]) == 1
    assert out.read_text() == "keep me"
    assert "health.json" in capsys.readouterr().err


def test_t7_docs_say_it(mod):
    assert "never edit it by hand" in " ".join(mod.__doc__.split())
    assert "scripts/dashboard_fixture/" in mod.__doc__
    for rel in ("docs/guidelines.md", "reference/protocol.md"):
        text = (RUNNER.parent / rel).read_text()
        assert "scripts/dashboard_fixture/" in text, rel
        assert "make_dashboard_fixture.py" in text, rel


def test_t8_no_trailing_newline_ascii_only(mod):
    text = mod.build(mod.SOURCE)
    assert not text.endswith("\n")
    text.encode("ascii")
