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
    TextBlock,
)

from . import guard, halt, handover, keys, presentation, sandbox
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
from .insights import disputes_since_review, friction_since_review, spend_by_role
from .ledger import Budget, Entry, Ledger, Tokens, budget_status
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

PROXY = "customer-proxy"
INTEGRATION_TESTER = "integration-tester"
PO = "product-owner"
MANAGER = "manager"
SCRIBE = "scribe"
ARCHITECT = "architect"
GATE_EVENTS = {Verdict.DISPUTE: EventKind.TEST_DISPUTE}
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
PrepareFn = Callable[[Config, sandbox.Order], sandbox.Prepared]


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
        env=launch.env,
        setting_sources=[],
        mcp_servers=launch.mcp_servers,
        settings=json.dumps(launch.settings) if launch.settings else None,
        resume=launch.resume,
    )


async def collect(query_fn: QueryFn, plan: Plan) -> StepResult:
    """Drain a query; keep the final text, cost, tokens and session id."""
    last_text, result = "", None
    async for message in query_fn(prompt=plan.prompt, options=plan.options):
        last_text = _text_of(message) or last_text
        result = message if isinstance(message, ResultMessage) else result
    if result is None:
        return StepResult(last_text, 0.0)
    cost, tokens = result.total_cost_usd or 0.0, Tokens.from_usage(result.usage)
    return StepResult(result.result or last_text, cost, result.session_id, tokens, result.num_turns)


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

    def emit(self, kind: EventKind, plan: Plan | None = None, **data: Any) -> None:
        """Log an event, attributed to ``plan``'s role and story when given."""
        role = plan.role.name if plan else None
        story = plan.story.id if plan and plan.story else None
        self.events.emit(Event(kind, role, story, data))

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
        if role.name in setups:
            setups[role.name](plan)
        return self.finish(plan)

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
        source = presentation.source_dir(self.config, story.id) if story else None
        return sandbox.Order(delivery, source if source and source.is_dir() else None)

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
            parts.append(self._manager_context())
        parts.append(followup_section(self.state.followups.get(plan.role.name, [])))
        return "\n\n".join(p for p in parts if p)

    def _manager_context(self) -> str:
        overrides = {r: vars(self.state.overrides[r]) for r in self.state.unreviewed}
        capped = [
            s.id for s in self.state.stories.values() if s.status is StoryStatus.NEEDS_MANAGER
        ]
        context = {
            "review_reasons": self.state.manager_due,
            "unreviewed_overrides": overrides,
            "stories_at_round_cap": capped,
            "budget": budget_status(self.ledger, self.config.team.budget_usd),
            "spend_by_role": spend_by_role(self.ledger),
            "friction_since_last_review": friction_since_review(self.events.events()),
            "test_disputes_since_last_review": disputes_since_review(self.events.events()),
            "pending_followups": self.state.followups,
        }
        return "Runner context:\n" + json.dumps(context, indent=2)

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
        if outcome is None:
            return None
        plan = Plan(self.resolve(request.role), self.scope_for(self.resolve(request.role)), story)
        report = self._advance_and_log(plan, outcome)
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
        self.emit(EventKind.STEP_END, plan, **outcome, tokens=tokens, cost_usd=cost, commit=commit)

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
            self._bounce(plan, str(parsed))
            return {"status": "bad_handoff", "reason": str(parsed)}
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

    def _bounce(self, plan: Plan, reason: str) -> None:
        story = plan.story
        if story and role_fits_step(plan.role.name, story.step):
            self.pipeline.advance(story, Outcome(Verdict.BOUNCE, reason, story.step))

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

    def _advance_and_log(self, plan: Plan, outcome: Outcome) -> dict[str, Any]:
        story = plan.story
        step = story.step
        self.pipeline.advance(story, outcome)
        if story.status is StoryStatus.DONE and story.id not in self.state.scribe_due:
            self.state.scribe_due.append(story.id)
        result = {
            "step": step,
            "verdict": outcome.verdict,
            "reason": outcome.reason,
            "now_at": story.step,
            "story_status": story.status,
            "rounds": story.rounds,
        }
        result |= _dispute_fields(outcome, story)
        self.emit(GATE_EVENTS.get(outcome.verdict, EventKind.GATE), plan, **result)
        return result

    def apply_manager(self, plan: Plan, handoff: Handoff) -> dict[str, Any]:
        """A Manager step clears the review queue and rules on the story; reports the ruling."""
        self.state.manager_due.clear()
        self.state.unreviewed.clear()
        for role, question in handoff.followups.items():
            self.state.followups.setdefault(role, []).append(question)
        return self._rule(plan, handoff.ruling) if handoff.ruling else {}

    def _rule(self, plan: Plan, ruling: str) -> dict[str, Any]:
        why = ruling_refusal(plan.story)
        if why:
            return {"ruling": {"ruling": ruling, "applied": False, "why": why}}
        self.pipeline.apply_ruling(plan.story, ruling)
        now_at = plan.story.step
        self.emit(EventKind.RULING, plan, ruling=ruling, now_at=now_at)
        return {"ruling": {"ruling": ruling, "applied": True, "now_at": now_at}}


def _story_lines(story: StoryState | None) -> list[str]:
    """The story line, and the open test dispute when there is one."""
    if story is None:
        return []
    lines = [f"Story {story.id}: {story.title} (step {story.step}, round {story.rounds})"]
    d = story.dispute
    if d:
        lines.append(f"Test dispute ({d.stage}): {d.test} contradicts {d.rule}: {d.reason}")
    return ["\n".join(lines)]


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
