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

from . import guard, keys, sandbox
from . import state as state_mod
from .config import CONFIG_NAME, Config
from .events import EVENTS, Event, EventKind, EventLog
from .gates import (
    Outcome,
    Pipeline,
    StoryState,
    StoryStatus,
    Verdict,
    dispatch_refusal,
    role_fits_step,
)
from .git_ops import Git, GitError
from .ledger import Budget, Entry, Ledger, Tokens
from .providers import Providers
from .relay import Note, Relay
from .roles import (
    Handoff,
    HandoffError,
    ResolvedRole,
    RoleBook,
    expand_globs,
    parse_handoff,
    scope_note,
)
from .state import RunState

PROXY = "customer-proxy"
PO = "product-owner"
MANAGER = "manager"
DEVOPS_SECTIONS = ("toolchain", "delivery")
SHELL_OPTS: dict[str, Any] = {
    "shell": True,
    "capture_output": True,
    "text": True,
    "timeout": 1800,
    "check": False,
}

QueryFn = Callable[..., AsyncIterator[Any]]
PrepareFn = Callable[[Config, Any], sandbox.Prepared]


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
    return StepResult(result.result or last_text, cost, result.session_id, tokens)


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
            return f"the run is {self.state.status}; end your turn"
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
        if role.name == PROXY:
            self._attach_delivery(plan)
        return self.finish(plan)

    def _attach_delivery(self, plan: Plan) -> None:
        delivery = self.config.delivery(plan.story.delivery if plan.story else None)
        if delivery is None:
            raise sandbox.SandboxError("no [[delivery]] is configured for the customer proxy")
        plan.prepared = self.prepare_fn(self.config, delivery)
        role_writes, plan.scope = plan.scope.write, sandbox.proxy_scope(self.config, plan.prepared)
        plan.scope.write += role_writes
        self._fit_role_to_delivery(plan)

    def _fit_role_to_delivery(self, plan: Plan) -> None:
        prepared = plan.prepared
        allowed = [t for t in plan.role.tools if t in prepared.kind.tools]
        plan.role.tools = allowed or list(prepared.kind.tools)
        plan.prompt += f"\n\n## How the customer reaches the product\n\n{prepared.guidance()}"
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
        if plan.story:
            s = plan.story
            parts.append(f"Story {s.id}: {s.title} (step {s.step}, round {s.rounds})")
        if plan.role.name == MANAGER:
            parts.append(self._manager_context())
        return "\n\n".join(parts)

    def _manager_context(self) -> str:
        overrides = {r: vars(self.state.overrides[r]) for r in self.state.unreviewed}
        capped = [
            s.id for s in self.state.stories.values() if s.status is StoryStatus.NEEDS_MANAGER
        ]
        context = {
            "review_reasons": self.state.manager_due,
            "unreviewed_overrides": overrides,
            "stories_at_round_cap": capped,
        }
        return "Runner context:\n" + json.dumps(context, indent=2)

    # ----- running -------------------------------------------------------

    async def run_role(self, request: StepRequest) -> dict[str, Any]:
        """Run one role step end to end and return a report for the PO."""
        reason = self.refusal(request)
        if reason:
            return refused(reason)
        self.settle_po()
        try:
            plan = self.plan(request)
        except sandbox.SandboxError as exc:
            return refused(str(exc))
        self.emit(EventKind.STEP_START, plan, brief=request.brief)
        return self.settle(plan, await self._execute(plan))

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
        return {
            **handoff_report(parsed),
            **self._effects(plan, parsed),
            **self._manual_question(plan),
        }

    def _effects(self, plan: Plan, handoff: Handoff) -> dict[str, Any]:
        """The Manager rules; any other role on a story goes through its gate."""
        if plan.role.name == MANAGER:
            self.apply_manager(plan, handoff)
            return {}
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
        self.ledger.record(Entry(role.name, role.model, cost, story_id, tokens=result.tokens))
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
        story = plan.story
        step = story.step
        outcome = self.pipeline.evaluate(step, handoff)
        self.pipeline.advance(story, outcome)
        result = {
            "step": step,
            "verdict": outcome.verdict,
            "reason": outcome.reason,
            "now_at": story.step,
            "story_status": story.status,
            "rounds": story.rounds,
        }
        self.emit(EventKind.GATE, plan, **result)
        return result

    def apply_manager(self, plan: Plan, handoff: Handoff) -> None:
        """A Manager step clears the review queue and rules on a capped story."""
        self.state.manager_due.clear()
        self.state.unreviewed.clear()
        story = plan.story
        if story and story.status is StoryStatus.NEEDS_MANAGER and handoff.ruling:
            self.pipeline.apply_ruling(story, handoff.ruling)
            self.emit(EventKind.RULING, plan, ruling=handoff.ruling, now_at=story.step)


def bad_handoff(error: HandoffError) -> dict[str, Any]:
    return {"status": "bad_handoff", "summary": str(error), "open_questions": [], "next_role": None}


def handoff_report(handoff: Handoff) -> dict[str, Any]:
    return {
        "status": handoff.status,
        "summary": handoff.summary,
        "open_questions": handoff.open_questions,
        "next_role": handoff.next_role,
    }
