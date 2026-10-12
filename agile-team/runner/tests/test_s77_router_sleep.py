"""s77 PO ruling: the router keeps a deprecated `sleep` field, defaulting to system.async_sleep."""

import asyncio

from agile_team.router import POLL_S, Router

from .fake_system import FakeSystem
from .test_s47 import waiting_rt


def test_the_default_sleep_goes_through_the_system_seam(make_runtime, fake: FakeSystem) -> None:
    rt = make_runtime()
    asyncio.run(Router(rt).sleep(3.0))
    assert fake.slept[-1] == 3.0


def test_a_wait_uses_the_default_sleep_for_one_poll(make_runtime, fake: FakeSystem) -> None:
    rt = waiting_rt(make_runtime)
    fake.on_sleep = [lambda: rt.relay.answer("m1", "a")]
    asyncio.run(Router(rt).advance())
    assert fake.slept == [POLL_S]


def test_an_assigned_sleep_replaces_the_default(make_runtime, fake: FakeSystem) -> None:
    rt = waiting_rt(make_runtime)
    router = Router(rt)
    seen: list[float] = []

    async def sleep(seconds: float) -> None:
        seen.append(seconds)
        rt.relay.answer("m1", "a")

    router.sleep = sleep
    asyncio.run(router.advance())
    assert seen == [POLL_S]
    assert fake.slept == []
