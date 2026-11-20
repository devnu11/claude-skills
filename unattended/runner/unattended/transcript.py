"""A prompt run's transcript: every prompt sent and message received, as one file per run.

``transcripts/run-<n>.jsonl`` holds one JSON line per item, in order: each prompt
the runner sends (``{"type": "prompt", "text": …}``) and each SDK message the
session yields (``{"type": "<MessageClass>", …its fields…}``). Values JSON cannot
hold are written as text. Lines are appended and flushed as they arrive, so a
crashed run keeps what it had. The transcript is for people and tools reading
the run; nothing feeds it back to the agent.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, is_dataclass
from pathlib import Path
from typing import Any

from .store import Job

TRANSCRIPTS = "transcripts"


def describe_message(message: Any) -> dict[str, Any]:
    """``message`` as a transcript line: its class name, then its fields."""
    fields = asdict(message) if is_dataclass(message) and not isinstance(message, type) else {}
    return {"type": type(message).__name__, **(fields or {"value": str(message)})}


@dataclass(frozen=True)
class Transcript:
    """The transcript file of one run."""

    job: Job
    run: int

    @property
    def path(self) -> Path:
        return self.job.path(TRANSCRIPTS) / f"run-{self.run}.jsonl"

    def record_prompt(self, text: str) -> None:
        """Append a prompt the runner sent."""
        self.write({"type": "prompt", "text": text})

    def record_message(self, message: Any) -> None:
        """Append a message the session yielded."""
        self.write(describe_message(message))

    def write(self, line: dict[str, Any]) -> None:
        """Append ``line`` and flush it."""
        self.path.parent.mkdir(exist_ok=True)
        with self.path.open("a") as transcript:
            transcript.write(json.dumps(line, default=str) + "\n")
            transcript.flush()
