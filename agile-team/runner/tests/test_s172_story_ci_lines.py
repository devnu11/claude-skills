"""s172: a red story CI carries the failing job, step and lines to the PO and the developer."""

from __future__ import annotations

from dataclasses import dataclass, field

from agile_team import ci, handover
from agile_team.ci import Bucket, Check
from agile_team.ci_triage import Job, Step
from agile_team.dispatch import StepRequest
from agile_team.gates import StoryState
from agile_team.po_tools import Start
from agile_team.story_branches import StoryCi

from .late import Late
from .pipeline_helpers import add_story
from .s29_helpers import FakePrs
from .test_s159_story_ci_rebase import ready

story_ci = Late("story_ci")
sched = Late("scheduler")
HEAD = "b" * 40
LINK = "https://github.com/o/r/actions/runs/1/job/77"
OTHER_LINK = "https://github.com/o/r/actions/runs/1/job/78"
STAMP = "2026-10-23T10:00:00.0000000Z"
SET_UP = Step("Set up job", "success")


def log(step: str, *texts: str) -> str:
    """A ``gh run view --log-failed`` log: ``job<TAB>step<TAB>timestamp text`` per line."""
    return "\n".join(f"unit\t{step}\t{STAMP} {t}" for t in texts)


def job_failing_at(step: str) -> Job:
    return Job("77", HEAD, "unit", (SET_UP, Step(step, "failure")))


@dataclass
class LogPrs(FakePrs):
    """Story-CI checks with per-link jobs and failed logs; counts the log fetches."""

    sha_list: list = field(default_factory=list)
    logs: dict = field(default_factory=dict)
    fetched: list = field(default_factory=list)

    def list_checks(self, sha: str) -> list:
        return self.sha_list

    def failed_log(self, link: str) -> str:
        self.fetched.append(link)
        return self.logs.get(link, "")


RUFF = (
    "src/a.py:3:1: F401 `os` imported but unused",
    "src/b.py:9:5: E501 Line too long (120 > 100)",
    "Found 2 errors.",
    "Error: Process completed with exit code 1.",
)


def red_poller(make_runtime, fake, step: str = "Run ruff", lines: tuple = RUFF):
    rt, story = ready(make_runtime, fake)
    story.pushed = HEAD
    rt.prs = LogPrs(
        sha_list=[Check("unit", Bucket.FAIL, "ci", LINK)],
        jobs={LINK: job_failing_at(step)},
        logs={LINK: log(step, *lines)},
    )
    return rt, story, story_ci.StoryCiPoll(rt)


def event_checks(rt) -> list[str]:
    [event] = [e for e in rt.events.events() if e.kind == "story-ci"]
    return event.data["checks"]


# ----- AC1: the story_ci event's checks name job, step, lines and link -----------------


def test_the_story_ci_checks_name_the_failing_step_ac1(make_runtime, fake) -> None:
    rt, story, poll = red_poller(make_runtime, fake)
    poll.poll(story, 1000.0)
    checks = event_checks(rt)
    assert checks[0] == f"- ci / unit: fail at step Run ruff {LINK}"


def test_the_story_ci_checks_indent_the_failing_lines_ac1(make_runtime, fake) -> None:
    rt, story, poll = red_poller(make_runtime, fake)
    poll.poll(story, 1000.0)
    assert "    src/a.py:3:1: F401 `os` imported but unused" in event_checks(rt)


def test_the_recorded_story_ci_keeps_the_checks_for_the_developer_ac1(make_runtime, fake) -> None:
    _, story, poll = red_poller(make_runtime, fake)
    got = poll.poll(story, 1000.0)
    assert got is not None and got.verdict == "red"
    assert story.ci.checks[0].startswith("- ci / unit: fail at step Run ruff")


def test_a_passing_check_is_not_listed_ac1(make_runtime, fake) -> None:
    rt, story, poll = red_poller(make_runtime, fake)
    rt.prs.sha_list.append(Check("lint", Bucket.PASS, "ci", OTHER_LINK))
    poll.poll(story, 1000.0)
    assert not any("lint" in c for c in event_checks(rt))


def test_a_failing_log_is_fetched_once_per_sha_and_check_ac1(make_runtime, fake) -> None:
    """API budget: the 60 s poll classifies a new (sha, check) once, not on every read."""
    rt, story, poll = red_poller(make_runtime, fake)
    poll.poll(story, 1000.0)
    poll.poll(story, 1000.0 + story_ci.STORY_CI_POLL_S)
    assert rt.prs.fetched == [LINK]


def test_a_green_story_ci_fetches_no_log_ac1(make_runtime, fake) -> None:
    rt, story, poll = red_poller(make_runtime, fake)
    rt.prs.sha_list = [Check("unit", Bucket.PASS, "ci", LINK)]
    poll.poll(story, 1000.0)
    assert rt.prs.fetched == []


def test_a_failing_check_without_a_job_link_still_lists_its_name_ac1(make_runtime, fake) -> None:
    rt, story, poll = red_poller(make_runtime, fake)
    rt.prs.sha_list = [Check("external", Bucket.FAIL, "", "https://other/x")]
    poll.poll(story, 1000.0)
    assert event_checks(rt) == ["- external: fail https://other/x"]


