"""Run one role step: a fresh ``query()`` per invocation.

A fresh query per step gives each role its own model and effort, lets the guard
hook know exactly which role is acting, and yields a per-step cost from
``ResultMessage.total_cost_usd``. After the step the runner settles the tree
(quarantine out-of-scope changes, commit the rest), checks the story's gate and
saves state. The tree is settled *before* the gate runs, so a gate never sees
changes a role was not allowed to make.
"""

from __future__ import annotations

import asyncio
import copy
import json
import tomllib
from collections.abc import AsyncIterator, Callable, Iterable, Mapping
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    HookMatcher,
    ResultMessage,
    SystemMessage,
    TextBlock,
)

from . import (
    acceptance,
    boundary,
    checkout,
    dependencies,
    git_check,
    guard,
    halt,
    handover,
    kept_sessions,
    keys,
    live,
    loops,
    ops_review,
    presentation,
    recovery,
    requirement_changes,
    requirements,
    revert_log,
    runner_tools,
    salvage,
    sandbox,
    scratch_rebase,
    shares,
    stages,
    stop_checks,
    story_rebase,
    story_spec,
    system,
)
from . import owners as owners_mod
from . import results as results_mod
from . import state as state_mod
from .boundary import BoundaryHold, StepKind
from .boundary_runner import boundary_data
from .checkout import CheckoutChanged
from .commands import CommandRunner, shell_runner
from .config import CONFIG_NAME, ENVIRONMENT_SECTION, OLD_ENVIRONMENT_NAME, Config, Environment
from .events import EVENTS, Event, EventKind, EventLog
from .gates import (
    FINISHED,
    ROUTED_COMMANDS,
    STEP_ROLES,
    UNGATED_ROLES,
    Outcome,
    Pipeline,
    Serving,
    StoryState,
    StoryStatus,
    Trace,
    Verdict,
    dispatch_refusal,
    fix_refusal,
    role_fits_step,
    ruling_refusal,
    setback_reason,
)
from .git_ops import Authored, Git, GitError
from .halt import Halt
from .insights import (
    disputes_since_review,
    friction_since_review,
    long_running_roles,
    spend_by_role,
)
from .ledger import PO_ROLE, Budget, Entry, Ledger, SessionCost, Tokens, budget_status
from .loops import Author, Setback
from .owners import Fix, FixRecord, Owners, Writer
from .priority import SOURCE_ROLES, Priority, Reorder
from .providers import Providers
from .relay import Note, Relay
from .results import Ran
from .roles import (
    Handoff,
    HandoffError,
    ResolvedRole,
    RoleBook,
    expand_globs,
    handoff_report,
    parse_handoff,
    scope_note,
)
from .run_writer import RunWriter
from .salvage import Cause, Interruption
from .stage_log import StageLog, place_of
from .state import RunState
from .story_branches import KeptSession
from .upstream import NO_PR_SERVICE, NoPrs, Prs, Upstream
from .workspaces import Workspaces

DISPUTE_OUTPUT = "Output of the test command when the dispute was raised:\n```\n{output}\n```"
GATE_CHORE = "gate: {step} on {story}"
RECORD_FAILED = "the {step} record was not committed: {error}"
QUALITY_CHORE = "quality checks for {story}"
PROXY = "customer-proxy"
INTEGRATION_TESTER = "integration-tester"
PO = PO_ROLE
MANAGER = "manager"
ARCHITECT = "architect"
GATE_EVENTS = {Verdict.DISPUTE: EventKind.TEST_DISPUTE, Verdict.ESCALATE: EventKind.ESCALATION}
SETBACKS = frozenset({Verdict.BOUNCE, Verdict.RETURN, Verdict.HOLD, Verdict.ROUTE})
PUSH_REFUSED = "pushing {branch} was refused (push_rejected): {why}; nothing was sent"
STORY_CANCELLED = "story {id} was cancelled; the step stops here"
FAULT_MISSING = 'story {id} repeated a setback; name its fault: "fault": a role or "runner"'
FAULT_UNKNOWN = 'unknown fault {fault!r}; name a role or "runner"'
RUNNER_FAULT_NOTE = (
    "Runner fault on {story}: no role can fix this setback: {reason}. "
    "The manager says: {summary} The story is blocked until the runner is fixed."
)
RULING_AFTER_FAULT = "the fault was not applied, so the ruling was not either"
NOT_NOTED = frozenset({"refused", "halted"})
DEVOPS_SECTIONS = ("toolchain", ENVIRONMENT_SECTION, OLD_ENVIRONMENT_NAME, "tool")
BOUNDARY_UNGATED = frozenset({MANAGER})
FIX_KINDS_SET = frozenset({StepKind.TEAM_FIX, StepKind.REBASE_FIX})
REBASE_FIX_ENV = {"GIT_EDITOR": "true"}
BARE_KINDS = frozenset({StepKind.GATE_FIX, StepKind.STORY_REBASE})
FIX_DISAGREES = "{role} says the failure is not theirs to fix: {summary}"
FIX_GLOBS = ("{source}", "{tests}", "{e2e}")

QueryFn = Callable[..., AsyncIterator[Any]]
PrepareFn = sandbox.PrepareFn


@dataclass(frozen=True)
class FileEdit:
    """A runner-written file: its repo-relative path, its text before and after."""

    file: str
    old: str
    new: str


@dataclass(frozen=True)
class Recorded:
    """A pass record's gate-report fields, or the hold that replaces the pass (s131)."""

    fields: dict[str, Any] = field(default_factory=dict)
    failure: Outcome | None = None


@dataclass
class StepRequest:
    """What the PO asked for: a role, its brief and (optionally) a story."""

    role: str
    brief: str
    story_id: str | None = None
    kind: StepKind = StepKind.ROLE


@dataclass
class Launch:
    """SDK launch settings beyond the role's own frontmatter."""

    system_prompt: str = ""
    env: dict[str, str] = field(default_factory=dict)
    mcp_servers: dict[str, Any] = field(default_factory=dict)
    extra_allowed: list[str] = field(default_factory=list)
    settings: dict[str, Any] | None = None
    resume: str | None = None


@dataclass
class Said:
    """The step's latest assistant text, for the Stop hook."""

    text: str = ""


@dataclass
class Plan:
    """One step: who runs, in what scope, on which story, with what prompt."""

    role: ResolvedRole
    scope: guard.Scope
    story: StoryState | None = None
    prompt: str = ""
    launch: Launch = field(default_factory=Launch)
    prepared: sandbox.Prepared | None = None
    summary: str = ""
    text: str = ""
    meter: live.Meter | None = None
    kind: StepKind = StepKind.ROLE
    commit: str | None = None
    said: Said = field(default_factory=Said)
    stop_hook: stop_checks.StopChecks | None = None
    base: str = ""
    reasons: dict[str, str] = field(default_factory=dict)
    unexplained: str = ""
    brief: str = ""
    on_session: Callable[[str], None] | None = None
    cancel: guard.StopFlag = field(default_factory=guard.StopFlag)

    @property
    def options(self) -> ClaudeAgentOptions:
        return build_options(self)

    def stop(self) -> None:
        if self.prepared:
            self.prepared.stop()


@dataclass(frozen=True)
class Staged:
    """The paths a step commit takes and the trailers its message ends with (s2)."""

    paths: list[str]
    trailers: tuple[str, ...] = ()


def _check_explained(parsed: Handoff | HandoffError, plan: Plan) -> Handoff | HandoffError:
    """``parsed``, or a bad handoff when the step's requirement edits were held back (C4)."""
    if not plan.unexplained:
        return parsed
    return requirement_changes.build_unexplained_error(parsed, plan.unexplained)


@dataclass
class StepResult:
    """What a finished ``query()`` produced."""

    text: str
    cost: float
    session_id: str | None = None
    tokens: Tokens = field(default_factory=Tokens)
    turns: int = 0
    compacted_from: int | None = None
    resumed: bool = False
    reported: float = 0.0


ISOLATION_ENV = {"ENABLE_CLAUDEAI_MCP_SERVERS": "false"}


def _hooks(plan: Plan, pre_tool: Any) -> dict[str, list[HookMatcher]]:
    hooks = {"PreToolUse": [HookMatcher(matcher=None, hooks=[pre_tool])]}
    if plan.stop_hook:
        hooks["Stop"] = [plan.stop_hook.matcher()]
    return hooks


def build_options(plan: Plan) -> ClaudeAgentOptions:
    """SDK options for one step: no user or project settings leak in."""
    role, launch = plan.role, plan.launch
    hook = guard.pre_tool_hook(plan.scope, plan.cancel)
    return ClaudeAgentOptions(
        system_prompt=launch.system_prompt,
        model=role.model,
        effort=role.effort,
        tools=list(role.tools),
        allowed_tools=[*role.tools, *launch.extra_allowed],
        permission_mode="dontAsk",
        hooks=_hooks(plan, hook),
        cwd=str(plan.scope.base),
        env={**launch.env, **ISOLATION_ENV},
        strict_mcp_config=True,
        setting_sources=[],
        mcp_servers=launch.mcp_servers,
        settings=json.dumps(launch.settings) if launch.settings else None,
        resume=launch.resume,
    )


@dataclass
class _Drain:
    """Accumulates what ``collect`` keeps from a query's messages."""

    last_text: str = ""
    result: ResultMessage | None = None
    compacted_from: int | None = None
    meter: live.Meter | None = None
    said: Said | None = None
    on_session: Callable[[str], None] | None = None

    def take(self, message: Any) -> None:
        if self.meter:
            self.meter.take(message)
        if self.on_session and _is_init(message):
            self.on_session(str(message.data.get("session_id", "")))
        self.last_text = _text_of(message) or self.last_text
        if self.said:
            self.said.text = self.last_text
        if isinstance(message, ResultMessage):
            self.result = message
        elif _is_boundary(message) and self.compacted_from is None:
            self.compacted_from = int(message.data.get("compact_metadata", {}).get("pre_tokens", 0))

    def step_result(self) -> StepResult:
        result = self.result
        if result is None:
            return StepResult(self.last_text, 0.0, compacted_from=self.compacted_from)
        tokens = Tokens.from_usage(result.usage)
        text = result.result or self.last_text
        cost = result.total_cost_usd or 0.0
        return StepResult(
            text, cost, result.session_id, tokens, result.num_turns, self.compacted_from
        )


