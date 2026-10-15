"""s59 R5/R6: pairing old and rebased commits, and rewriting the hashes in the run state."""

from agile_team.boundary import StackEntry, UpstreamState
from agile_team.gates import StoryState
from agile_team.rewrite import Listing, Stamped, pair, parse_listing, remap_state
from agile_team.salvage import Interruption
from agile_team.state import RunState

ONTO = "0" * 40


def record(sha: str, message: str = "subject", date: str = "100 +0000") -> str:
    return f"{sha}\x1fAda\x1fada@example.com\x1f{date}\x1f{message}\x1e\n"


def stamped(sha: str, message: str) -> Stamped:
    return Stamped(sha, f"Ada\x1fada@example.com\x1f100 +0000\x1f{message}")


def test_parse_listing_reads_records_with_multi_line_messages() -> None:
    out = record("a1", "first\n\nbody line") + record("b2", "second")
    first, second = parse_listing(out)
    assert (first.sha, second.sha) == ("a1", "b2")
    assert first.stamp == "Ada\x1fada@example.com\x1f100 +0000\x1ffirst\n\nbody line"
    assert second.stamp.endswith("second")


def test_parse_listing_skips_blank_records() -> None:
    assert parse_listing("") == ()
    assert parse_listing("\n") == ()
    assert [c.sha for c in parse_listing(record("a1") + "\n")] == ["a1"]


def test_pair_all_kept_maps_one_to_one() -> None:
    old = [stamped("A", "a"), stamped("B", "b"), stamped("C", "c")]
    new = Listing(ONTO, (stamped("A2", "a"), stamped("B2", "b"), stamped("C2", "c")))
    assert pair(old, new) == {"A": "A2", "B": "B2", "C": "C2"}


def test_pair_all_dropped_maps_every_sha_to_onto() -> None:
    old = [stamped("A", "a"), stamped("B", "b")]
    assert pair(old, Listing(ONTO, ())) == {"A": ONTO, "B": ONTO}


def test_pair_a_dropped_middle_maps_to_the_previous_kept_copy() -> None:
    old = [stamped("A", "a"), stamped("B", "b"), stamped("C", "c")]
    new = Listing(ONTO, (stamped("A2", "a"), stamped("C2", "c")))
    assert pair(old, new) == {"A": "A2", "B": "A2", "C": "C2"}


def test_pair_a_dropped_first_maps_to_onto() -> None:
    old = [stamped("A", "a"), stamped("B", "b")]
    new = Listing(ONTO, (stamped("B2", "b"),))
    assert pair(old, new) == {"A": ONTO, "B": "B2"}


def test_pair_a_merge_commit_in_old_maps_to_the_previous_kept_copy() -> None:
    old = [stamped("A", "a"), stamped("M", "Merge origin/main"), stamped("B", "b")]
    new = Listing(ONTO, (stamped("A2", "a"), stamped("B2", "b")))
    assert pair(old, new) == {"A": "A2", "M": "A2", "B": "B2"}


def test_pair_of_nothing_is_empty() -> None:
    assert pair([], Listing(ONTO, ())) == {}


# ----- remap_state -----------------------------------------------------------

MOVED = {"o1": "n1", "o2": "n2", "o3": "n3", "o4": "n4", "o5": "n5", "o6": "n6", "o7": "n7"}


def seeded() -> RunState:
    st = RunState(sprint=1)
    one = StoryState("s1", "One", "tests", commit="o1", code_commits=["o2", "upstream-sha"])
    one.interrupted = Interruption("developer-cli", "s1", "b", "limit", "o3")
    st.stories["s1"] = one
    st.stories["s2"] = StoryState("s2", "Two", "design")
    st.interrupted = [Interruption("developer-cli", "s2", "b", "limit", "o4")]
    st.upstream = UpstreamState(last_end="o5", checked="o1")
    st.upstream.stack = [
        StackEntry(1, "team/sprint-1", "o6", "o7", head="o1", pushed="o3", base="o4")
    ]
    return st


def test_remap_state_rewrites_exactly_the_recorded_team_hashes() -> None:
    st = seeded()
    count = remap_state(st, MOVED)
    one = st.stories["s1"]
    assert one.commit == "n1" and one.code_commits == ["n2", "upstream-sha"]
    assert one.interrupted.sha == "n3"
    assert st.interrupted[0].sha == "n4"
    assert st.upstream.last_end == "n5"
    entry = st.upstream.stack[0]
    assert (entry.start, entry.end) == ("n6", "n7")
    assert count == 7


def test_remap_state_leaves_pushed_and_as_is_and_the_check_alone() -> None:
    st = seeded()
    st.upstream.stack[0].as_is = "o5"
    remap_state(st, MOVED)
    entry = st.upstream.stack[0]
    assert (entry.head, entry.pushed, entry.as_is, entry.base) == ("o1", "o3", "o5", "o4")
    assert st.upstream.checked == "o1"


def test_remap_state_leaves_none_empty_and_unknown_values_alone() -> None:
    st = RunState(sprint=1)
    st.stories["s1"] = StoryState("s1", "One", "tests", commit=None, code_commits=["zz"])
    st.interrupted = [Interruption("developer-cli", None, "b", "limit", None)]
    st.upstream = UpstreamState(last_end="")
    assert remap_state(st, MOVED) == 0
    assert st.stories["s1"].commit is None and st.stories["s1"].code_commits == ["zz"]
    assert st.interrupted[0].sha is None and st.upstream.last_end == ""


def test_remap_state_with_nothing_moved_changes_nothing() -> None:
    st = seeded()
    assert remap_state(st, {}) == 0
    assert st.stories["s1"].commit == "o1"


def test_a_value_mapped_to_itself_is_not_counted() -> None:
    st = RunState(sprint=1)
    st.stories["s1"] = StoryState("s1", "One", "tests", commit="o1")
    assert remap_state(st, {"o1": "o1"}) == 0
