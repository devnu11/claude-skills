"""Run one role step: a fresh ``query()`` per invocation.

A fresh query per step gives each role its own model and effort, lets the guard
hook know exactly which role is acting, and yields a per-step cost from
``ResultMessage.total_cost_usd``. After the step the runner settles the tree
(quarantine out-of-scope changes, commit the rest), checks the story's gate and
saves state. The tree is settled *before* the gate runs, so a gate never sees
changes a role was not allowed to make.
"""

from __future__ import annotations

import json
import subprocess
import tomllib
from collections.abc import AsyncIterator, Callable
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

from . import guard, halt, handover, keys, loops, presentation, sandbox
from . import state as state_mod
from .config import CONFIG_NAME, Config, Delivery
from .events import EVENTS, Event, EventKind, EventLog
from .gates import (
    UNGATED_ROLES,
    Outcome,
    Pipeline,
    StoryState,
    StoryStatus,
    Verdict,
    dispatch_refusal,
    role_fits_step,
    ruling_refusal,
)
from .git_ops import Git, GitError
from .halt import Halt
from .insights import (
    disputes_since_review,
    friction_since_review,
    long_running_roles,
    spend_by_role,
)
from .ledger import Budget, Entry, Ledger, Tokens, budget_status
from .loops import Author, Setback
from .providers import Providers
from .relay import Note, Relay
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
from .state import RunState

REWORK_BRIEF = (
    "Code from an earlier pass is in, so the suite may already be green. "
    'If it is once the tests are right, say so in your handoff: "tests": "changed" '
    '(you changed tests for this story) or "tests": "confirmed" '
    "(you checked the existing tests already cover it)."
)
PROXY = "customer-proxy"
INTEGRATION_TESTER = "integration-tester"
PO = "product-owner"
MANAGER = "manager"
SCRIBE = "scribe"
ARCHITECT = "architect"
GATE_EVENTS = {Verdict.DISPUTE: EventKind.TEST_DISPUTE, Verdict.ESCALATE: EventKind.ESCALATION}
SETBACKS = frozenset({Verdict.BOUNCE, Verdict.RETURN, Verdict.HOLD})
FAULT_MISSING = 'story {id} repeated a setback; name its fault: "fault": a role or "runner"'
FAULT_UNKNOWN = 'unknown fault {fault!r}; name a role or "runner"'
RUNNER_FAULT_NOTE = (
    "Runner fault on {story}: the same setback repeated and no role can fix it: {reason}. "
    "The manager says: {summary} The story is blocked until the runner is fixed."
)
NOT_NOTED = frozenset({"refused", "halted"})
DEVOPS_SECTIONS = ("toolchain", "delivery")
SHELL_OPTS: dict[str, Any] = {
    "shell": True,
    "capture_output": True,
    "text": True,
    "timeout": 1800,
    "check": False,
}

QueryFn = Callable[..., AsyncIterator[Any]]
PrepareFn = sandbox.PrepareFn


@dataclass
class StepRequest:
    """What the PO asked for: a role, its brief and (optionally) a story."""

    role: str
    brief: str
    story_id: str | None = None


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

    @property
    def options(self) -> ClaudeAgentOptions:
        return build_options(self)

    def stop(self) -> None:
        if self.prepared:
            self.prepared.stop()


@dataclass
class StepResult:
    """What a finished ``query()`` produced."""

    text: str
    cost: float
    session_id: str | None = None
    tokens: Tokens = field(default_factory=Tokens)
    turns: int = 0
    compacted_from: int | None = None


ISOLATION_ENV = {"ENABLE_CLAUDEAI_MCP_SERVERS": "false"}