def _is_init(message: Any) -> bool:
    return isinstance(message, SystemMessage) and message.subtype == "init"


def _is_boundary(message: Any) -> bool:
    return isinstance(message, SystemMessage) and message.subtype == "compact_boundary"


async def collect(query_fn: QueryFn, plan: Plan) -> StepResult:
    """Drain a query; keep the final text, cost, tokens, session id and compaction."""
    # tests pass bare plans
    drain = _Drain(meter=getattr(plan, "meter", None), said=getattr(plan, "said", None))
    drain.on_session = getattr(plan, "on_session", None)
    async for message in query_fn(prompt=plan.prompt, options=plan.options):
        drain.take(message)
    return drain.step_result()


def _text_of(message: Any) -> str:
    if not isinstance(message, AssistantMessage):
        return ""
    return "".join(b.text for b in message.content if isinstance(b, TextBlock))


def with_secret_denials(settings: dict[str, Any] | None, secrets: list[Path]) -> dict | None:
    """Add Read deny rules for the key files to a role's Claude Code settings."""
    if not secrets:
        return settings
    merged = dict(settings or {})
    permissions = dict(merged.get("permissions", {}))
    permissions["deny"] = [*permissions.get("deny", []), *keys.deny_rules(secrets)]
    return {**merged, "permissions": permissions}


def restrict_config(audit: guard.Audit, git: Git) -> guard.Audit:
    """A config edit may only touch ``[toolchain]``, ``[[environment]]`` and ``[[tool]]``.

    Anything else (roles, gates, team) would let a role widen its own scope on
    the next run, so such an edit is moved to the quarantine list.
    """
    if CONFIG_NAME not in audit.in_scope or config_edit_allowed(git):
        return audit
    kept = [p for p in audit.in_scope if p != CONFIG_NAME]
    return guard.Audit(audit.role, kept, [*audit.out_of_scope, CONFIG_NAME])


def config_edit_allowed(git: Git) -> bool:
    """True when the working config differs from HEAD only in owned sections."""
    try:
        before = tomllib.loads(git.run("show", f"HEAD:{CONFIG_NAME}"))
        after = tomllib.loads(system.read_text(git.repo / CONFIG_NAME))
    except (GitError, OSError, tomllib.TOMLDecodeError):
        return False
    return _without_owned(before) == _without_owned(after)


def _without_owned(data: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in data.items() if k not in DEVOPS_SECTIONS}


def commit_message(plan: Plan, subject: str) -> str:
    """``subject`` plus a body naming the role and what it reported."""
    body = f"{plan.role.name}: {plan.summary}" if plan.summary else plan.role.name
    return f"{subject}\n\n{body}"


def refused(reason: str) -> dict[str, Any]:
    return {"status": "refused", "reason": reason}


def halted_report(role: str, found: Halt) -> dict[str, Any]:
    """The PO's report for a step cut short by a halt."""
    return {
        "status": "halted",
        "role": role,
        "reason": found.reason,
        "next": "the run is stopping; end your turn",
    }


def _halt_text(state: RunState) -> str:
    reason = f" ({state.status_reason})" if state.status_reason else ""
    return f"the run is {state.status}{reason}; end your turn"


@dataclass
class RunFlags:
    """The run's halt flags, shared by the runtime and every story view of it (B3)."""

    halted_by: Halt | None = None
    running: set[str] = field(default_factory=set)
    save_pending: bool = False
    stops: dict[str, guard.StopFlag] = field(default_factory=dict)
    limited: Halt | None = None


