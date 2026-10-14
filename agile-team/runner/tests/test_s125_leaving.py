"""s125: the diff the pending check reads (P10, D1, D2), leaving early (P14), serving (P16).

The real ``git diff`` of a tmp repo is the e2e test's; here ``Git`` runs on the fake system.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pytest
from agile_team import gates, pending_tests, stages, test_reports
from agile_team.boundary import StepKind
from agile_team.dispatch import Plan, Runtime, StepRequest
from agile_team.gates import StoryStatus
from agile_team.git_ops import Git
from agile_team.pending_tests import WHOLE, Registry
from agile_team.stop_checks import StopChecks

from .fake_system import FAKE_REPO, Done, FakeSystem
from .pipeline_helpers import add_story
from .s125_helpers import NEW_FAIL
from .test_s124_sprint_end import revert, setup
from .test_story_admin import clerk, requested

ENTRY = Registry({"s1": (NEW_FAIL,)})
PENDING_SUBJECT = "chore(s1): pending tests"
FILE = "agile-team/runner/tests/test_a.py"


# ---- P10: the diff and the files it names ---------------------------------------------------


def test_the_diff_pins_its_prefixes_and_quoting_whatever_the_humans_git_config(
    fake: FakeSystem,
) -> None:
    Git(FAKE_REPO).diff_lines("base1")
    (argv,) = [c.argv for c in fake.commands]
    assert argv[1:3] == ("-c", "core.quotePath=false")
    assert "--src-prefix=a/" in argv and "--dst-prefix=b/" in argv
    assert "-U0" in argv and argv[-1] == "base1"


def test_changed_for_reads_the_diff_and_the_untracked_files(fake: FakeSystem) -> None:
    diff = f"diff --git a/{FILE} b/{FILE}\n--- a/{FILE}\n+++ b/{FILE}\n@@ -3 +3,2 @@\n"
    fake.reply(("git", "diff"), Done(0, diff))
    fake.reply(("git", "ls-files"), Done(0, "tests/new.py\0"))
    got = test_reports.changed_for(Git(FAKE_REPO))("base1")
    assert got == {FILE: (range(3, 5),), "tests/new.py": (WHOLE,)}


def test_changed_for_an_empty_base_reads_nothing(fake: FakeSystem) -> None:
    assert test_reports.changed_for(Git(FAKE_REPO))("") == {}
    assert fake.commands == []


DELETED = f"""\
diff --git a/{FILE} b/{FILE}
--- a/{FILE}
+++ b/{FILE}
@@ -5 +5 @@ def test_a():
-    x = 1
+    x = 2
diff --git a/gone.py b/gone.py
deleted file mode 100644
--- a/gone.py
+++ /dev/null
@@ -1,2 +0,0 @@
-def test_g():
-    pass
"""


def test_a_deleted_file_owns_no_hunk_and_the_previous_file_is_not_credited() -> None:
    got = pending_tests.changed_lines(DELETED, [])
    assert got == {FILE: (range(5, 6),)}


def test_a_file_named_with_a_non_b_prefix_owns_no_hunk() -> None:
    diff = f"+++ w/{FILE}\n@@ -1 +1 @@\n"
    assert pending_tests.changed_lines(diff, []) == {}


# ---- P14: leaving early ---------------------------------------------------------------------


@pytest.fixture(autouse=True)
def tracked(configured: Path, fake: FakeSystem) -> None:
    fake.track()
    fake.reply(("git", "remote", "get-url"), Done(2))


def subjects(fake: FakeSystem) -> list[str]:
    return [c.subject() for c in fake.tree.commits]


def test_a_cancelled_story_drops_its_entry_in_one_pending_commit(
    make_runtime: Callable[..., Runtime], fake: FakeSystem
) -> None:
    rt = make_runtime()
    story = requested(rt)
    pending_tests.write(rt.config.repo, ENTRY)
    rt.relay.answer("m1", "cancel")
    before = subjects(fake)
    assert clerk(rt).settle() == ["s1"]
    assert pending_tests.read(rt.config.repo) == Registry()
    new = subjects(fake)[len(before) :]
    assert [s for s in new if s.startswith(PENDING_SUBJECT)] == [PENDING_SUBJECT]
    assert story.status is StoryStatus.CANCELLED


def test_a_cancel_of_a_story_with_no_entry_makes_no_pending_commit(
    make_runtime: Callable[..., Runtime], fake: FakeSystem
) -> None:
    rt = make_runtime()
    requested(rt)
    rt.relay.answer("m1", "cancel")
    clerk(rt).settle()
    assert not [s for s in subjects(fake) if s.startswith(PENDING_SUBJECT)]


def test_a_kept_story_keeps_its_entry(make_runtime: Callable[..., Runtime]) -> None:
    rt = make_runtime()
    requested(rt)
    pending_tests.write(rt.config.repo, ENTRY)
    rt.relay.answer("m1", "keep")
    clerk(rt).settle()
    assert pending_tests.read(rt.config.repo) == ENTRY


def test_a_reverted_story_drops_its_entry_in_one_pending_commit(
    make_runtime: Callable[..., Runtime], fake: FakeSystem
) -> None:
    rt, tools = setup(make_runtime)
    pending_tests.write(rt.config.repo, Registry({"s1": (NEW_FAIL,), "s2": ("x::y",)}))
    rt.git.commit([pending_tests.REGISTRY], "seed")
    rt.record_checkout()
    before = len(fake.tree.commits)
    out = revert(tools)
    assert out["status"] == "reverted"
    assert pending_tests.read(rt.config.repo) == Registry({"s2": ("x::y",)})
    new = subjects(fake)[before:]
    pending = [s for s in new if s.startswith(PENDING_SUBJECT)]
    assert pending == [PENDING_SUBJECT]


# ---- P16: serving ---------------------------------------------------------------------------


@dataclass
class Head:
    """A git that knows only HEAD."""

    sha: str = "head1"

    def head(self) -> str:
        return self.sha

    def content_digest(self, base: str) -> str:
        return "d"

    def changed_paths(self) -> list[str]:
        return []


def test_a_story_plan_starts_from_head(make_runtime: Callable[..., Runtime]) -> None:
    rt = make_runtime()
    add_story(rt, "s1", "tests")
    rt.git = Head()
    plan = rt.plan(StepRequest("unit-tester", "go", "s1"))
    assert plan.base == "head1"
    plan.stop()


def test_a_plan_with_no_story_has_no_base(make_runtime: Callable[..., Runtime]) -> None:
    rt = make_runtime()
    rt.git = Head()
    plan = rt.plan(StepRequest("manager", "review", None))
    assert plan.base == ""
    plan.stop()


def story_plan(rt: Runtime, step: str, base: str) -> Plan:
    story = add_story(rt, "s1", step)
    role = rt.resolve("developer")
    plan = Plan(role, rt.scope_for(role), story, kind=StepKind.ROLE)
    plan.base = base
    return plan


def test_gating_serves_the_plans_story_and_base(make_runtime: Callable[..., Runtime]) -> None:
    rt = make_runtime()
    plan = story_plan(rt, "implement", "base1")
    assert rt._gating(plan).checks.serving == gates.Serving("s1", "base1")


def test_gating_with_a_stop_hook_still_serves_the_story(
    make_runtime: Callable[..., Runtime],
) -> None:
    rt = make_runtime()
    plan = story_plan(rt, "implement", "base1")
    plan.stop_hook = StopChecks(rt, plan)
    pipeline = rt._gating(plan)
    assert pipeline.checks.serving == gates.Serving("s1", "base1")
    assert pipeline.checks.reuse == plan.stop_hook.reused


def test_the_runtime_serves_nothing_without_a_story(make_runtime: Callable[..., Runtime]) -> None:
    rt = make_runtime()
    role = rt.resolve("manager")
    plan = Plan(role, rt.scope_for(role), None)
    assert rt.served(plan).checks.serving == gates.Serving()


def test_the_stop_hooks_gates_serve_the_plans_story_and_base(
    make_runtime: Callable[..., Runtime],
) -> None:
    rt = make_runtime()
    plan = story_plan(rt, "implement", "base1")
    hook = StopChecks(rt, plan)
    hooked = hook._hooked(stages.Name.STOP_SUITE)
    assert hooked.checks.serving == gates.Serving("s1", "base1")


def test_the_plain_runtime_pipeline_is_not_changed_by_serving(
    make_runtime: Callable[..., Runtime],
) -> None:
    rt = make_runtime()
    rt.served(story_plan(rt, "implement", "base1"))
    assert rt.pipeline.checks.serving == gates.Serving()
