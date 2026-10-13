"""Run state in ``.team/run/state.json`` so ``start --resume`` can continue."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

from . import system
from .boundary import Boundary, Failure, StackEntry, UpstreamState
from .ci import CiResult
from .config import OLD_ENVIRONMENT_NAME, PIPELINE_STEPS
from .gates import FINISHED, PreviousStep, StoryState, StoryStatus, load_dispute
from .holds import PoHold
from .ledger import SessionCost
from .loops import Rule, Setback
from .owners import FixRecord, load_fix
from .providers import DEFAULT as DEFAULT_PROVIDER
from .roles import RETIRED_ROLES
from .salvage import RUN_ENDING, Cause, InFlight, Interruption

STATE_FILE = "state.json"
STOP_FILE = "stop"
PID_FILE = "runner.pid"


class RunStatus(StrEnum):
    """The run as a whole.

    ``sprint-end``, ``blocked`` and ``done`` are set by the PO's ``notify_user``.
    ``blocked``, ``failed``, ``stopped`` and ``checkout-changed`` are set by the runner
    when it halts (see ``halt.HALTS``). ``interrupted`` is derived by ``shown_status``
    and never stored.
    """

    IDLE = "idle"
    RUNNING = "running"
    SPRINT_END = "sprint-end"
    BLOCKED = "blocked"
    DONE = "done"
    FAILED = "failed"
    STOPPED = "stopped"
    INTERRUPTED = "interrupted"
    CHECKOUT_CHANGED = "checkout-changed"


@dataclass
class CheckoutRecord:
    """The branch the runner runs on and the commit it expects there (s61)."""

    branch: str
    head: str

    def text(self) -> str:
        """``<branch> at <sha7>``."""
        return f"{self.branch} at {self.head[:7]}"


@dataclass
class ModelOverride:
    """A PO-set model change for one role, with the logged reason."""

    model: str
    effort: str
    reason: str
    provider: str = DEFAULT_PROVIDER


@dataclass
class RunState:
    """Everything the runner needs to resume."""

    cadence: str = "sprint"
    sprint: int = 0
    po_session: str | None = None
    status: RunStatus = RunStatus.IDLE
    stories: dict[str, StoryState] = field(default_factory=dict)
    overrides: dict[str, ModelOverride] = field(default_factory=dict)
    unreviewed: list[str] = field(default_factory=list)
    manager_due: list[str] = field(default_factory=list)
    status_reason: str | None = None
    task: str = ""
    followups: dict[str, list[str]] = field(default_factory=dict)
    delivered: list[str] | None = None
    po_renew_due: list[str] = field(default_factory=list)
    po_renew_path: str = "compact"
    po_cost: SessionCost | None = None
    boundary: Boundary | None = None
    upstream: UpstreamState = field(default_factory=UpstreamState)
    goal: str = ""
    order: list[str] = field(default_factory=list)
    pulled: list[str] = field(default_factory=list)
    human_order: list[str] = field(default_factory=list)
    reorders: dict[str, str] = field(default_factory=dict)
    reorders_told: list[str] = field(default_factory=list)
    in_flight: InFlight | None = None
    interrupted: list[Interruption] = field(default_factory=list)
    checkout: CheckoutRecord | None = None
    told: list[str] = field(default_factory=list)
    unsaved: Cause | None = None
    halt_kind: str | None = None  # the HaltKind value of the halt that set the status (s44)

    def mark(self, status: RunStatus, reason: str | None = None) -> None:
        """Set the run status and why; no reason clears the old one; any halt kind is cleared."""
        self.status, self.status_reason, self.halt_kind = status, reason, None

    def runtime_overrides(self, role: str) -> dict[str, Any]:
        """Fields from a PO model override for ``role``, if any."""
        o = self.overrides.get(role)
        return {"model": o.model, "effort": o.effort, "provider": o.provider} if o else {}

    def halted(self) -> bool:
        """``done``/``blocked``/``checkout-changed`` always halt; ``sprint-end`` only on sprints."""
        if self.status in (RunStatus.DONE, RunStatus.BLOCKED, RunStatus.CHECKOUT_CHANGED):
            return True
        return self.status is RunStatus.SPRINT_END and self.cadence == "sprint"

    def unknown_stories(self, ids: list[str]) -> list[str]:
        """The ids that are not opened stories, in the order given."""
        return [i for i in ids if i not in self.stories]

    def begin_sprint(self, ids: list[str]) -> None:
        """Open the next sprint holding exactly ``ids``; other unfinished stories go back."""
        self.sprint += 1
        for sid, story in self.stories.items():
            if story.status not in FINISHED:
                story.sprint = self.sprint if sid in ids else None

    def interrupt(self, found: Interruption) -> None:
        """Record a cut-off step: pending for the PO, and offered on its story."""
        self.in_flight = None
        if found.cause in RUN_ENDING:
            self.interrupted.append(found)
        story = self.stories.get(found.story or "")
        if story and found.sha is not None:
            story.interrupted = found

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2)

    @classmethod
    def from_json(cls, text: str) -> RunState:
        data = {k: v for k, v in json.loads(text).items() if k not in RUN_DROPPED}
        data["status"] = RunStatus(data.get("status", RunStatus.IDLE))
        data["stories"] = {k: _story(v) for k, v in data.get("stories", {}).items()}
        data["overrides"] = {
            k: ModelOverride(**v)
            for k, v in data.get("overrides", {}).items()
            if k not in RETIRED_ROLES
        }
        data["po_cost"] = _nested(SessionCost, data.get("po_cost"))
        data["boundary"] = _boundary(data.get("boundary"))
        data["upstream"] = _upstream_state(data.get("upstream"))
        data["in_flight"] = _nested(InFlight, data.get("in_flight"))
        data["interrupted"] = [Interruption(**i) for i in data.get("interrupted", [])]
        data["checkout"] = _nested(CheckoutRecord, data.get("checkout"))
        data["unsaved"] = Cause(u) if (u := data.get("unsaved")) else None
        return cls(**data)


NESTED = {
    "previous": PreviousStep,
    "dispute": load_dispute,
    "interrupted": Interruption,
    "po_hold": PoHold,
}


RUN_DROPPED = frozenset({"scribe_due"})
STORY_DROPPED = frozenset({"environment", OLD_ENVIRONMENT_NAME})
PAST_IMPLEMENT = frozenset(PIPELINE_STEPS[PIPELINE_STEPS.index("implement") + 1 :])


def _legacy_implemented(data: dict[str, Any]) -> int:
    return int(data.get("step") in PAST_IMPLEMENT)


def _kept(data: dict[str, Any]) -> dict[str, Any]:
    """``data`` without the story keys the story file replaced (s94 SF6)."""
    return {k: v for k, v in data.items() if k not in STORY_DROPPED}


def _story(data: dict[str, Any]) -> StoryState:
    data = _kept(data)
    status = StoryStatus(data.get("status", StoryStatus.ACTIVE))
    nested = {k: _nested(cls, data.get(k)) for k, cls in NESTED.items()}
    implemented = data.get("implemented", _legacy_implemented(data))
    setbacks = {k: [Setback(**s) for s in data.get(k, [])] for k in ("streak", "run")}
    by = data.get("escalated_by")
    extra = {"implemented": implemented, "escalated_by": Rule(by) if by else None}
    extra |= {
        "fixes": [load_fix(f) for f in data.get("fixes", [])],
        "fixed": [FixRecord(**r) for r in data.get("fixed", [])],
    }
    return StoryState(**{**data, "status": status, **extra, **nested, **setbacks})


def _boundary(data: dict[str, Any] | None) -> Boundary | None:
    if not data:
        return None
    failure = _nested(Failure, data.get("failure"))
    streak = [Setback(**s) for s in data.get("streak", [])]
    return Boundary(**{**data, "failure": failure, "streak": streak})


def _upstream_state(data: dict[str, Any] | None) -> UpstreamState:
    data = data or {}
    stack = [
        StackEntry(**{**e, "ci": _nested(CiResult, e.get("ci"))}) for e in data.get("stack", [])
    ]
    return UpstreamState(**{**data, "stack": stack})


def _nested(cls: Callable[..., Any], data: dict[str, Any] | None) -> Any:
    return cls(**data) if data else None


def load(run_dir: Path) -> RunState:
    path = run_dir / STATE_FILE
    return RunState.from_json(system.read_text(path)) if system.is_file(path) else RunState()


def save(run_dir: Path, state: RunState) -> None:
    """Write atomically so a crash mid-write never leaves a torn state file."""
    system.make_dirs(run_dir)
    tmp = run_dir / f"{STATE_FILE}.tmp"
    system.write_text(tmp, state.to_json())
    system.replace(tmp, run_dir / STATE_FILE)


def runner_pid(run_dir: Path) -> int | None:
    """The pid in ``runner.pid``; ``None`` when missing, unreadable or not positive."""
    try:
        pid = int(system.read_text(run_dir / PID_FILE).strip())
    except (OSError, ValueError):
        return None
    return pid if pid > 0 else None


def pid_alive(pid: int) -> bool:
    """Whether a process with ``pid`` exists."""
    try:
        system.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def runner_alive(run_dir: Path) -> bool:
    """Whether the process named in ``runner.pid`` is alive."""
    pid = runner_pid(run_dir)
    return pid is not None and pid_alive(pid)


def shown_status(run_dir: Path, state: RunState) -> RunStatus:
    """The stored status, except ``running`` with no live runner reads ``interrupted``."""
    if state.status is RunStatus.RUNNING and not runner_alive(run_dir):
        return RunStatus.INTERRUPTED
    return state.status