# ----- AC1: the PO's hand-over --------------------------------------------------------


def queued_lines(make_runtime, story_ci_found) -> str:
    rt = make_runtime()
    s = sched.Scheduler(rt, Start("task"))
    seen: list = []
    s.queue_pass = seen.append  # type: ignore[method-assign]
    story = StoryState(id="s1", title="t", step="implement", sprint=1)
    s.queue_story_ci(story, story_ci_found)
    [found] = seen
    return "\n".join(found.lines)


CHECKS = [
    f"- ci / unit: fail at step Run ruff {LINK}",
    "    src/a.py:3:1: F401 `os` imported but unused",
]


def test_the_hand_over_lists_the_checks_step_lines_and_link_ac1(make_runtime) -> None:
    text = queued_lines(make_runtime, StoryCi(HEAD, "red", "pr", CHECKS))
    assert "ci / unit: fail at step Run ruff" in text and LINK in text
    assert "    src/a.py:3:1: F401 `os` imported but unused" in text


def test_the_hand_over_does_not_print_the_verdict_as_a_check_ac1(make_runtime) -> None:
    text = queued_lines(make_runtime, StoryCi(HEAD, "red", "pr", CHECKS))
    assert f"{HEAD}: red" not in text


def test_the_report_lines_keep_each_indented_line_apart_ac1() -> None:
    report = {"story_ci": {"verdict": "red", "sha": HEAD, "checks": CHECKS}}
    text = "\n".join(handover.report_lines(report, "s1"))
    assert "\n    src/a.py:3:1: F401" in text


# ----- AC2: finding lines, not the tail ------------------------------------------------


def test_lint_shows_the_finding_lines_not_the_tail_ac2() -> None:
    got = ci.failing_lines(log("Run ruff", *RUFF))
    assert got[:2] == list(RUFF[:2])
    assert "Error: Process completed with exit code 1." not in got


def test_format_shows_the_files_it_would_reformat_ac2() -> None:
    texts = ("Would reformat: src/a.py", "Would reformat: src/b.py", "2 files would be reformatted")
    noise = ("uv sync done", "Error: Process completed with exit code 1.")
    got = ci.failing_lines(log("Run ruff format", *noise[:1], *texts, *noise[1:]))
    assert got[:2] == ["Would reformat: src/a.py", "Would reformat: src/b.py"]
    assert "uv sync done" not in got


def test_house_rules_shows_its_finding_lines_ac2() -> None:
    finding = "src/c.py:12: verb-name: compile_pattern is not a verb in function compile_pattern"
    tail = tuple(f"later line {i}" for i in range(12))
    got = ci.failing_lines(log("Run house-rules", "checking 40 files", finding, *tail))
    assert got == [finding]


def test_pytest_still_shows_its_failed_lines_ac2() -> None:
    failed = "FAILED tests/test_x.py::test_y - assert 1 == 2"
    got = ci.failing_lines(log("Run tests", "collected 3 items", failed, "1 failed, 2 passed"))
    assert failed in got and "collected 3 items" not in got


def test_a_log_with_no_known_pattern_still_shows_its_tail_ac2() -> None:
    got = ci.failing_lines(log("Run it", *(f"line {i}" for i in range(30))))
    assert got == [f"line {i}" for i in range(20, 30)]


def test_finding_lines_are_capped_and_not_repeated_ac2() -> None:
    many = tuple(f"src/a.py:{n}:1: F401 unused" for n in range(1, 40))
    got = ci.failing_lines(log("Run ruff", *many, many[0]))
    assert len(got) == ci.MAX_LINES and len(set(got)) == len(got)


def test_an_empty_log_has_no_lines_ac2() -> None:
    assert ci.failing_lines("") == []


# ----- AC3: the developer's brief ------------------------------------------------------


def prompt_of(rt, role: str = "developer-cli") -> str:
    return rt.user_prompt(rt.plan(StepRequest(role, "go", "s1")))


def test_the_developer_brief_holds_the_story_ci_section_ac3(make_runtime) -> None:
    rt = make_runtime()
    st = add_story(rt, step="implement")
    st.ci = StoryCi(HEAD, "red", "pr", CHECKS)
    text = prompt_of(rt)
    assert "## Story CI" in text
    assert "ci / unit: fail at step Run ruff" in text and LINK in text
    assert "    src/a.py:3:1: F401 `os` imported but unused" in text


def test_a_green_story_ci_adds_no_section_ac3(make_runtime) -> None:
    rt = make_runtime()
    st = add_story(rt, step="implement")
    st.ci = StoryCi(HEAD, "green", "pr", [])
    assert "## Story CI" not in prompt_of(rt)


def test_a_story_without_ci_adds_no_section_ac3(make_runtime) -> None:
    rt = make_runtime()
    add_story(rt, step="implement")
    assert "## Story CI" not in prompt_of(rt)


def test_a_red_story_ci_without_checks_adds_no_section_ac3(make_runtime) -> None:
    rt = make_runtime()
    st = add_story(rt, step="implement")
    st.ci = StoryCi(HEAD, "red", "pr", [])
    assert "## Story CI" not in prompt_of(rt)