@dataclass
class Runtime:
    """The live run: config, roles, git, ledger, relay, state and pipeline."""

    config: Config
    book: RoleBook
    git: Git
    ledger: Ledger
    relay: Relay
    state: RunState
    env: dict[str, str]
    query_fn: QueryFn
    pipeline: Pipeline
    prepare_fn: PrepareFn = field(default_factory=lambda: sandbox.Preparer().prepare)
    secrets: list[Path] = field(default_factory=list)
    providers: Providers = field(default_factory=Providers)
    upstream: Upstream | None = None
    prs: Prs = field(default_factory=lambda: NoPrs(NO_PR_SERVICE))
    shell: Callable[[Path], CommandRunner] = shell_runner
    pipeline_for: Callable[[Config], Pipeline] | None = None
    writer: RunWriter = field(default_factory=RunWriter)
    flags: RunFlags = field(default_factory=RunFlags)
    worktree_of: str | None = None
    main_git: Git | None = None
    revert_queue: list[Any] = field(default_factory=list)
    events: EventLog = field(init=False)
    pulse: live.Pulse = field(init=False)
    stage_log: StageLog = field(init=False)
    results: results_mod.Results = field(init=False)
    step_meter: live.Meter | None = field(default=None, init=False)

    def __post_init__(self) -> None:
        self.events = EventLog(self.config.run_dir / EVENTS)
        self.pulse = live.Pulse(self.config.run_dir, self.config.health.beat_s)
        self.stage_log = StageLog(self.events, self.pulse, board=self.pulse)
        self.pipeline.checks.stages = self.stage_log.open
        self.results = results_mod.Results(self.config.run_dir)
        if self.upstream is None:
            self.upstream = Upstream(self.git, self.config.upstream)
        if self.pipeline_for is None:
            self.pipeline_for = self._get_pipeline
        self.events.writer = self.ledger.writer = self.writer

    @property
    def main(self) -> Git:
        """Git in the main checkout, also from a story's view."""
        return self.main_git or self.git

    def _get_pipeline(self, config: Config) -> Pipeline:
        return self.pipeline

    @property
    def halted_by(self) -> Halt | None:
        """The run's first halt, shared with every story view."""
        return self.flags.halted_by

    @halted_by.setter
    def halted_by(self, found: Halt | None) -> None:
        self.flags.halted_by = found

    def at(  # house-rules: allow verb-name -- name fixed by the s159 tests
        self,
        story: StoryState,
    ) -> Runtime:
        """B3: the run seen from one story's worktree; every run file stays shared."""
        path = Workspaces(self.git, self.config).path_of(story.id)
        view = copy.copy(self)
        view.config = self.config.at_worktree(path)
        view.git = Git(path, self.git.options)
        view.pipeline = self.pipeline_for(view.config)  # type: ignore[misc]
        view.step_meter, view.worktree_of = None, story.id
        view.main_git = self.main
        view.stage_log = copy.copy(self.stage_log)
        view.pipeline.checks.stages = view.stage_log.open
        return view

    def emit(self, kind: EventKind, plan: Plan | None = None, /, **data: Any) -> Event:
        """Log an event, attributed to ``plan``'s role and story when given."""
        role = plan.role.name if plan else None
        story = plan.story.id if plan and plan.story else None
        return self.events.emit(Event(kind, role, story, data))

    def save(self) -> None:
        """Submit a coalesced save of ``state.json`` to the writer (C6)."""
        self.writer.check_owner()
        if self.flags.save_pending:
            return
        self.flags.save_pending = True
        self.writer.submit(self._write_state)

    def _write_state(self) -> None:
        self.flags.save_pending = False
        state_mod.save(self.config.run_dir, self.state)

    def report_load_faults(self) -> None:
        """Emit one run-level ``fault`` event per value dropped at load, then clear and save."""
        faults = self.state.load_faults
        if not faults:
            return
        for f in faults:
            self.emit(EventKind.FAULT, fault="state", **asdict(f))
        self.state.load_faults = []
        self.save()

    def stop_requested(self) -> bool:
        return system.exists(self.config.run_dir / state_mod.STOP_FILE)

    def resolve(self, name: str) -> ResolvedRole:
        return self.book.resolve(name, self.state.runtime_overrides(name))

    def scope_for(self, role: ResolvedRole) -> guard.Scope:
        """Guard scope from the role's globs with placeholders expanded."""
        values = self.config.placeholders()
        write, read = expand_globs(role.write, values), expand_globs(role.read, values)
        return guard.Scope(role.name, self.config.repo, write, read, secrets=self.secrets)

    # ----- refusal -------------------------------------------------------

    def refusal(self, request: StepRequest) -> str | None:
        """Why the requested step may not run now, or ``None``."""
        checks = (self._run_refusal, self._role_refusal, self._story_refusal)
        return next((reason for reason in (c(request) for c in checks) if reason), None)

    def _run_refusal(self, request: StepRequest) -> str | None:
        if self.stop_requested():
            return "a stop was requested; end your turn"
        if self.state.halted():
            return _halt_text(self.state)
        if self.state.manager_due and self.is_held_by_review(request):
            return "manager review due: " + "; ".join(self.state.manager_due)
        return None

    @staticmethod
    def is_held_by_review(request: StepRequest) -> bool:
        """AC6.8: the Manager review blocks the storyless steps, never a story's step."""
        free = request.role == MANAGER or request.kind in FIX_KINDS_SET
        return not (free or request.story_id)

    def _role_refusal(self, request: StepRequest) -> str | None:
        return None if request.role in self.book.names() else f"unknown role {request.role!r}"

    def _story_refusal(self, request: StepRequest) -> str | None:
        sid = request.story_id
        if sid and sid not in self.state.stories:
            return f"unknown story {sid!r}; ask the liaison for it with request_story"
        if sid in self.relay.blocked_stories():
            return f"story {sid} is blocked waiting on an answer"
        story = self.state.stories.get(sid or "")
        check = STORY_REFUSALS.get(request.kind, dispatch_refusal)
        return self._boundary_refusal(request.role, story) or check(request.role, story)

    def _boundary_refusal(self, role: str, story: StoryState | None) -> str | None:
        """Sprint stories wait while a boundary is pending (the Manager may run)."""
        b = self.state.boundary
        if b is None or story is None or story.sprint != self.state.sprint:
            return None
        if role in BOUNDARY_UNGATED:
            return None
        return boundary.BOUNDARY_REFUSAL.format(
            sprint=b.sprint, edge=b.edge, stage=b.stage, held=boundary.held_text(b)
        )

    # ----- planning ------------------------------------------------------

    def plan(self, request: StepRequest) -> Plan:
        """Resolve the role and build its scope, prompt and launch settings."""
        role = self.resolve(request.role)
        story = self.state.stories.get(request.story_id or "")
        plan = Plan(role, self.scope_for(role), story, request.brief, kind=request.kind)
        plan.brief = request.brief
        if story:
            plan.base = self.git.head()
        try:
            self._set_up(plan, request.kind)
            return self.finish(plan)
        except Exception:
            plan.stop()
            raise

    def _told_revert(self, plan: Plan) -> Plan:
        """R8: the role has the revert note now; it is not owed it again."""
        owed = plan.story.revert_owed if plan.story else []
        if plan.role.name in owed:
            owed.remove(plan.role.name)
            self.save()
        return plan

    def _set_up(self, plan: Plan, kind: StepKind) -> None:
        if kind not in BARE_KINDS:
            self._role_set_up(plan)
        if kind in FIX_SETUPS:
            FIX_SETUPS[kind](self, plan)
        if kind in stop_checks.STOP_HOOK_KINDS:
            plan.stop_hook = stop_checks.StopChecks(self, plan)
        self._confine_git(plan)

    def _role_set_up(self, plan: Plan) -> None:
        setups = {PROXY: self._attach_environment, INTEGRATION_TESTER: self._lay_out_presentation}
        if plan.role.name in setups:
            setups[plan.role.name](plan)
        step = fitting_step(plan.role.name, STEP_SETUPS)
        if step:
            STEP_SETUPS[step](self, plan)
        self._attach_requirements(plan)
        self._attach_shares(plan)

    def _attach_requirements(self, plan: Plan) -> None:
        """Add the ``## Requirements`` section to a checked story's brief (s1 T13)."""
        section = requirements.BRIEFS.get(plan.role.name)
        if section and plan.story is not None and plan.story.trace is Trace.CHECKED:
            plan.prompt += "\n\n" + section(requirements.load(self.config), plan.story.id)

    def _attach_shares(self, plan: Plan) -> None:
        """Add the ``## Shared files`` section to a story-bound brief (s120 S9)."""
        if plan.story is None:
            return
        found = shares.listed_of(self.config, plan.story.id)
        if section := shares.brief_section(found, shares.Brief(plan.story.id, plan.role.name)):
            plan.prompt += "\n\n" + section

    def _confine_git(self, plan: Plan) -> None:
        """Confine a GIT_CONFINED step's git to its workspace and set git's ceiling (G2)."""
        step = fitting_step(plan.role.name, GIT_CONFINED)
        if step is None:
            return
        self._set_git_workspace(plan, GIT_CONFINED[step](self, plan))

    def _set_git_workspace(self, plan: Plan, path: Path) -> None:
        """Confine the step's git to ``path`` and set git's ceiling (G2)."""
        plan.scope.git_workspace = system.resolve(path)
        env = {**(plan.launch.env or self.env), **git_check.git_env(self.config.run_dir)}
        plan.launch.env = env

    def _presentation_workspace(self, plan: Plan) -> Path:
        return presentation.story_root(self.config, plan.story.id)  # type: ignore[union-attr]  # story-bound role

    def _proxy_workspace(self, plan: Plan) -> Path:
        return presentation.copied_workspace(plan.prepared.root)  # type: ignore[union-attr]  # proxy has a sandbox

    def _attach_runner_tools(self, plan: Plan) -> None:
        """Give a developer step the runner's named-test tools (R1)."""
        server = runner_tools.mcp_server(runner_tools.RunnerTools(self, plan))
        plan.launch.mcp_servers = {**plan.launch.mcp_servers, runner_tools.SERVER: server}
        plan.launch.extra_allowed = [*plan.launch.extra_allowed, *runner_tools.tool_names()]

    def _run_quality_checks(self, plan: Plan) -> None:
        """Lint, static and (unless kept at HEAD) coverage before the quality czar (Q1-Q3)."""
        if plan.story is None:
            return
        with self.pulse.doing(QUALITY_CHORE.format(story=plan.story.id)):
            for name in self._quality_due(plan.story):
                checks = self.pipeline.serving(Serving(plan.story.id)).checks
                self._keep(plan.story, checks.ran(name), "before quality")

    def _quality_due(self, story: StoryState) -> list[str]:
        """The configured ROUTED_COMMANDS, plus coverage when its kept run is not at HEAD (Q2)."""
        commands = self.pipeline.checks.commands
        due = [name for name in ROUTED_COMMANDS if commands.get(name)]
        kept = self.results.latest(story.id, "coverage")
        return due if kept and kept.at == self.git.head() else [*due, "coverage"]

    def _keep(self, story: StoryState, ran: Ran, where: str) -> None:
        """Store a run with HEAD and where it ran (B2, Q1)."""
        self.results.keep(story.id, replace(ran, at=self.git.head(), where=where))

    def _team_fix_scope(self, plan: Plan) -> None:
        """A team-branch fix may also write source, tests and e2e tests."""
        values = self.config.placeholders()
        wanted = expand_globs(list(FIX_GLOBS), values)
        plan.scope.write = [*plan.scope.write, *(g for g in wanted if not g.startswith("!"))]

    def _set_rebase_fix_scope(self, plan: Plan) -> None:
        """A rebase fix may write only the scratch worktree, and its git is confined there."""
        failure = self.state.boundary.failure if self.state.boundary else None
        stopped = Path(failure.worktree) if failure and failure.worktree else None
        worktree = stopped or self.config.run_dir / scratch_rebase.REBASE_DIR
        rel = worktree.relative_to(self.config.repo).as_posix()
        plan.scope.write = [f"{rel}/**"]
        self._set_git_workspace(plan, worktree)
        plan.launch.env = {**plan.launch.env, **REBASE_FIX_ENV}

    def _set_story_rebase_scope(self, plan: Plan) -> None:
        """S2: the rebase step writes only the conflicting files, in the story's worktree."""
        rebase = plan.story.rebase  # type: ignore[union-attr]
        plan.scope.write = list(rebase.files)
        story_rebase.prepare(self.git, rebase)
        plan.launch.env = {**(plan.launch.env or self.env), **REBASE_FIX_ENV}
        lines = story_rebase.STORY_REBASE_LINES
        values = {"id": plan.story.id, "files": ", ".join(rebase.files)}  # type: ignore[union-attr]
        values |= {"onto": rebase.onto, "base": rebase.base, "branch": rebase.branch}
        plan.prompt += "\n\n" + "\n\n".join(line.format(**values) for line in lines)

    def _lay_out_presentation(self, plan: Plan) -> None:
        with self.stage_log.open(stages.Name.PRESENTATION_LAYOUT):
            presentation.lay_out(self.config, plan.story)  # type: ignore[arg-type]  # story-bound role
        section = presentation.layout_section(self.config, plan.story.id)  # type: ignore[union-attr]
        plan.prompt += f"\n\n{section}".rstrip()

    def _attach_environment(self, plan: Plan) -> None:
        environment = self._environment_for(plan)
        if environment is None:
            raise sandbox.SandboxError("no [[environment]] is configured for the customer proxy")
        with self.stage_log.open(stages.Name.ENV_PREPARE):
            plan.prepared = self.prepare_fn(self.config, self._order(environment, plan.story))
        role_writes, plan.scope = plan.scope.write, sandbox.proxy_scope(self.config, plan.prepared)
        plan.scope.write += role_writes
        self._fit_role_to_environment(plan)

    def _environment_for(self, plan: Plan) -> Environment | None:
        """The story's due environment (AE7); the first configured without a story."""
        if plan.story is None:
            return self.config.environment(None)
        names = tuple(story_spec.environment_names(self.config, plan.story.id))
        due = acceptance.Round(names, tuple(plan.story.tried)).due()
        return self.config.environment(due) if due else None

    def _order(self, environment: Environment, story: StoryState | None) -> sandbox.Order:
        showing = presentation.Showing(story.id, environment) if story else None
        shared = shares.listed_of(self.config, story.id).paths() if story else ()
        source = presentation.presented_source(self.config, showing)
        return sandbox.Order(environment, source, shared)

    def _fit_role_to_environment(self, plan: Plan) -> None:
        prepared = plan.prepared
        allowed = [t for t in plan.role.tools if t in prepared.kind.tools]
        plan.role.tools = allowed or list(prepared.kind.tools)
        plan.prompt += f"\n\n## How the customer reaches the product\n\n{prepared.guidance()}"
        plan.prompt += f"\n\n{presentation.prompt_section(prepared.presentation)}".rstrip()
        plan.prompt += self._criteria_section(plan)
        plan.launch = self._sandbox_launch(prepared)

    def _criteria_section(self, plan: Plan) -> str:
        spec = story_spec.read(self.config, plan.story.id).spec if plan.story else None
        if spec is None:
            return ""
        return f"\n\n{acceptance.brief_section(spec, plan.prepared.environment.name)}"  # type: ignore[union-attr]  # proxy has a sandbox

    def _sandbox_launch(self, prepared: sandbox.Prepared) -> Launch:
        servers = prepared.mcp_servers()
        return Launch(
            env={**prepared.env, **self.env},
            mcp_servers=servers,
            extra_allowed=[f"mcp__{name}" for name in servers],
            settings=sandbox.os_sandbox_settings(self.config, prepared),
        )

    def finish(self, plan: Plan) -> Plan:
        """Fill the prompt, system prompt, environment and settings for a step."""
        plan.scope.secrets = self.secrets
        plan.prompt = self.user_prompt(plan)
        note = scope_note(plan.scope.write, plan.scope.read)
        plan.launch.system_prompt = self.book.system_prompt(plan.role, note)
        plan.launch.env = {**(plan.launch.env or self.env), **self.providers.env_for(plan.role)}
        plan.launch.settings = with_secret_denials(plan.launch.settings, self.secrets)
        plan.launch.resume = plan.launch.resume or self._find_kept_session(plan)
        return plan

    def _find_kept_session(self, plan: Plan) -> str | None:
        """K1: the story's kept session of this role, when nothing about the role changed."""
        if plan.story is None or plan.prepared is not None:
            return None
        return kept_sessions.resume_of(plan.story, plan.role)

    def user_prompt(self, plan: Plan) -> str:
        parts = [plan.prompt]
        parts.extend(_story_lines(plan.story, []))
        if plan.story:
            found = self.results.shown(plan.story.id, plan.story.step)
            parts.append(results_mod.section(found))
            parts.append(self._revert_note(plan, plan.story))
        if plan.role.name == MANAGER:
            parts.append(self._manager_context(plan.story))
        parts.append(followup_section(self.state.followups.get(plan.role.name, [])))
        return "\n\n".join(p for p in parts if p)

    def _revert_note(self, plan: Plan, story: StoryState) -> str:
        """R8-R9: the revert brief, to a role owed it and to every design brief."""
        if plan.role.name in story.revert_owed or story.step == revert_log.DESIGN_STEP:
            return revert_log.brief_section(story.reverted, story.step)
        return ""

    def _manager_context(self, story: StoryState | None = None) -> str:
        overrides = {r: vars(self.state.overrides[r]) for r in self.state.unreviewed}
        capped = [
            s.id
            for s in self.state.stories.values()
            if s.status is StoryStatus.NEEDS_MANAGER and s.repeated is None
        ]
        context = {
            "review_reasons": self.state.manager_due,
            "unreviewed_overrides": overrides,
            "stories_at_round_cap": capped,
            "budget": budget_status(self.ledger, self.config.team.budget_usd),
            "spend_by_role": spend_by_role(self.ledger),
            "long_running_roles": long_running_roles(self.ledger),
            "friction_since_last_review": friction_since_review(self.events.events()),
            "test_disputes_since_last_review": disputes_since_review(self.events.events()),
            "pending_followups": self.state.followups,
            **self._repeated_context(story),
            **self._boundary_context(),
        }
        return "Runner context:\n" + json.dumps(context, indent=2)

    def _boundary_context(self) -> dict[str, Any]:
        b = self.state.boundary
        if b is None or b.escalated is None:
            return {}
        return {"repeated_boundary": boundary.manager_view(b, self.events.events())}

    def _repeated_context(self, story: StoryState | None) -> dict[str, Any]:
        if story is None or story.repeated is None:
            return {}
        return {
            "repeated_setback": {
                **loops.manager_view(story, self.events.events()),
                "code": self.pipeline.checks.code_facts(story),
            }
        }

    # ----- running -------------------------------------------------------

    async def run_role(self, request: StepRequest) -> dict[str, Any]:
        """Run one role step end to end and return a report for the PO; log any crash."""
        reason = self.refusal(request)
        if reason:
            return refused(reason)
        story = self.state.stories.get(request.story_id or "")
        if self.uses_worktree(request, story):
            return await self.run_in_worktree(request, story)  # type: ignore[arg-type]
        return await self.run_here(request)

    def uses_worktree(self, request: StepRequest, story: StoryState | None) -> bool:
        """B3: with story branches on, a story's role step runs in the story's worktree."""
        on = self.state.story_branches and self.worktree_of is None
        return bool(on and story is not None and request.kind in WORKTREE_KINDS)

    async def run_in_worktree(self, request: StepRequest, story: StoryState) -> dict[str, Any]:
        """Make the story's branch and worktree, then run the step in a view of the run."""
        refused_report = await self.writer.apply(lambda: self.prepare_story(story))
        if refused_report is not None:
            return refused_report
        self.flags.running.add(story.id)
        try:
            return await self.at(story).run_here(request)
        finally:
            self.flags.running.discard(story.id)

    async def run_here(self, request: StepRequest) -> dict[str, Any]:
        """Run the step in this runtime's checkout; log any crash."""
        try:
            report = await self._placed_step(request)
        except CheckoutChanged as moved:
            return halted_report(request.role, moved.halt)
        except Exception as exc:
            halt.log_traceback(self.config.run_dir, exc)
            raise
        self.enforce_ceiling()
        return report

    @property
    def sprint_head(self) -> str:
        """The sprint branch's head: the sprint entry's, else the main checkout's."""
        entry = boundary.find_current_entry(self.state.upstream.stack, self.state.sprint)
        return entry.head if entry and entry.head else self.git.head()

    def prepare_story(self, story: StoryState) -> dict[str, Any] | None:
        """B1, B5: give the story its branch and worktree; a refusal report if it drifted."""
        space = Workspaces(self.git, self.config)
        path = space.path_of(story.id)
        if story.worktree_head and system.is_dir(path):
            drift = checkout.check_worktree(Git(path, self.git.options), story)
            if drift is not None:
                return self._report_drift(story, space.changed_files(story.id), path)
        self._make_workspace(story, space)
        return None

    def _make_workspace(self, story: StoryState, space: Workspaces) -> None:
        """B1: fork the branch at the sprint head, or rebuild the worktree of a kept branch."""
        action = "rebuilt" if story.branch else "created"
        head = self.sprint_head
        if story.branch and not story.worktree_head and story.base_sha != head:
            return self._run_returning_replay(story, head)
        space.ensure(story, head)
        data = {"action": action, "branch": story.branch, "base_sha": story.base_sha}
        self.events.emit(
            Event(EventKind.STORY_BRANCH, None, story.id, data | {"replays": story.replays})
        )
        self.save()

    def _run_returning_replay(self, story: StoryState, head: str) -> None:
        """A kept branch starts again on an older base: replay it onto the sprint head (R8)."""
        from .replay import StoryReplay
        from .story_ci import StoryPusher

        old_pr = story.pr
        if StoryReplay(self).run(story, head).outcome.value == "rebased":
            StoryPusher(self).push_replayed(story, old_pr)
        self.save()

    def _report_drift(self, story: StoryState, files: list[str], path: Path) -> dict[str, Any]:
        """B5: the worktree changed outside the team; the story holds and names the files."""
        story.drift = files
        self.save()
        reason = f"story {story.id}'s worktree {path} changed outside the team: {', '.join(files)}"
        return {**refused(reason), "drift": {"path": str(path), "files": files}}

    async def _placed_step(self, request: StepRequest) -> dict[str, Any]:
        """Run the step with its stages attached to the requested story and step."""
        story = self.state.stories.get(request.story_id or "")
        with self.stage_log.within(place_of(story)):
            return await self._run_step(request)

    async def _run_step(self, request: StepRequest) -> dict[str, Any]:
        """Settle the PO, return an unpresented request or run the planned step, then note it."""
        if self.worktree_of is None:
            self.settle_po()
        report = (
            self._unready(request)
            or self._unpresented(request)
            or await self._plan_and_run(request)
        )
        self._note_if_ran(request, report)
        return report

    def _note_if_ran(self, request: StepRequest, report: dict[str, Any]) -> None:
        story = self.state.stories.get(request.story_id or "")
        if story and report["status"] not in NOT_NOTED:
            self.note_step(story, report)

    async def _plan_and_run(self, request: StepRequest) -> dict[str, Any]:
        try:
            plan = self.plan(request)
        except sandbox.NotUp as exc:
            return self._not_up(request, exc)
        except sandbox.SandboxError as exc:
            return refused(str(exc))
        await self.take_off(plan)
        return await self._run_planned(plan)

    async def take_off(self, plan: Plan) -> None:
        """Announce the step and record it as in flight (applied by the writer)."""
        await self.writer.apply(lambda: self._take_off(plan))

    def _take_off(self, plan: Plan) -> None:
        self._told_revert(plan)
        if plan.story is not None:
            self.flags.stops[plan.story.id] = plan.cancel
        step = plan.story.step if plan.story else None
        self.emit(EventKind.STEP_START, plan, brief=plan.brief, step=step, **self.pulse.clocks())
        plan.on_session = lambda sid: self._keep_init_session(plan, sid)
        flying = salvage.InFlight(plan.role.name, plan.story.id if plan.story else None, plan.brief)
        self._mark_in_flight(plan, flying)
        plan.meter = self.step_meter = self.pulse.open(self.who(plan))
        self.save()

    def _mark_in_flight(self, plan: Plan, flying: salvage.InFlight) -> None:
        """I1: a story step in its worktree records itself on the story; any other on the run."""
        if self.worktree_of is not None and plan.story is not None:
            plan.story.in_flight = flying
        else:
            self.state.in_flight = flying

    def _keep_init_session(self, plan: Plan, session: str) -> None:
        """I1: the session id arrives with the SDK's init message; keep it with the step."""
        story = plan.story
        if story is not None and story.in_flight is not None and session:
            story.in_flight = replace(story.in_flight, session=session)

    def who(self, plan: Plan) -> live.Who:
        """What the live meter measures for ``plan``."""
        story = plan.story
        billing = self.providers.billing(plan.role)
        return live.Who(
            plan.role.name, story.id if story else None, story.step if story else None,
            plan.role.model, billing,
        )  # fmt: skip

    def _end_meter(self) -> live.Meter | None:
        """Take the open step's meter (once) and close it; ``None`` when already taken (I1)."""
        meter, self.step_meter = self.step_meter, None
        if meter is not None:
            self.pulse.close(meter)
        return meter

    def _close_interrupted(self, cause: Cause) -> None:
        """Emit the open step's ``interrupted`` step-end, if nobody has ended it yet (I2)."""
        meter = self._end_meter()
        if meter is not None:
            reason = self.halted_by.reason if self.halted_by else None
            self.events.emit(meter.interrupted(live.Stop(cause, reason)))

    def _land(self, plan: Plan) -> None:
        """The step settled: nothing is in flight and its offered work is spent."""
        self.state.in_flight = None
        if plan.story:
            plan.story.interrupted = None
            plan.story.in_flight = None
        self.save()

    def note_step(self, story: StoryState, report: dict[str, Any]) -> None:
        """Record a story step: its hold and its gated previous step."""
        story.hold = handover.hold_reason(report)
        previous = handover.previous_step(report)
        if previous and report.get("role") not in UNGATED_ROLES:
            story.previous = previous
        self.save()

    def _unready(self, request: StepRequest) -> dict[str, Any] | None:
        """Hold a Proxy request whose story file has problems, billing nothing (SF7)."""
        story = self.state.stories.get(request.story_id or "")
        outcome = self.pipeline.unready(story) if story and request.role == PROXY else None
        return self._returned(request, outcome) if outcome else None

    def _unpresented(self, request: StepRequest) -> dict[str, Any] | None:
        """Return a Proxy request on an unpresented story to e2e, billing nothing."""
        story = self.state.stories.get(request.story_id or "")
        outcome = self.pipeline.unpresented(story) if story and request.role == PROXY else None
        return self._returned(request, outcome) if outcome else None

    def _not_up(self, request: StepRequest, exc: sandbox.NotUp) -> dict[str, Any]:
        """Return the story to e2e when its service did not start; refuse without an e2e step."""
        outcome = self.pipeline.return_to_e2e(str(exc))
        if outcome is None or request.story_id not in self.state.stories:
            return refused(str(exc))
        return self._returned(request, outcome)

    def _returned(self, request: StepRequest, outcome: Outcome) -> dict[str, Any]:
        role = self.resolve(request.role)
        story = self.state.stories[request.story_id or ""]
        report = self._advance_and_log(Plan(role, self.scope_for(role), story), outcome)
        self.save()
        return {"status": "returned", "role": PROXY, "reason": outcome.reason, "gate": report}

    async def _run_planned(self, plan: Plan) -> dict[str, Any]:
        try:
            result = await self._execute(plan)
            if plan.cancel.requested:
                return self._end_stopped(plan)
            settled = await self.settle_work(plan, result)
            return await self.apply_settled(plan, settled)
        except asyncio.CancelledError:
            if self.worktree_of is not None:
                self.save_interrupted(Cause.SIGTERM)
            raise
        except Exception as exc:
            return self._step_failed(plan, exc)

    def stop_step(self, story_id: str, reason: str) -> bool:
        """C8: ask the story's running step to end at its next tool call; True if one runs."""
        flag = self.flags.stops.get(story_id)
        if flag is None or story_id not in self.flags.running:
            return False
        flag.requested, flag.reason = True, reason
        return True

    def release_cancelled(self, story: StoryState) -> None:
        """E1, C8: a cancelled story's step stops at a safe point; its worktree goes."""
        if not self.stop_step(story.id, STORY_CANCELLED.format(id=story.id)):
            self.drop_worktree(story)

    def drop_worktree(self, story: StoryState) -> None:
        """E1: remove the worktree and keep the branch."""
        if story.worktree_head:
            Workspaces(self.main, self.config).remove(story.id)
            story.worktree_head = ""
            self.save()

    def recover_stories(self, cause: Cause) -> None:
        """I2, I3: on a resume, prune stale worktrees and mark each cut-off story step stopped."""
        pinned = self.state.boundary is not None and self.state.boundary.replay is not None
        kept = {s.id for s in self.state.stories.values() if s.in_flight}
        Workspaces(self.main, self.config).prune_stale(
            frozenset(kept | ({"replay"} if pinned else set()))
        )
        for story in self.state.stories.values():
            if story.in_flight is not None:
                self._resume_story(story, cause)
        self.save()

    def _resume_story(self, story: StoryState, cause: Cause) -> None:
        """I2: the cut-off step ends as stopped, its session is kept, its worktree is offered."""
        flying = story.in_flight
        assert flying is not None
        if not self._has_ended(story, flying.role):
            data = {"status": "stopped", "interrupted": str(cause)}
            self.events.emit(Event(EventKind.STEP_END, flying.role, story.id, data))
        role = self.resolve(flying.role)
        if flying.session:
            kept = KeptSession(flying.session, role.model, role.effort, role.provider)
            story.sessions[flying.role] = kept
        story.interrupted = Interruption(cause, flying.role, story.id, flying.brief, None)
        story.in_flight = None

    def _has_ended(self, story: StoryState, role: str) -> bool:
        """True when the latest step of ``role`` on the story has a step-end."""
        for event in reversed(self.events.events()):
            marks = event.kind in (EventKind.STEP_START, EventKind.STEP_END)
            if event.role == role and event.story == story.id and marks:
                return event.kind is EventKind.STEP_END
        return True

    def _end_stopped(self, plan: Plan) -> dict[str, Any]:
        """C8: a cancelled story's step ends here: no commit and no gate."""
        self.flags.stops.pop(plan.story.id, None)  # type: ignore[union-attr]
        self._end_meter()
        self._land(plan)
        self.drop_worktree(plan.story)  # type: ignore[arg-type]
        return {"role": plan.role.name, "status": "stopped", "reason": plan.cancel.reason}

    async def settle_work(self, plan: Plan, result: StepResult) -> dict[str, Any]:
        """The blocking half of a step's end: handoff, tree, quarantine, commit and gate.

        It runs on the loop thread: every state change stays with the one writer (C6), so a
        long gate delays the other stories' tasks but never races them.
        """
        return self.settle(plan, result)

    async def apply_settled(self, plan: Plan, settled: dict[str, Any]) -> dict[str, Any]:
        """P4: after a story step, push its branch with its PR (a short call on the loop thread)."""
        story = plan.story
        if story is None or self.worktree_of is None:
            return settled
        from .story_ci import StoryPusher

        refused_push = StoryPusher(self).after_step(story)
        if refused_push:
            text = PUSH_REFUSED.format(branch=story.branch, why=refused_push)
            self.relay.post(Note("update", text, [story.id]))
        self.save()
        return settled

    def _step_failed(self, plan: Plan, exc: Exception) -> dict[str, Any]:
        """A limit halts the run (logged here); any other error is saved and re-raised."""
        found = halt.limit_halt(exc)
        self._drop_overfull_session(plan, exc)
        if found is None:
            self.save_interrupted(Cause.ERROR)
            raise exc
        halt.log_traceback(self.config.run_dir, exc)
        return halted_report(plan.role.name, self._stop_for_limit(plan, found))

    def _drop_overfull_session(self, plan: Plan, exc: Exception) -> None:
        """K3: a resumed query that fails on the context limit loses its kept session."""
        if plan.story and plan.launch.resume and kept_sessions.context_exceeded(str(exc)):
            kept_sessions.drop_role(plan.story, plan.role.name)
            self.save()

    def _stop_for_limit(self, plan: Plan, found: Halt) -> Halt:
        """I6: a story step cut off by the usage limit fails alone; the scheduler halts the run."""
        if self.worktree_of is None:
            return self.halt_run(found)
        self.save_interrupted(Cause.LIMIT)
        self.flags.limited = found
        return found

    def priority(self) -> Priority:
        """The story ranking: the PO's order and pulls over this run's stories."""
        return Priority(self.state.order, self.state.pulled)

    def load_dependencies(self) -> str | None:
        """Load `depends_on` from the open stories' files into state (s86); the refusal, or None."""
        stories = self.state.stories
        found = dependencies.declared(self.config, dependencies.open_ids(stories))
        if refusal := dependencies.load_refusal(found, stories):
            return refusal
        dependencies.apply(found, stories)
        self.save()
        return None

    def reorder(self, change: Reorder) -> list[str]:
        """Apply a new order and log it (PO tools and dashboard requests alike)."""
        stories = self.state.stories
        before = self.priority().queue(stories.values())
        self.state.order = change.order
        self.state.pulled = self.priority().repulled(change.pull, stories)
        self.save()
        after = self.priority().queue(stories.values())
        data = change.event_data(before, after) | {
            "warnings": dependencies.warnings(dependencies.Moved(before, after), stories)
        }
        self.events.emit(Event(EventKind.PRIORITY, SOURCE_ROLES[change.source], change.story, data))
        return after

    def enforce_ceiling(self) -> Halt | None:
        """Halt the run when corrected spend has reached ``team.budget_usd`` (B1, B3)."""
        found = halt.budget_halt(self.ledger.total(), self.config.team.budget_usd)
        return self.halt_run(found) if found else None

    def halt_run(self, found: Halt) -> Halt:
        """Record the run's first halt (status, reason, liaison note); later calls re-assert it."""
        first = self.halted_by is None
        self.halted_by = self.halted_by or found
        saved = self.save_interrupted(Cause(self.halted_by.kind.value))
        self.state.mark(self.halted_by.rule.status, self.halted_by.reason)
        self.state.halt_kind = self.halted_by.kind.value
        self.save()
        if first:
            self.relay.post(
                Note(
                    self.halted_by.rule.note_kind,
                    halt_note(self.halted_by, saved) + _waits_suffix(self.relay),
                )
            )
        return self.halted_by

    def save_interrupted(self, cause: Cause) -> Interruption | None:
        """Save a cut-off step's edits (or the PO's) in a reverted commit and record it.

        Nothing is saved when the checkout moved (K5): the tree is not the team's;
        the cause is kept for ``start --resume`` (s62 R1).
        """
        self._close_interrupted(cause)
        if self.worktree_of is not None:
            return None  # I1: a story step keeps its worktree; nothing is committed
        if checkout.check(self.git, self.state.checkout) is not None:
            self.state.unsaved = cause
            return None
        saved = recovery.Salvager(self.git, self.config.run_dir).save(self.state, cause)
        self.record_checkout()
        return saved

    def checkout_moved(self) -> Halt | None:
        """K3/K4: halt the run when the checkout drifted; record it when unrecorded and matching."""
        with self.stage_log.open(stages.Name.CHECKOUT_GUARD):
            return self.drift_halt()

    def drift_halt(self) -> Halt | None:
        """``checkout_moved`` without its stage event (a refusal must leave the events alone)."""
        drift = checkout.check(self.git, self.state.checkout)
        if drift is not None:
            return self.halt_run(drift.halt())
        if self.state.checkout is None:
            self.record_checkout()
        return None

    def verify_checkout(self) -> None:
        """``checkout_moved``, raising ``CheckoutChanged`` with the halt when it halted."""
        if self.worktree_of is not None:
            return
        with self.stage_log.open(stages.Name.CHECKOUT_VERIFY):
            moved = self.drift_halt()
        if moved is not None:
            raise CheckoutChanged(moved)

    def record_checkout(self) -> None:
        """K1: expect the live branch and HEAD; call only after the runner's own git writes."""
        if self.worktree_of is not None:
            self.state.stories[self.worktree_of].worktree_head = self.git.head()
            return self.save()
        self.state.checkout = checkout.recorded(self.git)
        self._follow_sprint_head()
        self.save()

    def _follow_sprint_head(self) -> None:
        """AC1.3: the sprint's stack entry follows the main checkout's HEAD."""
        entry = boundary.own_entry(self.state.upstream.stack, self.state.sprint)
        if entry is not None:
            entry.head = self.state.checkout.head  # type: ignore[union-attr]

    async def _execute(self, plan: Plan) -> StepResult:
        try:
            result = await collect(self.query_fn, plan)
        finally:
            plan.stop()
        return self.priced(plan, self._own_cost(plan, result))

    def _own_cost(self, plan: Plan, result: StepResult) -> StepResult:
        """K4: a resumed step is billed its session's delta; the running total is kept."""
        kept = plan.story.sessions.get(plan.role.name) if plan.story else None
        resume = plan.launch.resume
        if kept is None or resume is None or kept.session != resume:
            return result
        own = SessionCost(kept.session, kept.reported).own_cost(resume, result.cost)
        return replace(result, cost=own, resumed=True, reported=result.cost)

    def priced(self, plan: Plan, result: StepResult) -> StepResult:
        """``result`` with the cost its role's provider bills."""
        return replace(result, cost=self.providers.cost_of(plan.role, result.cost))

    def settle_po(self) -> dict[str, str | None]:
        """Commit the PO's own story edits so the next role starts on a clean tree."""
        role = self.resolve(PO)
        return self.settle_tree(Plan(role, self.scope_for(role), summary="update stories"))

    def settle(self, plan: Plan, result: StepResult) -> dict[str, Any]:
        """Record cost, read the handoff, settle the tree, then gate; save state."""
        what = f"settling {salvage.label(plan.role.name, plan.story.id if plan.story else None)}"
        with self.pulse.doing(what):
            return self._settle(plan, result)

    def _settle(self, plan: Plan, result: StepResult) -> dict[str, Any]:
        plan.text = result.text
        self.record_cost(plan, result)
        self._keep_session(plan, result)
        parsed = self._parse(plan)
        report = {"role": plan.role.name, "cost_usd": round(result.cost, 4)}
        report |= self.settle_tree(plan)
        parsed = _check_explained(parsed, plan)
        self._emit_step_end(plan, parsed, result, report["commit"])
        report |= self._apply(plan, parsed)
        self._land(plan)
        return report

    def _keep_session(self, plan: Plan, result: StepResult) -> None:
        """K1: remember the role's session on the story for its next step."""
        if plan.story is None or result.session_id is None or plan.prepared is not None:
            return
        reported = result.reported or result.cost
        role = plan.role
        kept = KeptSession(result.session_id, role.model, role.effort, role.provider, reported)
        plan.story.sessions[role.name] = kept

    def _emit_step_end(
        self, plan: Plan, parsed: Handoff | HandoffError, result: StepResult, commit: str | None
    ) -> None:
        outcome = handoff_report(parsed) if isinstance(parsed, Handoff) else bad_handoff(parsed)
        cost = round(result.cost, 4)
        tokens = asdict(result.tokens)
        meter = self._end_meter()
        self.emit(
            EventKind.STEP_END,
            plan,
            **outcome,
            tokens=tokens,
            cost_usd=cost,
            commit=commit,
            turns=result.turns,
            resumed=result.resumed,
            cache_write=result.tokens.cache_creation,
            model=meter.reading.model if meter else None,
            **live.time_split(meter),
            **self.pulse.clocks(),
        )

    def _parse(self, plan: Plan) -> Handoff | HandoffError:
        try:
            handoff = parse_handoff(plan.text)
        except HandoffError as exc:
            plan.summary = "malformed handoff"
            return exc
        plan.summary = handoff.summary
        plan.reasons = handoff.requirement_changes
        return handoff

    def _apply(self, plan: Plan, parsed: Handoff | HandoffError) -> dict[str, Any]:
        parsed = _settled(plan, parsed)
        if isinstance(parsed, HandoffError):
            gate = self._bounce(plan, str(parsed))
            return {
                "status": "bad_handoff",
                "reason": str(parsed),
                **({"gate": gate} if gate else {}),
            }
        self.state.followups.pop(plan.role.name, None)
        return {
            **handoff_report(parsed),
            **self._effects(plan, parsed),
            **self._manual_question(plan),
        }

    def _effects(self, plan: Plan, handoff: Handoff) -> dict[str, Any]:
        """The Manager rules; any other role on a story goes through its gate."""
        if plan.role.name == MANAGER:
            return self.apply_manager(plan, handoff)
        if plan.kind in KIND_EFFECTS:
            return KIND_EFFECTS[plan.kind](self, plan, handoff)
        effect = STORY_EFFECTS.get(plan.role.name)
        if effect and plan.story:
            effect(plan.story, handoff)
        return {"gate": self.gate(plan, handoff)} if plan.story else {}

    def _fix_effects(self, plan: Plan, handoff: Handoff) -> dict[str, Any]:
        """Settle a gate fix step: pop it when done, else set the story back (R17)."""
        story, fix = plan.story, plan.story.fixes[0]
        report: dict[str, Any] = {"fix": self._record_fix(plan, handoff, fix)}
        outcome = fix_outcome(story, handoff)
        if outcome is None:
            story.fixes.pop(0)
            return report
        return report | {"gate": self._advance_and_log(plan, outcome)}

    def _apply_rebase(self, plan: Plan, handoff: Handoff) -> dict[str, Any]:
        """S3: adopt the rebased branch when the role's result checks out; else bounce a round."""
        story, rebase = plan.story, plan.story.rebase  # type: ignore[union-attr]
        why = self._find_rebase_refusal(plan, handoff)
        if why:
            outcome = Outcome(Verdict.BOUNCE, why, story.step, author=Author.ROLE)  # type: ignore[union-attr]
            return {"gate": self._advance_and_log(plan, outcome)}
        self._take_rebase(story, rebase)  # type: ignore[arg-type]
        return {"rebased": {"branch": story.branch, "onto": rebase.onto}}  # type: ignore[union-attr]

    def _find_rebase_refusal(self, plan: Plan, handoff: Handoff) -> str | None:
        if handoff.status != "done":
            return f"role reported {handoff.status}: {handoff.summary}"
        return story_rebase.refusal(self.git, plan.story.rebase)  # type: ignore[union-attr,arg-type]

    def _take_rebase(self, story: StoryState, rebase: Any) -> None:
        """S3: the story takes the rebased branch, remaps its shas and pushes it."""
        from .replay import StoryReplay
        from .story_ci import StoryPusher

        old_pr = story.pr
        StoryReplay(self).take_over(story, rebase)
        story.rebase = None
        StoryPusher(self).push_replayed(story, old_pr)

    def _record_fix(self, plan: Plan, handoff: Handoff, fix: Fix) -> dict[str, Any]:
        story = plan.story
        diff = self.git.run("diff", f"{plan.commit}^", plan.commit) if plan.commit else ""
        record = FixRecord(
            fix.role,
            [i.shown for i in fix.items],
            plan.commit,
            handoff.asserts,
            owners_mod.asserts_changed(diff),
        )
        story.fixed.append(record)
        left = [f.role for f in story.fixes[1:]]
        self.emit(
            EventKind.GATE_FIX,
            plan,
            status=handoff.status,
            files=record.files,
            commit=record.commit,
            asserts=record.asserts,
            assertions_changed=record.changed,
            left=left,
        )
        return asdict(record)

    def _bounce(self, plan: Plan, reason: str) -> dict[str, Any] | None:
        story = plan.story
        if story and role_fits_step(plan.role.name, story.step):
            outcome = Outcome(Verdict.BOUNCE, reason, story.step, author=Author.ROLE)
            return self._advance_and_log(plan, outcome)
        return None

    def _manual_question(self, plan: Plan) -> dict[str, Any]:
        if not plan.prepared or plan.prepared.environment.kind != "manual":
            return {}
        stories = [plan.story.id] if plan.story else []
        return {"question_id": self.relay.post(Note("question", plan.text, stories)).id}

    def record_cost(self, plan: Plan, result: StepResult) -> None:
        before, cost = self.ledger.total(), result.cost
        story_id = plan.story.id if plan.story else None
        role = plan.role
        entry = Entry(
            role.name,
            role.model,
            cost,
            story_id,
            tokens=result.tokens,
            turns=result.turns,
            resumed=result.resumed,
        )
        self.ledger.record(entry)
        budget = Budget(self.config.team.budget_usd, self.config.team.manager_every_pct)
        if budget.checkpoint_crossed(before, before + cost):
            self.state.manager_due.append(f"budget checkpoint at ${before + cost:.2f}")

    def settle_tree(self, plan: Plan) -> dict[str, Any]:
        """Quarantine out-of-scope changes, hold back unexplained edits, commit the rest."""
        self.verify_checkout()
        audit = restrict_config(guard.audit_step(self.git, plan.scope), self.git)
        quarantined = self._quarantine(plan, audit)
        sorting = self._sort_requirements(plan, audit)
        held = self._hold_back(plan, sorting)
        kept = [p for p in audit.in_scope if p not in sorting.held_files]
        staged = Staged(kept, sorting.trailers)
        commit = self.commit_step(plan, staged) if kept else None
        if commit or quarantined or held:
            self.record_checkout()
        fields: dict[str, Any] = {"commit": commit, "quarantine": quarantined}
        return fields | self._report_held(held) | self._record_requirements(plan, sorting)

    def _quarantine(self, plan: Plan, audit: guard.Audit) -> str | None:
        quarantined = guard.quarantine(self.git, audit) if audit.out_of_scope else None
        if quarantined:
            self.emit(EventKind.QUARANTINE, plan, sha=quarantined, paths=audit.out_of_scope)
        return quarantined

    def _sort_requirements(self, plan: Plan, audit: guard.Audit) -> requirement_changes.Sorting:
        """Classify the step's requirement files and split them by their reasons (C1-C3)."""
        folder = requirements.folder_of(self.config)
        paths = requirement_changes.select_candidates(audit.in_scope, folder)
        found = requirement_changes.find_changes(self.git, paths)
        return requirement_changes.sort_changes(found, plan.reasons)

    def _hold_back(self, plan: Plan, sorting: requirement_changes.Sorting) -> str | None:
        """Commit and revert the unexplained edits (C4); the hold-back sha, or None."""
        if not sorting.held:
            return None
        held = requirement_changes.HeldBack(plan.role.name, tuple(sorting.held_files))
        sha = requirement_changes.hold_back(self.git, held)
        plan.unexplained = requirement_changes.describe_unexplained(sorting.held, sha)
        return sha

    @staticmethod
    def _report_held(held: str | None) -> dict[str, str]:
        return {"held_back": held} if held else {}

    def _record_requirements(
        self, plan: Plan, sorting: requirement_changes.Sorting
    ) -> dict[str, Any]:
        """Emit the change events, auto-accept (C7, C8) and give the C9 report keys."""
        if not sorting.landed or plan.commit is None:
            return {}
        for explained in sorting.landed:
            self.emit(EventKind.REQUIREMENT_CHANGED, plan, **explained.entry, sha=plan.commit)
        affected = self._accept_affected(plan, sorting.landed)
        fields = {
            "requirement_changes": [e.entry for e in sorting.landed],
            "redesigned_stories": list(affected.redesign),
            "affected_done_stories": list(affected.done),
        }
        return {k: v for k, v in fields.items() if v}

    def _accept_affected(
        self, plan: Plan, landed: tuple[requirement_changes.Explained, ...]
    ) -> requirement_changes.Affected:
        """Send past-design stories that trace the changes back to design (C8)."""
        own = plan.story.id if plan.story else None
        scope = requirement_changes.AcceptScope(
            tuple(requirement_changes.collect_traced(landed, own)), self.pipeline.is_past_design
        )
        affected = requirement_changes.find_affected(self.state.stories, scope)
        for sid in affected.redesign:
            target = requirement_changes.NoteTarget(sid, own or "run", plan.commit or "")
            self.pipeline.redesign(self.state.stories[sid])
            self.state.stories[sid].note = requirement_changes.build_redesign_note(landed, target)
        if affected.redesign:
            self.save()
        return affected

    def commit_step(self, plan: Plan, staged: Staged) -> str:
        """First commit of a story is ``feat``; later ones are fixups of it."""
        message = Authored(commit_message(plan, self._subject(plan)), trailers=staged.trailers)
        sha = self.git.commit_by(staged.paths, message)
        plan.commit = sha
        if plan.story and not plan.story.commit:
            plan.story.commit = sha
        self._record_commit(plan, sha, staged.paths)
        return sha

    def _record_commit(self, plan: Plan, sha: str, paths: list[str]) -> None:
        """Run the COMMIT_RECORDS rows that fit the committing role (s46, R7)."""
        if plan.story:
            _note_files(plan.story, paths)
        for step, record in COMMIT_RECORDS:
            if plan.story and role_fits_step(plan.role.name, step):
                record(plan.story, sha, paths)

    def _subject(self, plan: Plan) -> str:
        story = plan.story
        if story is None:
            return f"chore(team): {plan.role.name} step"
        if story.commit:
            return f"fixup! {self.git.subject(story.commit)}"
        return f"feat({story.id}): {story.title}"

    def gate(self, plan: Plan, handoff: Handoff) -> dict[str, Any]:
        """Evaluate the step's gate, commit its pass record, then advance the story (s131)."""
        self.verify_checkout()
        outcome = self._evaluate(plan, handoff)
        record = self._pass_record(plan, handoff) if outcome.verdict is Verdict.PASS else Recorded()
        return self._advance_and_log(plan, record.failure or outcome) | record.fields

    def _pass_record(self, plan: Plan, handoff: Handoff) -> Recorded:
        """Run the step's PASS_RECORDS row; a GitError becomes a gate hold naming it (s131 R2)."""
        row = PASS_RECORDS.get(plan.story.step)  # type: ignore[union-attr]
        if row is None:
            return Recorded()
        try:
            return Recorded(row(self, plan, handoff))
        except GitError as error:
            reason = RECORD_FAILED.format(step=plan.story.step, error=error)  # type: ignore[union-attr]
            return Recorded(failure=Outcome(Verdict.HOLD, reason))

    def _record_tooling(self, plan: Plan, handoff: Handoff) -> dict[str, Any]:
        """R1: write the Tooling section into the story file and commit only that file."""
        story = plan.story.id  # type: ignore[union-attr]
        file = story_spec.file_of(self.config, story)
        old = system.read_text(self.config.repo / file)
        edit = FileEdit(file, old, ops_review.with_section(old, handoff.tooling))
        sha = self._commit_edit(edit, ops_review.RECORD_SUBJECT.format(story=story))
        self.record_checkout()
        return {"tooling": {"file": file, "commit": sha}}

    def _commit_edit(self, edit: FileEdit, subject: str) -> str | None:
        """Write ``edit`` and commit only its file; None when unchanged.

        On a GitError, restore the old text and re-raise.
        """
        if edit.new == edit.old:
            return None
        system.write_text(self.config.repo / edit.file, edit.new)
        try:
            return self.git.commit([edit.file], subject)
        except GitError:
            self._restore(edit)
            raise

    def _restore(self, edit: FileEdit) -> None:
        """Put ``edit``'s file back to its old text and unstage it (s131 R2)."""
        system.write_text(self.config.repo / edit.file, edit.old)
        # attempt, not run: git may be what broke, and a raise here would hide the first error.
        self.git.attempt("reset", "-q")

    def _attach_ops_review(self, plan: Plan) -> None:
        """B1: the ops-review section, only for a story at ops-review."""
        story = plan.story
        if story is None or story.step != ops_review.STEP:
            return
        facts = ops_review.facts(self.config, story_spec.read(self.config, story.id))
        plan.prompt += f"\n\n{ops_review.brief_section(facts)}".rstrip()

    def served(self, plan: Plan) -> Pipeline:
        """The pipeline whose test runs are made for ``plan``'s story (P16)."""
        story = plan.story
        return self.pipeline.serving(Serving(story.id, plan.base) if story else Serving())

    def _evaluate(self, plan: Plan, handoff: Handoff) -> Outcome:
        chore = GATE_CHORE.format(step=plan.story.step, story=plan.story.id)
        with self.pulse.doing(chore):
            return self._gating(plan).evaluate(plan.story, handoff)

    def _gating(self, plan: Plan) -> Pipeline:
        """The pipeline gating ``plan``; reuses the Stop hook's suite run if any."""
        served = self.served(plan)
        return plan.stop_hook.reusing(served) if plan.stop_hook else served

    def owners(self, story: StoryState) -> Owners:
        """Who may write what, in pipeline order, for this story (R2)."""
        runner_owned = {s for s, role in STEP_ROLES.items() if role == "runner"}
        rows = [
            (step, self._writer_role(story, step))
            for step in self.pipeline.steps
            if step not in runner_owned
        ]
        return Owners(
            _writers(rows, lambda role: tuple(self.scope_for(self.resolve(role)).write)),
            story.step,
            frozenset(story.files),
        )

    def _writer_role(self, story: StoryState, step: str) -> str:
        role = STEP_ROLES[step]
        known = role == "developer" and story.developer in self.book.names()
        return story.developer if known else role

    def _queue_done_renewal(self, story: Any) -> None:
        reason = f"{story.id} done"
        if story.status is StoryStatus.DONE and reason not in self.state.po_renew_due:
            self.state.po_renew_due.append(reason)

    def _keep_runs(self, story: StoryState, outcome: Outcome) -> None:
        """Keep the gate's run and any extra runs under the step's gate."""
        for ran in (outcome.ran, *outcome.extra_ran):
            if ran:
                self._keep(story, ran, f"{story.step} gate")

    def _advance_and_log(self, plan: Plan, outcome: Outcome) -> dict[str, Any]:
        story = plan.story
        step = story.step
        outcome = self.pipeline.route(outcome, self.owners(story))
        self._keep_runs(story, outcome)
        setback = _setback(plan, outcome)
        outcome = self.pipeline.screen(story, setback) or outcome if setback else outcome
        self._advance_story(story, step, outcome)
        self._queue_done_renewal(story)
        result = {
            "step": step,
            "verdict": outcome.verdict,
            "reason": outcome.reason,
            "now_at": story.step,
            "story_status": story.status,
            "rounds": story.rounds,
        }
        result |= _collect_outcome_fields(outcome)
        result |= _dispute_fields(outcome, story) | _setback_fields(setback, story)
        result |= {"rule": outcome.rule} if outcome.verdict is Verdict.ESCALATE else {}
        event = self.emit(GATE_EVENTS.get(outcome.verdict, EventKind.GATE), plan, **result)
        _record(story, setback, event)
        story.run = (
            loops.after_pass(story.run, step) if outcome.verdict is Verdict.PASS else story.run
        )
        return result

    def _advance_story(self, story: StoryState, step: str, outcome: Outcome) -> None:
        """Move the story by the outcome; then K2 and L2: sessions end when it finishes or goes
        back, and a story at land joins the land queue."""
        self.pipeline.advance(story, outcome)
        sent_back = outcome.verdict in (Verdict.BOUNCE, Verdict.RETURN) and story.step != step
        if sent_back or story.status in FINISHED:
            kept_sessions.drop_all(story)
        if story.step == "land" and story.id not in self.state.land_queue:
            self.state.land_queue.append(story.id)

    def apply_manager(self, plan: Plan, handoff: Handoff) -> dict[str, Any]:
        """A Manager step clears the review queue and rules on the story; reports the ruling."""
        self.state.manager_due.clear()
        self.state.unreviewed.clear()
        for role, question in handoff.followups.items():
            self.state.followups.setdefault(role, []).append(question)
        return {**self._rulings(plan, handoff), **self._boundary_review()}

    def _boundary_review(self) -> dict[str, Any]:
        """The Manager's review of an escalated boundary: mark it reviewed, report it."""
        b = self.state.boundary
        if b is None or b.hold is not BoundaryHold.ESCALATED:
            return {}
        b.hold = BoundaryHold.REVIEWED
        data = boundary_data(self, b)
        return {"boundary": {**data, "reason": b.escalated, "hold": b.hold, "reviewed": True}}

    def _rulings(self, plan: Plan, handoff: Handoff) -> dict[str, Any]:
        if _names_fault(plan, handoff):
            return self._rule_after_fault(plan, handoff)
        return self._rule(plan, handoff) if handoff.ruling else {}

    def _rule_after_fault(self, plan: Plan, handoff: Handoff) -> dict[str, Any]:
        """Apply the named fault; a ruling then wins, or is reported unapplied."""
        report = self._fault(plan, handoff)
        if not handoff.ruling:
            return report
        if report["fault"]["applied"]:
            return report | self._rule(plan, handoff)
        return report | _unapplied_ruling(handoff.ruling)

    def _fault_refusal(self, story: StoryState | None, fault: str | None) -> str | None:
        why = ruling_refusal(story, "a fault")
        if why or story is None:
            return why
        if not fault:
            return FAULT_MISSING.format(id=story.id)
        known = fault == "runner" or fault in self.book.names()
        return None if known else FAULT_UNKNOWN.format(fault=fault)

    def _fault(self, plan: Plan, handoff: Handoff) -> dict[str, Any]:
        story, fault = plan.story, handoff.fault
        why = self._fault_refusal(story, fault)
        if why:
            return {"fault": {"fault": fault, "applied": False, "why": why}}
        reason, kind = setback_reason(story), self.pipeline.fault_kind(fault)
        self.pipeline.apply_fault(story, fault)
        report = {"fault": fault, "kind": kind, "reason": reason, "now_at": story.step}
        self.emit(EventKind.FAULT, plan, **report)
        self._tell_human(plan, handoff, report)
        return {"fault": {**report, "applied": True}}

    def _tell_human(self, plan: Plan, handoff: Handoff, report: dict[str, Any]) -> None:
        if report["kind"] is not loops.Fault.RUNNER:
            return
        text = RUNNER_FAULT_NOTE.format(
            story=plan.story.id, reason=report["reason"], summary=handoff.summary
        )
        self.relay.post(Note("update", text, [plan.story.id]))

    def _rule(self, plan: Plan, handoff: Handoff) -> dict[str, Any]:
        ruling = handoff.ruling
        why = ruling_refusal(plan.story) or self.pipeline.ruling_move_refusal(plan.story, ruling)
        if why:
            return {"ruling": {"ruling": ruling, "applied": False, "why": why}}
        self.pipeline.apply_ruling(plan.story, ruling)
        now_at = plan.story.step
        self.emit(
            EventKind.RULING, plan, ruling=ruling, reason=handoff.ruling_reason, now_at=now_at
        )
        return {"ruling": {"ruling": ruling, "applied": True, "now_at": now_at}}