def build_options(plan: Plan) -> ClaudeAgentOptions:
    """SDK options for one step: no user or project settings leak in."""
    role, launch, hook = plan.role, plan.launch, guard.pre_tool_hook(plan.scope)
    return ClaudeAgentOptions(
        system_prompt=launch.system_prompt,
        model=role.model,
        effort=role.effort,
        tools=list(role.tools),
        allowed_tools=[*role.tools, *launch.extra_allowed],
        permission_mode="dontAsk",
        hooks={"PreToolUse": [HookMatcher(matcher=None, hooks=[hook])]},
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

    def take(self, message: Any) -> None:
        self.last_text = _text_of(message) or self.last_text
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


def _is_boundary(message: Any) -> bool:
    return isinstance(message, SystemMessage) and message.subtype == "compact_boundary"


async def collect(query_fn: QueryFn, plan: Plan) -> StepResult:
    """Drain a query; keep the final text, cost, tokens, session id and compaction."""
    drain = _Drain()
    async for message in query_fn(prompt=plan.prompt, options=plan.options):
        drain.take(message)
    return drain.step_result()


def _text_of(message: Any) -> str:
    if not isinstance(message, AssistantMessage):
        return ""
    return "".join(b.text for b in message.content if isinstance(b, TextBlock))


def shell_runner(repo: Path) -> Callable[[str], tuple[int, str]]:
    """Run toolchain commands in ``repo``; return exit code and combined output."""

    def run(command: str) -> tuple[int, str]:
        proc = subprocess.run(command, cwd=repo, **SHELL_OPTS)
        return proc.returncode, proc.stdout + proc.stderr

    return run


def with_secret_denials(settings: dict[str, Any] | None, secrets: list[Path]) -> dict | None:
    """Add Read deny rules for the key files to a role's Claude Code settings."""
    if not secrets:
        return settings
    merged = dict(settings or {})
    permissions = dict(merged.get("permissions", {}))
    permissions["deny"] = [*permissions.get("deny", []), *keys.deny_rules(secrets)]
    return {**merged, "permissions": permissions}


def restrict_config(audit: guard.Audit, git: Git) -> guard.Audit:
    """A config edit may only touch ``[toolchain]`` and ``[[delivery]]``.

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
        after = tomllib.loads((git.repo / CONFIG_NAME).read_text())
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


def halted_report(plan: Plan, found: Halt) -> dict[str, Any]:
    """The PO's report for a step cut short by a halt."""
    return {
        "status": "halted",
        "role": plan.role.name,
        "reason": found.reason,
        "next": "the run is stopping; end your turn",
    }


def _halt_text(state: RunState) -> str:
    reason = f" ({state.status_reason})" if state.status_reason else ""
    return f"the run is {state.status}{reason}; end your turn"


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
    events: EventLog = field(init=False)
    halted_by: Halt | None = field(default=None, init=False)

    def __post_init__(self) -> None:
        self.events = EventLog(self.config.run_dir / EVENTS)

    def emit(self, kind: EventKind, plan: Plan | None = None, /, **data: Any) -> Event:
        """Log an event, attributed to ``plan``'s role and story when given."""
        role = plan.role.name if plan else None
        story = plan.story.id if plan and plan.story else None
        return self.events.emit(Event(kind, role, story, data))

    def save(self) -> None:
        state_mod.save(self.config.run_dir, self.state)

    def stop_requested(self) -> bool:
        return (self.config.run_dir / state_mod.STOP_FILE).exists()

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
        if self.state.manager_due and request.role != MANAGER:
            return "manager review due: " + "; ".join(self.state.manager_due)
        return None

    def _role_refusal(self, request: StepRequest) -> str | None:
        return None if request.role in self.book.names() else f"unknown role {request.role!r}"

    def _story_refusal(self, request: StepRequest) -> str | None:
        sid = request.story_id
        if sid and sid not in self.state.stories:
            return f"unknown story {sid!r}; open it with open_story"
        if sid in self.relay.blocked_stories():
            return f"story {sid} is blocked waiting on an answer"
        return dispatch_refusal(request.role, self.state.stories.get(sid or ""))

    # ----- planning ------------------------------------------------------

    def plan(self, request: StepRequest) -> Plan:
        """Resolve the role and build its scope, prompt and launch settings."""
        role = self.resolve(request.role)
        story = self.state.stories.get(request.story_id or "")
        plan = Plan(role, self.scope_for(role), story, request.brief)
        setups = {PROXY: self._attach_delivery, INTEGRATION_TESTER: self._lay_out_presentation}
        try:
            if role.name in setups:
                setups[role.name](plan)
            return self.finish(plan)
        except Exception:
            plan.stop()
            raise

    def _lay_out_presentation(self, plan: Plan) -> None:
        presentation.lay_out(self.config, plan.story)  # type: ignore[arg-type]  # story-bound role

    def _attach_delivery(self, plan: Plan) -> None:
        delivery = self.config.delivery(plan.story.delivery if plan.story else None)
        if delivery is None:
            raise sandbox.SandboxError("no [[delivery]] is configured for the customer proxy")
        plan.prepared = self.prepare_fn(self.config, self._order(delivery, plan.story))
        role_writes, plan.scope = plan.scope.write, sandbox.proxy_scope(self.config, plan.prepared)
        plan.scope.write += role_writes
        self._fit_role_to_delivery(plan)

    def _order(self, delivery: Delivery, story: StoryState | None) -> sandbox.Order:
        return sandbox.Order(delivery, presentation.presented_source(self.config, story))

    def _fit_role_to_delivery(self, plan: Plan) -> None:
        prepared = plan.prepared
        allowed = [t for t in plan.role.tools if t in prepared.kind.tools]
        plan.role.tools = allowed or list(prepared.kind.tools)
        plan.prompt += f"\n\n## How the customer reaches the product\n\n{prepared.guidance()}"
        plan.prompt += f"\n\n{presentation.prompt_section(prepared.presentation)}".rstrip()
        plan.launch = self._sandbox_launch(prepared)

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
        return plan

    def user_prompt(self, plan: Plan) -> str:
        parts = [plan.prompt]
        parts.extend(_story_lines(plan.story))
        if plan.role.name == MANAGER:
            parts.append(self._manager_context(plan.story))
        parts.append(followup_section(self.state.followups.get(plan.role.name, [])))
        return "\n\n".join(p for p in parts if p)

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
        }
        return "Runner context:\n" + json.dumps(context, indent=2)

    def _repeated_context(self, story: StoryState | None) -> dict[str, Any]:
        if story is None or story.repeated is None:
            return {}
        return {"repeated_setback": loops.manager_view(story, self.events.events())}

    # ----- running -------------------------------------------------------

    async def run_role(self, request: StepRequest) -> dict[str, Any]:
        """Run one role step end to end and return a report for the PO."""
        reason = self.refusal(request)
        if reason:
            return refused(reason)
        self.settle_po()
        report = self._unpresented(request) or await self._plan_and_run(request)
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
        self.emit(EventKind.STEP_START, plan, brief=request.brief)
        return await self._run_planned(plan)

    def note_step(self, story: StoryState, report: dict[str, Any]) -> None:
        """Record a story step: its hold, its gated previous step and the scribe queue."""
        story.hold = handover.hold_reason(report)
        previous = handover.previous_step(report)
        if previous and report.get("role") not in UNGATED_ROLES:
            story.previous = previous
        if report.get("role") == SCRIBE and story.id in self.state.scribe_due:
            self.state.scribe_due.remove(story.id)
        self.save()

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
        except Exception as exc:
            return self._step_failed(plan, exc)
        return self.settle(plan, result)

    def _step_failed(self, plan: Plan, exc: Exception) -> dict[str, Any]:
        """A limit halts the run; any other error goes on to the PO unchanged."""
        halt.log_traceback(self.config.run_dir, exc)
        found = halt.limit_halt(exc)
        if found is None:
            raise exc
        return halted_report(plan, self.halt_run(found))

    def halt_run(self, found: Halt) -> Halt:
        """Record the run's first halt (status, reason, liaison note); later calls re-assert it."""
        first = self.halted_by is None
        self.halted_by = self.halted_by or found
        self.state.mark(self.halted_by.rule.status, self.halted_by.reason)
        self.save()
        if first:
            self.relay.post(Note(self.halted_by.rule.note_kind, self.halted_by.message()))
        return self.halted_by

    async def _execute(self, plan: Plan) -> StepResult:
        try:
            result = await collect(self.query_fn, plan)
        finally:
            plan.stop()
        return self.priced(plan, result)

    def priced(self, plan: Plan, result: StepResult) -> StepResult:
        """``result`` with the cost its role's provider bills."""
        return replace(result, cost=self.providers.cost_of(plan.role, result.cost))

    def settle_po(self) -> dict[str, str | None]:
        """Commit the PO's own story edits so the next role starts on a clean tree."""
        role = self.resolve(PO)
        return self.settle_tree(Plan(role, self.scope_for(role), summary="update stories"))

    def settle(self, plan: Plan, result: StepResult) -> dict[str, Any]:
        """Record cost, read the handoff, settle the tree, then gate; save state."""
        plan.text = result.text
        self.record_cost(plan, result)
        parsed = self._parse(plan)
        report = {"role": plan.role.name, "cost_usd": round(result.cost, 4)}
        report |= self.settle_tree(plan)
        self._emit_step_end(plan, parsed, result, report["commit"])
        report |= self._apply(plan, parsed)
        self.save()
        return report

    def _emit_step_end(
        self, plan: Plan, parsed: Handoff | HandoffError, result: StepResult, commit: str | None
    ) -> None:
        outcome = handoff_report(parsed) if isinstance(parsed, Handoff) else bad_handoff(parsed)
        cost = round(result.cost, 4)
        tokens = asdict(result.tokens)
        self.emit(
            EventKind.STEP_END,
            plan,
            **outcome,
            tokens=tokens,
            cost_usd=cost,
            commit=commit,
            turns=result.turns,
        )

    def _parse(self, plan: Plan) -> Handoff | HandoffError:
        try:
            handoff = parse_handoff(plan.text)
        except HandoffError as exc:
            plan.summary = "malformed handoff"
            return exc
        plan.summary = handoff.summary
        return handoff

    def _apply(self, plan: Plan, parsed: Handoff | HandoffError) -> dict[str, Any]:
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
        effect = STORY_EFFECTS.get(plan.role.name)
        if effect and plan.story:
            effect(plan.story, handoff)
        return {"gate": self.gate(plan, handoff)} if plan.story else {}

    def _bounce(self, plan: Plan, reason: str) -> dict[str, Any] | None:
        story = plan.story
        if story and role_fits_step(plan.role.name, story.step):
            outcome = Outcome(Verdict.BOUNCE, reason, story.step, author=Author.ROLE)
            return self._advance_and_log(plan, outcome)
        return None

    def _manual_question(self, plan: Plan) -> dict[str, Any]:
        if not plan.prepared or plan.prepared.delivery.kind != "manual":
            return {}
        stories = [plan.story.id] if plan.story else []
        return {"question_id": self.relay.post(Note("question", plan.text, stories)).id}

    def record_cost(self, plan: Plan, result: StepResult) -> None:
        before, cost = self.ledger.total(), result.cost
        story_id = plan.story.id if plan.story else None
        role = plan.role
        entry = Entry(
            role.name, role.model, cost, story_id, tokens=result.tokens, turns=result.turns
        )
        self.ledger.record(entry)
        budget = Budget(self.config.team.budget_usd, self.config.team.manager_every_pct)
        if budget.checkpoint_crossed(before, before + cost):
            self.state.manager_due.append(f"budget checkpoint at ${before + cost:.2f}")

    def settle_tree(self, plan: Plan) -> dict[str, str | None]:
        """Quarantine out-of-scope changes, then commit in-scope ones."""
        audit = restrict_config(guard.audit_step(self.git, plan.scope), self.git)
        quarantined = guard.quarantine(self.git, audit) if audit.out_of_scope else None
        if quarantined:
            self.emit(EventKind.QUARANTINE, plan, sha=quarantined, paths=audit.out_of_scope)
        commit = self.commit_step(plan, audit.in_scope) if audit.in_scope else None
        return {"commit": commit, "quarantine": quarantined}

    def commit_step(self, plan: Plan, paths: list[str]) -> str:
        """First commit of a story is ``feat``; later ones are fixups of it."""
        sha = self.git.commit(paths, commit_message(plan, self._subject(plan)))
        if plan.story and not plan.story.commit:
            plan.story.commit = sha
        return sha

    def _subject(self, plan: Plan) -> str:
        story = plan.story
        if story is None:
            return f"chore(team): {plan.role.name} step"
        if story.commit:
            return f"fixup! {self.git.subject(story.commit)}"
        return f"feat({story.id}): {story.title}"

    def gate(self, plan: Plan, handoff: Handoff) -> dict[str, Any]:
        """Evaluate the story's current step gate and advance the story."""
        return self._advance_and_log(plan, self.pipeline.evaluate(plan.story, handoff))

    def _queue_done_renewal(self, story: Any) -> None:
        reason = f"{story.id} done"
        if story.status is StoryStatus.DONE and reason not in self.state.po_renew_due:
            self.state.po_renew_due.append(reason)

    def _advance_and_log(self, plan: Plan, outcome: Outcome) -> dict[str, Any]:
        story = plan.story
        step = story.step
        setback = _setback(plan, outcome)
        outcome = self.pipeline.screen(story, setback) or outcome if setback else outcome
        self.pipeline.advance(story, outcome)
        if story.status is StoryStatus.DONE and story.id not in self.state.scribe_due:
            self.state.scribe_due.append(story.id)
        self._queue_done_renewal(story)
        result = {
            "step": step,
            "verdict": outcome.verdict,
            "reason": outcome.reason,
            "now_at": story.step,
            "story_status": story.status,
            "rounds": story.rounds,
        }
        result |= _dispute_fields(outcome, story) | _setback_fields(setback, story)
        result |= {"rule": outcome.rule} if outcome.verdict is Verdict.ESCALATE else {}
        event = self.emit(GATE_EVENTS.get(outcome.verdict, EventKind.GATE), plan, **result)
        _record(story, setback, event)
        story.run = (
            loops.after_pass(story.run, step) if outcome.verdict is Verdict.PASS else story.run
        )
        return result

    def apply_manager(self, plan: Plan, handoff: Handoff) -> dict[str, Any]:
        """A Manager step clears the review queue and rules on the story; reports the ruling."""
        self.state.manager_due.clear()
        self.state.unreviewed.clear()
        for role, question in handoff.followups.items():
            self.state.followups.setdefault(role, []).append(question)
        return self._rulings(plan, handoff)

    def _rulings(self, plan: Plan, handoff: Handoff) -> dict[str, Any]:
        if plan.story and plan.story.repeated is not None:
            return self._rule_repeat(plan, handoff)
        return self._rule(plan, handoff.ruling) if handoff.ruling else {}

    def _rule_repeat(self, plan: Plan, handoff: Handoff) -> dict[str, Any]:
        """Apply the fault the Manager named; a ruling then wins, but only after a fault applied."""
        report = self._fault(plan, handoff)
        if report["fault"]["applied"] and handoff.ruling:
            report |= self._rule(plan, handoff.ruling)
        return report

    def _fault_refusal(self, story: StoryState, fault: str | None) -> str | None:
        if not fault:
            return FAULT_MISSING.format(id=story.id)
        known = fault == "runner" or fault in self.book.names()
        return None if known else FAULT_UNKNOWN.format(fault=fault)

    def _fault(self, plan: Plan, handoff: Handoff) -> dict[str, Any]:
        story, fault = plan.story, handoff.fault
        why = self._fault_refusal(story, fault)
        if why:
            return {"fault": {"fault": fault, "applied": False, "why": why}}
        reason, kind = story.repeated, self.pipeline.fault_kind(fault)
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

    def _rule(self, plan: Plan, ruling: str) -> dict[str, Any]:
        why = ruling_refusal(plan.story)
        if why:
            return {"ruling": {"ruling": ruling, "applied": False, "why": why}}
        self.pipeline.apply_ruling(plan.story, ruling)
        now_at = plan.story.step
        self.emit(EventKind.RULING, plan, ruling=ruling, now_at=now_at)
        return {"ruling": {"ruling": ruling, "applied": True, "now_at": now_at}}


def _story_lines(story: StoryState | None) -> list[str]:
    """The story line, the open test dispute, and the rework brief when they apply."""
    if story is None:
        return []
    head = f"Story {story.id}: {story.title} (step {story.step}, round {story.rounds})"
    return ["\n".join([head, *_dispute_lines(story), *_rework_lines(story)])]


def _dispute_lines(story: StoryState) -> list[str]:
    d = story.dispute
    if not d:
        return []
    return [f"Test dispute ({d.stage}): {d.test} contradicts {d.rule}: {d.reason}"]


def _rework_lines(story: StoryState) -> list[str]:
    reworked = story.step == "tests" and story.implemented > 0 and story.dispute is None
    return [REWORK_BRIEF] if reworked else []


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
