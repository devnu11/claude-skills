"""s159 C4/AC12.1: the reserve for each running step and the start refusal."""

import statistics

from agile_team import budget_reserve as br
from agile_team.ledger import Entry

WHO = ("developer", "opus", 1.0)


def entry(cost: float, **kw) -> Entry:
    return Entry(
        role=kw.pop("role", "developer"), model=kw.pop("model", "opus"), cost_usd=cost, **kw
    )


def test_fewer_than_five_steps_gives_the_floor() -> None:
    assert br.RESERVE_MIN_STEPS == 5
    assert br.reserve([entry(9.0) for _ in range(4)], WHO) == 1.0


def test_five_steps_give_mean_plus_three_sigma() -> None:
    costs = [2.0, 3.0, 4.0, 5.0, 6.0]
    expect = statistics.mean(costs) + 3 * statistics.pstdev(costs)
    got = br.reserve([entry(c) for c in costs], WHO)
    assert got in (expect, statistics.mean(costs) + 3 * statistics.stdev(costs))


def test_the_floor_wins_when_it_is_higher() -> None:
    assert br.reserve([entry(0.1) for _ in range(6)], ("developer", "opus", 2.5)) == 2.5


def test_other_roles_and_models_are_ignored() -> None:
    mixed = [entry(8.0, role="architect") for _ in range(6)]
    mixed += [entry(8.0, model="haiku") for _ in range(6)]
    assert br.reserve(mixed, WHO) == 1.0


def test_resumed_and_estimated_entries_are_excluded() -> None:
    skipped = [entry(9.0, resumed=True) for _ in range(3)]
    skipped += [entry(9.0, estimated=True) for _ in range(3)]
    assert br.reserve(skipped + [entry(2.0) for _ in range(4)], WHO) == 1.0


def test_constant_costs_have_no_spread() -> None:
    assert br.reserve([entry(3.0) for _ in range(5)], WHO) == 3.0


def test_nothing_started_at_the_edge() -> None:
    assert br.start_refusal((8.0, 10.0), [1.0, 1.0]) is not None
    assert br.start_refusal((8.0, 10.0), [1.0, 0.5]) is None
    assert br.start_refusal((10.0, 10.0), []) is not None
    assert br.start_refusal((0.0, 10.0), []) is None