def find_rebase_refusal(role: str, story: StoryState | None) -> str | None:
    """S1: only the role a queued story rebase names may run it, on its story."""
    if story is None or story.rebase is None:
        return "no story rebase is queued"
    if role != story.rebase.role:
        return f"story {story.id}'s rebase belongs to {story.rebase.role}"
    return None


def _names_fault(plan: Plan, handoff: Handoff) -> bool:
    """The fault path applies: a fault is named or the story repeated a setback."""
    return bool(handoff.fault or (plan.story and plan.story.repeated is not None))


def _unapplied_ruling(ruling: str) -> dict[str, Any]:
    """The report of a ruling held back because its fault did not apply."""
    return {"ruling": {"ruling": ruling, "applied": False, "why": RULING_AFTER_FAULT}}


def _add_code_commit(story: StoryState, sha: str, paths: list[str]) -> None:
    story.code_commits.append(sha)


def _add_test_files(story: StoryState, sha: str, paths: list[str]) -> None:
    story.test_files.extend(p for p in paths if p not in story.test_files)


def fitting_step(role: str, table: Mapping[str, object]) -> str | None:
    """The first key of ``table`` whose step ``role`` works on."""
    return next((s for s in table if role_fits_step(role, s)), None)


COMMIT_RECORDS: tuple[tuple[str, Callable[[StoryState, str, list[str]], None]], ...] = (
    ("implement", _add_code_commit),
    ("tests", _add_test_files),
)

