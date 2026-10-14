"""E2E for s117: the s114 follow-ups, checked on the shipped files."""

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PO = ROOT / "agile_team/roles/product-owner.md"
FIXTURE = ROOT / "agile_team/dashboard/fixtures/snapshot.json"
SCRIBE = re.compile(r"\bscribe\b", re.IGNORECASE)


def test_ac1_word_boundary_regex_in_role_test() -> None:
    src = (ROOT / "tests/test_s114.py").read_text()
    assert r"\bscribe\b" in src
    assert not SCRIBE.search("describe and prescribe")
    assert SCRIBE.search("the Scribe's ADRs")


def test_ac1_ac2_s114_tests_pass() -> None:
    out = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "--no-header", "tests/test_s114.py"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert out.returncode == 0, out.stdout[-800:]


def test_ac2_fixture_roles_everywhere() -> None:
    snap = json.loads(FIXTURE.read_text())
    for key in ("events", "ledger", "steps"):
        assert snap[key]
        assert all(e.get("role") != "scribe" for e in snap[key])
    assert all(r["name"] != "scribe" for r in snap["roles"])


def test_ac3_missing_and() -> None:
    text = PO.read_text()
    assert "the gate's reason, and runs the manager when one is due" in text.replace("\n", " ")


def test_ac4_item_5_capitalised_and_wrapped() -> None:
    text = PO.read_text()
    block = text.split("\n5. ")[1].split("\n6. ")[0]
    assert "Calling `continue_story` also clears" in block.replace("\n   ", " ")
    assert "continue_story also clears" not in block
    for line in ("5. " + block).splitlines():
        assert len(line) <= 78
