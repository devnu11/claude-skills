"""s161 AC1: the renamed functions follow the house rules; the PO tool keeps its name."""

from __future__ import annotations

import asyncio

import pytest
from agile_team import po_tools
from agile_team.dispatch import Runtime
from agile_team.landing_queue import LandingQueue
from agile_team.po_tools import Tools
from agile_team.scheduler import Scheduler


def test_the_order_landings_tool_maps_to_set_landing_order_n2() -> None:
    assert po_tools.METHODS["order_landings"] == "set_landing_order"


def test_noted_order_landings_runs_set_landing_order_n2(make_runtime) -> None:
    rt = make_runtime()
    out = asyncio.run(Tools(rt).noted("order_landings")({"stories": "s1"}))
    assert '"refused"' in out["content"][0]["text"]


@pytest.mark.parametrize(
    ("owner", "name"),
    [
        (Scheduler, "ended"),
        (Runtime, "checkout_lock"),
        (LandingQueue, "candidates"),
        (LandingQueue, "order"),
    ],
)
def test_a_no_argument_query_is_a_property_n3(owner: type, name: str) -> None:
    assert isinstance(owner.__dict__[name], property)


@pytest.mark.parametrize(
    ("owner", "old", "new"),
    [
        (LandingQueue, "next_up", "pick_next"),
        (LandingQueue, "waiting", "candidates"),
        (Runtime, "at", "get_story_view"),
    ],
)
def test_the_old_name_is_gone_n1(owner: type, old: str, new: str) -> None:
    assert not hasattr(owner, old) or old == new
    assert hasattr(owner, new)