STEP_SETUPS = {
    ops_review.STEP: Runtime._attach_ops_review,
    "implement": Runtime._attach_runner_tools,
    "quality": Runtime._run_quality_checks,
}

PASS_RECORDS: dict[str, Callable[[Runtime, Plan, Handoff], dict[str, Any]]] = {
    ops_review.STEP: Runtime._record_tooling,
}

GIT_CONFINED: dict[str, Callable[[Runtime, Plan], Path]] = {
    "e2e": Runtime._presentation_workspace,
    "acceptance": Runtime._proxy_workspace,
}

FIX_SETUPS = {
    StepKind.TEAM_FIX: Runtime._team_fix_scope,
    StepKind.REBASE_FIX: Runtime._set_rebase_fix_scope,
    StepKind.STORY_REBASE: Runtime._set_story_rebase_scope,
}
WORKTREE_KINDS = frozenset({StepKind.ROLE, StepKind.GATE_FIX, StepKind.STORY_REBASE})


def _story_lines(story: StoryState | None, rework: list[str]) -> list[str]:
    """The story line, the open test dispute, and the rework brief when they apply."""
    if story is None:
        return []
    head = f"Story {story.id}: {story.title} (step {story.step}, round {story.rounds})"
    lines = [head, *_dispute_lines(story), *rework, *_interrupted_lines(story)]
    return ["\n".join(lines)]


