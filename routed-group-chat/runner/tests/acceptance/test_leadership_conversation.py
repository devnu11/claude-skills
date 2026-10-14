"""Acceptance: a full leadership conversation on examples/leadership.toml, via the CLI.

One scripted session exercises addressing, handoff, markers, sticky routing,
compaction and the `log`/`show` views together, as a user would see them.
"""

from __future__ import annotations

import json

import pytest

from ..conftest import Cli, FakeBackend

pytestmark = pytest.mark.acceptance

SCRIPT = {
    "liaison": ["Team is blocked on the CI runner.\nQUESTION: who fixes CI?"],
    "manager": [
        "I'll get platform on it today.\nRESOLVED: Q1\nDECISION: platform fixes CI by Wed",
        "Slip is one week. Scope call is the PO's.\nHANDOFF: @po",
        "Agreed.",
    ],
    "po": ["Cut search from v1.\nDECISION: search moves to v2"],
    "proxy": ["Customer accepts v1 without search."],
}


def test_full_leadership_conversation(leadership: Cli, backend: FakeBackend) -> None:
    """Relay each message as written; show the printed replies verbatim, one per role."""
    backend.replies = {name: list(lines) for name, lines in SCRIPT.items()}
    flags = ["--recent-tokens", "60"]

    # Given the human asks the liaison for status
    status = leadership.say("@liaison status?", flags)
    assert status.out.startswith("@liaison: Team is blocked")

    # When the manager is asked and resolves the open question
    fix = leadership.say("@manager can you unblock?", flags)
    assert fix.out.startswith("@manager: I'll get platform on it today.")

    # And a sticky follow-up hands the floor to the PO
    slip = leadership.say("what does that do to the date?", flags)
    assert [line.split(":")[0] for line in slip.out.split("\n\n") if line] == ["@manager", "@po"]

    # And everyone weighs in, in roster order
    final = leadership.say("@proxy @manager ok with that?", flags)
    assert final.out == "@proxy: Customer accepts v1 without search.\n\n@manager: Agreed.\n\n"

    # Then the log holds both decisions and no open questions
    log = leadership.run("log").out
    assert "- [D1] platform fixes CI by Wed (by manager)" in log
    assert "- [D2] search moves to v2 (by po)" in log
    assert "## Open questions\n- none" in log

    # And older turns were folded into the summary, the latest ones kept verbatim
    shown = leadership.run("show").out
    assert shown.startswith("--- summary ---\nSUMMARY\n")
    assert "@liaison: Team is blocked" not in shown
    kept = json.loads(leadership.state_file.read_text())["turns"]
    assert len(kept) >= 4
    assert [t["speaker"] for t in kept[-4:]] == ["po", "human", "proxy", "manager"]
