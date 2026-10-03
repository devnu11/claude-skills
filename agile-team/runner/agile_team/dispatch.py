"""Run one role step: a fresh ``query()`` per invocation.

A fresh query per step gives each role its own model and effort, lets the guard
hook know exactly which role is acting, and yields a per-step cost from
``ResultMessage.total_cost_usd``. After the step the runner settles the tree
(quarantine out-of-scope changes, commit the rest), checks the story's gate and
saves state.
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    HookMatcher,
    ResultMessage,
    TextBlock,
)

from . import gates, guard, sandbox
from . import state as state_mod
from .config import Config
from .git_ops import Git
from .ledger import Entry, Ledger, checkpoint_crossed
from .relay import Relay
from .roles import (
    HandoffError,
    ResolvedRole,
    RoleBook,
    expand_globs,
    parse_handoff,
    scope_note,
    system_prompt,
)
from .state import RunState

PROXY = "customer-proxy"
PO = "product-owner"
MANAGER = "manager"
COMMAND_TIMEOUT_S = 1800

QueryFn = Callable[..., AsyncIterator[Any]]
PrepareFn = Callable[..., sandbox.Prepared]


@dataclass
class StepResult:
    """What a finished ``query()`` produced."""

    text: str
    cost: float
    session_id: str | None = None


async def collect(query_fn: QueryFn, prompt: str, options: ClaudeAgentOptions) -> StepResult:
    """Drain a query; keep the final text, cost and session id."""
    last_text, result = "", None
    async for message in query_fn(prompt=prompt, options=options):
        if isinstance(message, AssistantMessage):
            text = "".join(b.text for b in message.content if isinstance(b, TextBlock))
            last_text = text or last_text
        elif isinstance(message, ResultMessage):
            result = message
    if result is None:
        return StepResult(last_text, 0.0)
    return StepResult(result.result or last_text, result.total_cost_usd or 0.0, result.session_id)


def build_options(
    role: ResolvedRole,
    prompt: str,
    scope: guard.Scope,
    env: dict[str, str],
    *,
    mcp_servers: dict[str, Any] | None = None,
    extra_allowed: list[str] | None = None,
    settings: dict[str, Any] | None = None,
) -> ClaudeAgentOptions:
    """SDK options for one role step: no user/project settings leak in."""
    return ClaudeAgentOptions(
        system_prompt=prompt,
        model=role.model,
        effort=role.effort,
        tools=list(role.tools),
        allowed_tools=[*role.tools, *(extra_allowed or [])],
        permission_mode="dontAsk",
        hooks={"PreToolUse": [HookMatcher(matcher=None, hooks=[guard.pre_tool_hook(scope)])]},
        cwd=str(scope.cwd or scope.repo),
        env=env,
        setting_sources=[],
        mcp_servers=mcp_servers or {},
        settings=json.dumps(settings) if settings else None,
    )


def shell_runner(repo: Path) -> gates.CommandRunner:
    """Run toolchain commands in ``repo``; return exit code and combined output."""

    def run(command: str) -> tuple[int, str]:
        proc = subprocess.run(
            command,
            shell=True,
            cwd=repo,
            capture_output=True,
            text=True,
            timeout=COMMAND_TIMEOUT_S,
            check=False,
        )
        return proc.returncode, proc.stdout + proc.stderr

    return run


@dataclass
class Plan:
    """Everything needed to launch one step."""

    role: ResolvedRole
    scope: guard.Scope
    options: ClaudeAgentOptions
    prompt: str
    prepared: sandbox.Prepared | None = None


@dataclass
class Runtime:
    """The live run: config, roles, git, ledger, relay and state."""

    config: Config
    book: RoleBook
    git: Git
    ledger: Ledger
    relay: Relay
    state: RunState
    env: dict[str, str]
    query_fn: QueryFn
    checks: gates.Checks
    prepare_fn: PrepareFn = sandbox.prepare
    notes: list[str] = field(default_factory=list)

    @property
    def steps(self) -> list[str]:
        return list(self.config.gates.steps)

    def save(self) -> None:
        state_mod.save(self.config.run_dir, self.state)

    def stop_requested(self) -> bool:
        return (self.config.run_dir / state_mod.STOP_FILE).exists()

    # ----- refusal -------------------------------------------------------

    def refusal(self, role: str, story_id: str | None) -> str | None:
        """Why ``role`` may not run now, or ``None``."""
        if self.stop_requested():
            return "a stop was requested; end your turn"
        if self.run_halted():
            return f"the run is {self.state.status}; end your turn"
        if role not in self.book.names():
            return f"unknown role {role!r}"
        if story_id and story_id not in self.state.stories:
            return f"unknown story {story_id!r}; open it with open_story"
        if self.state.manager_due and role != MANAGER:
            return "manager review due: " + "; ".join(self.state.manager_due)
        story = self.state.stories.get(story_id) if story_id else None
        return gates.dispatch_refusal(story, role, self.relay.blocked_stories())

    def run_halted(self) -> bool:
        """``done``/``blocked`` always halt; ``sprint-end`` halts only the sprint cadence."""
        status = self.state.status
        return status in ("done", "blocked") or (
            status == "sprint-end" and self.state.cadence == "sprint"
        )

    # ----- planning ------------------------------------------------------

    def scope_for(self, role: ResolvedRole) -> guard.Scope:
        """Guard scope from the role's globs with placeholders expanded."""
        values = self.config.placeholders()
        write, read = expand_globs(role.write, values), expand_globs(role.read, values)
        return guard.Scope(role.name, self.config.repo, write, read)

    def settle_po(self) -> dict[str, str | None]:
        """Commit the PO's own story edits so the next role starts on a clean tree."""
        role = self.book.resolve(PO, self.state.runtime_overrides(PO))
        return self.settle_tree(PO, self.scope_for(role), None)

    def plan(self, name: str, brief: str, story: gates.StoryState | None) -> Plan:
        role = self.book.resolve(name, self.state.runtime_overrides(name))
        scope = self.scope_for(role)
        if name == PROXY:
            return self._proxy_plan(role, brief, story, scope.write)
        return self._finish_plan(role, brief, story, scope)

    def _proxy_plan(
        self, role: ResolvedRole, brief: str, story: gates.StoryState | None, write: list[str]
    ) -> Plan:
        delivery = self.config.delivery(story.delivery if story else None)
        if delivery is None:
            raise sandbox.SandboxError("no [[delivery]] is configured for the customer proxy")
        prepared = self.prepare_fn(self.config, delivery)
        scope = sandbox.proxy_scope(self.config, prepared, write)
        role.tools = [t for t in role.tools if t in prepared.kind.tools] or list(
            prepared.kind.tools
        )
        brief = f"{brief}\n\n## How the customer reaches the product\n\n{prepared.guidance()}"
        servers = sandbox.mcp_servers(prepared)
        plan = self._finish_plan(
            role,
            brief,
            story,
            scope,
            mcp_servers=servers,
            extra_allowed=[f"mcp__{n}" for n in servers],
            settings=sandbox.os_sandbox_settings(self.config, prepared),
            env={**prepared.env, **self.env},
        )
        plan.prepared = prepared
        return plan

    def _finish_plan(
        self,
        role: ResolvedRole,
        brief: str,
        story: gates.StoryState | None,
        scope: guard.Scope,
        env: dict[str, str] | None = None,
        **extra: Any,
    ) -> Plan:
        system = system_prompt(
            self.book, role, self.config.repo, scope_note(scope.write, scope.read)
        )
        options = build_options(role, system, scope, env or self.env, **extra)
        return Plan(role, scope, options, self.user_prompt(role.name, brief, story))

    def user_prompt(self, role: str, brief: str, story: gates.StoryState | None) -> str:
        parts = [brief]
        if story:
            parts.append(
                f"Story {story.id}: {story.title} (step {story.step}, round {story.rounds})"
            )
        if role == MANAGER:
            parts.append(self._manager_context())
        return "\n\n".join(parts)

    def _manager_context(self) -> str:
        overrides = {
            r: {"model": o.model, "effort": o.effort, "reason": o.reason}
            for r, o in self.state.overrides.items()
            if not o.reviewed
        }
        capped = [s.id for s in self.state.stories.values() if s.needs_manager]
        return "Runner context:\n" + json.dumps(
            {
                "review_reasons": self.state.manager_due,
                "unreviewed_overrides": overrides,
                "stories_at_round_cap": capped,
            },
            indent=2,
        )

    # ----- running -------------------------------------------------------

    async def run_role(self, role: str, brief: str, story_id: str | None = None) -> dict[str, Any]:
        """Run one role step end to end and return a report for the PO."""
        reason = self.refusal(role, story_id)
        if reason:
            return {"status": "refused", "reason": reason}
        self.settle_po()
        story = self.state.stories.get(story_id) if story_id else None
        try:
            plan = self.plan(role, brief, story)
        except sandbox.SandboxError as exc:
            return {"status": "refused", "reason": str(exc)}
        try:
            result = await collect(self.query_fn, plan.prompt, plan.options)
        finally:
            if plan.prepared:
                plan.prepared.stop()
        return self.settle(plan, story, result)

    def settle(
        self, plan: Plan, story: gates.StoryState | None, result: StepResult
    ) -> dict[str, Any]:
        """Record cost, commit/quarantine, check the gate and save state."""
        self.record_cost(plan.role, result.cost, story)
        report: dict[str, Any] = {"role": plan.role.name, "cost_usd": round(result.cost, 4)}
        report.update(self.settle_tree(plan.role.name, plan.scope, story))
        try:
            handoff = parse_handoff(result.text)
        except HandoffError as exc:
            report.update(status="bad_handoff", reason=str(exc))
            self._bounce_on_bad_handoff(story, plan.role.name)
            self.save()
            return report
        report.update(
            status=handoff.status,
            summary=handoff.summary,
            open_questions=handoff.open_questions,
            next_role=handoff.next_role,
        )
        self.after_handoff(plan, story, handoff, result.text, report)
        self.save()
        return report

    def _bounce_on_bad_handoff(self, story: gates.StoryState | None, role: str) -> None:
        if story and gates.role_fits_step(role, story.step):
            outcome = gates.Outcome(False, "malformed handoff")
            gates.advance(story, outcome, self.steps, self.config.gates.round_cap)

    def after_handoff(
        self,
        plan: Plan,
        story: gates.StoryState | None,
        handoff: Any,
        text: str,
        report: dict[str, Any],
    ) -> None:
        name = plan.role.name
        if name == MANAGER:
            self.apply_manager(story, handoff.ruling)
        elif story:
            report["gate"] = self.gate(story, handoff)
        if plan.prepared and plan.prepared.delivery.kind == "manual":
            stories = [story.id] if story else []
            report["question_id"] = self.relay.post("question", text, stories).id

    def record_cost(self, role: ResolvedRole, cost: float, story: gates.StoryState | None) -> None:
        before = self.ledger.total()
        self.ledger.record(Entry(role.name, role.model, cost, story.id if story else None))
        team = self.config.team
        if checkpoint_crossed(before, before + cost, team.budget_usd, team.manager_every_pct):
            self.state.manager_due.append(f"budget checkpoint at ${before + cost:.2f}")

    def settle_tree(
        self, role: str, scope: guard.Scope, story: gates.StoryState | None
    ) -> dict[str, str | None]:
        """Quarantine out-of-scope changes, then commit in-scope ones."""
        audit = guard.audit_step(self.git, scope)
        quarantined = (
            guard.quarantine(self.git, role, audit.out_of_scope) if audit.out_of_scope else None
        )
        commit = self.commit_step(role, audit.in_scope, story) if audit.in_scope else None
        return {"commit": commit, "quarantine": quarantined}

    def commit_step(self, role: str, paths: list[str], story: gates.StoryState | None) -> str:
        """First commit of a story is ``feat``; later ones are fixups of it."""
        if story is None:
            return self.git.commit(paths, f"chore(team): {role} step")
        if story.commit:
            return self.git.commit_fixup(paths, story.commit)
        story.commit = self.git.commit(paths, f"feat({story.id}): {story.title}")
        return story.commit

    def gate(self, story: gates.StoryState, handoff: Any) -> dict[str, Any]:
        """Evaluate the story's current step gate and advance the story."""
        step = story.step
        outcome = gates.evaluate(step, handoff, self.checks, self.steps)
        gates.advance(story, outcome, self.steps, self.config.gates.round_cap)
        return {
            "step": step,
            "passed": outcome.passed,
            "reason": outcome.reason,
            "now_at": "done" if story.done else story.step,
            "rounds": story.rounds,
            "needs_manager": story.needs_manager,
        }

    def apply_manager(self, story: gates.StoryState | None, ruling: str | None) -> None:
        """A Manager step clears the review queue and rules on a capped story."""
        self.state.manager_due.clear()
        for override in self.state.overrides.values():
            override.reviewed = True
        if story and story.needs_manager and ruling:
            gates.apply_ruling(story, ruling, self.steps)