def _interrupted_lines(story: StoryState) -> list[str]:
    return [salvage.offer(story.interrupted)] if story.interrupted else []


def _waits_suffix(relay: Relay) -> str:
    """ "; " + the run's waiting reason when a question is open, else "" (W5)."""
    waiting = relay.waiting()
    return f"; {waiting}" if waiting else ""


def halt_note(found: Halt, saved: Interruption | None) -> str:
    """The liaison note for a halt, naming the commit that holds the cut-off edits."""
    return found.message() + salvage.note_suffix(saved)


def _dispute_lines(story: StoryState) -> list[str]:
    d = story.dispute
    if not d:
        return []
    head = f"Test dispute ({d.stage}): {d.test} contradicts {d.rule}: {d.reason}"
    return [head, DISPUTE_OUTPUT.format(output=d.output)] if d.output else [head]


def _collect_outcome_fields(outcome: Outcome) -> dict[str, Any]:
    """A gate event's ``tried``, ``fixes`` and ``failures`` fields, where the outcome has them."""
    fields = _tried_fields(outcome.tried) if outcome.tried else {}
    if outcome.fixes:
        fields["fixes"] = [
            {"role": f.role, "files": [i.shown for i in f.items]} for f in outcome.fixes
        ]
    if outcome.verdict is not Verdict.PASS:
        fields |= results_mod.collect_event_failures((outcome.ran, *outcome.extra_ran))
    return fields


