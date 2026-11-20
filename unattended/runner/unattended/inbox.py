"""Messages for a prompt job's agent, delivered between its steps (``unattended tell``).

A message is a file in the job's ``inbox/`` directory, named by the time it was
posted so the oldest goes first. It is written atomically, so a run never reads
half a message. Messages are delivered, and then removed, at the first of:

- the run's next tool step, as ``additionalContext`` after the tool result (see
  ``steps``), so the cached prefix is untouched and no call is cut off;
- the next run's start, appended to its prompt, when no step came first.

Each delivery logs a ``delivered`` event with how many and where.
"""

from __future__ import annotations

import time
from datetime import datetime

from .steps import Advice
from .store import Job

INBOX = "inbox"
SUFFIX = ".md"
HEADER = "Message from the operator (unattended tell), sent {at}:"


def post_message(job: Job, text: str) -> None:
    """Queue ``text`` for the job's agent and log a ``tell`` event."""
    inbox = job.path(INBOX)
    inbox.mkdir(exist_ok=True)
    name = f"{time.time_ns():020d}"
    tmp = inbox / f".{name}.tmp"
    tmp.write_text(text)
    tmp.replace(inbox / f"{name}{SUFFIX}")
    job.event("tell", {"chars": len(text)})


def count_messages(job: Job) -> int:
    """How many messages wait for delivery."""
    inbox = job.path(INBOX)
    return len(list(inbox.glob(f"*{SUFFIX}"))) if inbox.is_dir() else 0


def take_messages(job: Job) -> list[str]:
    """Every waiting message, oldest first, each with its header; they leave the inbox."""
    inbox = job.path(INBOX)
    found = sorted(inbox.glob(f"*{SUFFIX}")) if inbox.is_dir() else []
    taken = [format_message(path.stem, path.read_text()) for path in found]
    for path in found:
        path.unlink()
    return taken


def format_message(stem: str, text: str) -> str:
    """``text`` under a header naming when it was sent."""
    at = datetime.fromtimestamp(int(stem) / 1e9).astimezone().isoformat(timespec="seconds")
    return f"{HEADER.format(at=at)}\n{text.strip()}"


def deliver_at_step(job: Job) -> Advice:
    """A step check: the waiting messages as text for the model."""
    taken = take_messages(job)
    if taken:
        job.event("delivered", {"messages": len(taken), "at": "step"})
    return Advice("\n\n".join(taken))


def deliver_at_start(job: Job, prompt: str) -> str:
    """``prompt`` with the waiting messages appended."""
    taken = take_messages(job)
    if not taken:
        return prompt
    job.event("delivered", {"messages": len(taken), "at": "start"})
    return "\n\n".join([prompt, *taken])
