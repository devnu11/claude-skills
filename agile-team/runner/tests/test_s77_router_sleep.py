"""s77: a router wait sleeps through system.async_sleep (Z6 removed the `sleep` field)."""

import asyncio

from agile_team.router import POLL_S, Router

from .clock import about
from .fake_system import FakeSystem
from .test_s47 import waiting_rt


def test_a_wait_uses_the_default_sleep_for_one_poll(make_runtime, fake: FakeSystem) -> None:
    rt = waiting_rt(make_runtime)
    fake.on_sleep = [lambda: rt.relay.answer("m1", "a")]
    asyncio.run(Router(rt).advance())
    assert fake.slept == about([POLL_S])