def _tried_fields(tried: acceptance.Tried) -> dict[str, Any]:
    return {
        "environment": tried.environment,
        "mark": tried.mark,
        "failed_acs": list(tried.failed),
    }


def _setback(plan: Plan, outcome: Outcome) -> Setback | None:
    """The setback a bounce, return or hold is, or ``None`` for any other outcome."""
    if outcome.verdict not in SETBACKS:
        return None
    step = plan.story.step
    to_step = outcome.bounce_to or step
    return Setback(step, to_step, plan.role.name, outcome.verdict, outcome.author, outcome.reason)


def _history(setback: Setback, story: StoryState) -> list[str]:
    if story.escalated_by is loops.Rule.BACKSTOP and story.status is StoryStatus.NEEDS_MANAGER:
        return [s.event for s in story.run]
    return [s.event for s in story.streak] if loops.repeats(story.streak, setback) else []


def _setback_fields(setback: Setback | None, story: StoryState) -> dict[str, Any]:
    """Key, author, count, history and bounces for the event of a setback."""
    if setback is None:
        return {}
    history = _history(setback, story)
    count = len(history) + 1
    bounces = loops.bounces(story.run, setback) + 1 if loops.counts(setback) else 0
    return {
        "key": setback.key,
        "author": setback.author,
        "count": count,
        "history": history,
        "bounces": bounces,
    }


