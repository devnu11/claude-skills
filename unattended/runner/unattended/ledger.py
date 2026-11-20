"""A prompt job's per-call ledger: one line in ``calls.jsonl`` per API response.

The CLI repeats one API response's usage on each content block it emits, so a
response is written once its last block has gone by: when a block of another
response arrives, or when the run ends. Each line holds the run, the response's
message id, the model, its tokens by kind (cache reads and 5-minute and 1-hour
cache writes included), their cost at the rate table (null for a model the
table lacks) and when it was written. The file is append-only and flushed per
line, so another process can follow it as the job's spend feed.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from typing import Any

from .limits import local
from .pricing import Rates, Usage, find_rate
from .store import Job

CALLS_FILE = "calls.jsonl"
type Reading = tuple[str, str, Usage]  # (message id, model, usage)


@dataclass
class Ledger:
    """Writes each API response of one run once, at its last reading."""

    job: Job
    run: int
    rates: Rates
    pending: Reading | None = None

    def note(self, reading: Reading) -> None:
        """Hold ``reading``; write the held one first when it is another response's."""
        if self.pending and self.pending[0] != reading[0]:
            self.write(self.pending)
        self.pending = reading

    def close(self) -> None:
        """Write the last response; call once the run has ended."""
        if self.pending:
            self.write(self.pending)
        self.pending = None

    def write(self, reading: Reading) -> None:
        """Append ``reading`` as one ``calls.jsonl`` line."""
        with self.job.path(CALLS_FILE).open("a") as calls:
            calls.write(json.dumps(self.describe(reading)) + "\n")
            calls.flush()

    def describe(self, reading: Reading) -> dict[str, Any]:
        """The ledger line for ``reading``."""
        message_id, model, usage = reading
        rate = find_rate(model, self.rates)
        usd = None if rate is None else round(usage.compute_cost(rate), 6)
        return {
            "run": self.run, "message_id": message_id, "model": model, "tokens": asdict(usage),
            "usd": usd, "at": local(time.time()).isoformat(timespec="seconds"),
        }  # fmt: skip


def read_calls(job: Job) -> list[dict[str, Any]]:
    """Every ledger line so far."""
    path = job.path(CALLS_FILE)
    return [json.loads(line) for line in path.read_text().splitlines()] if path.is_file() else []