def _record(story: StoryState, setback: Setback | None, event: Event) -> None:
    """Add a setback to the streak, and to the run when it crosses between two steps."""
    if setback is None:
        return
    stamped = replace(setback, event=event.id)
    story.streak = loops.extend(story.streak, stamped)
    story.run = loops.extend_run(story.run, stamped) if loops.counts(stamped) else story.run


def _dispute_fields(outcome: Outcome, story: StoryState) -> dict[str, Any]:
    if outcome.verdict is not Verdict.DISPUTE:
        return {}
    d = outcome.dispute
    return {"test": d.test, "rule": d.rule, "disputes": story.disputes}


def _capture_developer(story: StoryState, handoff: Handoff) -> None:
    """The architect's pick of developer specialisation for the story."""
    story.developer = handoff.developer or story.developer


STORY_EFFECTS: dict[str, Callable[[StoryState, Handoff], None]] = {
    ARCHITECT: _capture_developer,
}


def followup_section(questions: list[str]) -> str:
    """The Manager's pending questions for a role, answered in its handoff's ``friction``."""
    if not questions:
        return ""
    asked = "\n".join(f"- {q}" for q in questions)
    return f"## Questions from the Manager\n\n{asked}\n\nAnswer them in your handoff's `friction`."


def bad_handoff(error: HandoffError) -> dict[str, Any]:
    return {
        "status": "bad_handoff",
        "summary": str(error),
        "open_questions": [],
        "next_role": None,
        "friction": "",
    }


def _writers(
    rows: Iterable[tuple[str, str]], scope: Callable[[str], tuple[str, ...]]
) -> tuple[Writer, ...]:
    """One Writer per role, first step wins (R2)."""
    seen: dict[str, Writer] = {}
    for step, role in rows:
        seen.setdefault(role, Writer(step, role, scope(role)))
    return tuple(seen.values())


def _note_files(story: StoryState, paths: list[str]) -> None:
    """Add committed paths to the story's files, once each (R7)."""
    story.files.extend(p for p in dict.fromkeys(paths) if p not in story.files)


def _settled(plan: Plan, parsed: Handoff | HandoffError) -> Handoff | HandoffError:
    """A malformed handoff on a gate fix step counts as failed (R17)."""
    if isinstance(parsed, HandoffError) and plan.kind is StepKind.GATE_FIX:
        return Handoff("failed", summary=str(parsed))
    return parsed


def _fix_disagrees(story: StoryState, handoff: Handoff) -> Outcome:
    reason = FIX_DISAGREES.format(role=story.fixes[0].role, summary=handoff.summary)
    return Outcome(Verdict.BOUNCE, reason, story.step, author=Author.ROLE)


def _fix_holds(story: StoryState, handoff: Handoff) -> Outcome:
    reason = f"role reported {handoff.status}: {handoff.summary}"
    return Outcome(Verdict.HOLD, reason, author=Author.ROLE)


FIX_OUTCOMES: dict[str, Callable[[StoryState, Handoff], Outcome]] = {
    "changes_requested": _fix_disagrees,
    "blocked": _fix_holds,
    "failed": _fix_holds,
}


def fix_outcome(story: StoryState, handoff: Handoff) -> Outcome | None:
    """The setback a gate fix handoff causes, or ``None`` when it is done."""
    make = FIX_OUTCOMES.get(handoff.status)
    return make(story, handoff) if make else None


STORY_REFUSALS = {StepKind.GATE_FIX: fix_refusal, StepKind.STORY_REBASE: find_rebase_refusal}
KIND_EFFECTS = {
    StepKind.GATE_FIX: Runtime._fix_effects,
    StepKind.STORY_REBASE: Runtime._apply_rebase,
}
