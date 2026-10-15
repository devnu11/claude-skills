"""``agile-team`` command line: init | config check | roles | start | status | answer | stop.

Run from the target repo's root. Every subcommand returns an exit code; errors
print ``agile-team <cmd>: <message>`` and return 1.
"""

from __future__ import annotations

import argparse
import asyncio
import functools
import json
import signal
import sys
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass, fields, replace
from enum import StrEnum
from pathlib import Path
from typing import Any

from . import (
    checkout,
    gates,
    halt,
    keys,
    onboard,
    opinions,
    pending_tests,
    presentation,
    reconcile,
    recovery,
    repin,
    requirements,
    revert_log,
    sandbox,
    shares,
    stages,
    story_drafts,
    story_spec,
    suite_runs,
    system,
    test_reports,
    threads,
    watch,
)
from . import config as config_mod
from . import state as state_mod
from .commands import shell_runner
from .dashboard import server
from .dispatch import QueryFn, Runtime, StepResult
from .git_ops import Git
from .ledger import LEDGER, Ledger, budget_status
from .po_tools import Start, StartMode, run_po
from .preflight import Preflight
from .providers import DEFAULT as DEFAULT_PROVIDER
from .providers import Providers
from .relay import Relay, RelayError
from .roles import (
    REPO_ROLES,
    Layer,
    ResolvedRole,
    RoleBook,
    RoleError,
    expand_globs,
    user_roles_dir,
)
from .salvage import Cause
from .sharing import Shares
from .story_drafts import (
    Action,
    Approval,
    Checked,
    Known,
    Placing,
    StoryRequest,
    draft_problems,
    option_problems,
)
from .story_intake import StoryQueue
from .upstream import GhPrs, command_runner

ANSWER_FIELDS = tuple(f.name for f in fields(onboard.Answers))


START_REFUSED = (
    "story files: {refusal}; story amend cannot change depends_on, so the human fixes it: "
    "edit depends_on in the story's file in {folder}, git commit it, then agile-team start "
    "again (agile-team accept-checkout first if start halts on the moved checkout)"
)


class CliError(Exception):
    """A user-facing failure; the message is printed as is."""


class StopMode(StrEnum):
    """When ``agile-team stop`` takes effect."""

    AFTER_STEP = "after-step"
    NOW = "now"


class Browser(StrEnum):
    """Whether ``dashboard`` opens a browser tab."""

    OPEN = "open"
    SKIP = "skip"


@dataclass(frozen=True)
class Place:
    """Where the CLI works: the target repo and the home holding ``~/secrets``."""

    repo: Path
    home: Path

    @classmethod
    def of(cls, args: argparse.Namespace) -> Place:
        return cls(repo_of(args), home_of(args))


def repo_of(args: argparse.Namespace) -> Path:
    """The ``--repo`` path, resolved once so every derived path is absolute."""
    return system.resolve(Path(args.repo))


def home_of(args: argparse.Namespace) -> Path:
    """The ``--home`` path, or the user's home when it is absent."""
    return Path(args.home) if args.home else system.home()


def default_query() -> QueryFn:
    from claude_agent_sdk import query

    return query


def print_json(data: Any) -> None:
    print(json.dumps(data, indent=2))


def role_book(config: config_mod.Config, home: Path) -> RoleBook:
    """Built-in, global and repo roles; the global layer lives under ``home``."""
    return RoleBook.for_repo(config.repo, config.roles, user_roles_dir(home, system.environ()))


def _load_config(repo: Path) -> config_mod.Config:
    try:
        return config_mod.load(repo)
    except config_mod.ConfigError as exc:
        raise CliError(str(exc)) from exc


# ----- dashboard ---------------------------------------------------------


def cmd_dashboard(args: argparse.Namespace) -> int:
    """Serve the read-only dashboard until interrupted."""
    httpd = _dashboard_server(args)
    urls = server.dashboard_urls(*httpd.server_address[:2])
    local = server.with_token(urls.local, httpd.app.token)  # type: ignore[attr-defined]
    print(f"dashboard: {local}", flush=True)
    if urls.lan:
        print(f"from other machines: {urls.lan}", flush=True)
    if args.browser is Browser.OPEN:
        system.open_browser(local)
    server.serve(httpd)
    return 0


def _dashboard_server(args: argparse.Namespace) -> system.HttpServer:
    place = Place.of(args)
    config = _load_config(place.repo)
    app = server.Dashboard.for_run(config, role_book(config, place.home))
    app = replace(app, token=args.token or config.dashboard.token or system.token())
    address = (args.host or server.default_host(), args.port)
    try:
        return server.open_server(address, app)
    except OSError as exc:
        raise CliError(f"cannot listen on {address[0]}:{address[1]}: {exc.strerror}") from exc


# ----- init --------------------------------------------------------------


def cmd_detect(args: argparse.Namespace) -> int:
    """Print the detected preset and what it would configure."""
    print_json(detection(repo_of(args), onboard.load_presets()))
    return 0


def detection(repo: Path, presets: dict[str, Any]) -> dict[str, Any]:
    """The preset that fits ``repo``, or the known presets when none does."""
    name = onboard.detect(repo, presets)
    if name is None:
        return {"preset": None, "known": sorted(presets)}
    preset = presets[name]
    return {
        "preset": name,
        "environment_kind": onboard.suggest_kind(repo, preset),
        "commands": preset["commands"],
        "globs": preset["globs"],
    }


def cmd_init(args: argparse.Namespace) -> int:
    """Phase A onboarding: write the config, charter and ignores, then commit."""
    repo = repo_of(args)
    _require_init_inputs(repo, args)
    try:
        sha = onboard.onboard(repo, answers_from(args))
    except (FileExistsError, ValueError) as exc:
        raise CliError(str(exc)) from exc
    print(f"onboarded: {sha}" if sha else "nothing to change")
    return 0


def _require_init_inputs(repo: Path, args: argparse.Namespace) -> None:
    if not Git(repo).is_repo():
        raise CliError(f"not a git repository: {repo}; run git init first")
    if not Git(repo).is_clean():
        raise CliError("working tree is dirty; commit or stash first")
    if not args.preset or not args.environment_kind:
        raise CliError("--preset and --environment are required (see --detect)")


def answers_from(args: argparse.Namespace) -> onboard.Answers:
    """The init answers; argparse dests are named after ``Answers`` fields."""
    return onboard.Answers(**{name: getattr(args, name) for name in ANSWER_FIELDS})


# ----- config check --------------------------------------------------------


def cmd_config_check(args: argparse.Namespace) -> int:
    place = Place.of(args)
    config = _load_config(place.repo)
    problems = check_config(config, place.home)
    _print_lines("warning", config.warnings)
    _print_lines("problem", problems)
    print("config ok" if not problems else f"{len(problems)} problem(s)")
    return 1 if problems else 0


def cmd_requirements(args: argparse.Namespace) -> int:
    """``requirements check``: print the problems and AC coverage; exit 1 on problems (s1 T6-T8)."""
    report = requirements.report(requirements.load(_load_config(repo_of(args))))
    print_json(report)
    return 1 if report["problems"] else 0


def _print_lines(prefix: str, lines: list[str]) -> None:
    for line in lines:
        print(f"{prefix}: {line}")


def check_config(config: config_mod.Config, home: Path) -> list[str]:
    """Static config problems plus every role's resolution and glob expansion."""
    book = role_book(config, home)
    known = config_mod.Known(book.names(), set(sandbox.ENVIRONMENT_KINDS))
    return config_mod.validate(config, known) + _role_problems(book, config)


def _role_problems(book: RoleBook, config: config_mod.Config) -> list[str]:
    problems = []
    for name in sorted(book.names()):
        try:
            _check_role(book.resolve(name), config)
        except RoleError as exc:
            problems.append(f"role {name}: {exc}")
    return problems


def _check_role(role: ResolvedRole, config: config_mod.Config) -> None:
    values = config.placeholders()
    expand_globs(role.write, values)
    expand_globs(role.read, values)
    if role.provider not in {DEFAULT_PROVIDER, *config.providers}:
        raise RoleError(f"unknown provider {role.provider!r}; add [providers.{role.provider}]")


# ----- roles ---------------------------------------------------------------


def cmd_roles(args: argparse.Namespace) -> int:
    return ROLE_ACTIONS[args.action](args)


def _book(args: argparse.Namespace) -> RoleBook:
    place = Place.of(args)
    return role_book(_load_config(place.repo), place.home)


def roles_list(args: argparse.Namespace) -> int:
    """Print each role's layers and its resolved model, provider and scope."""
    book = _book(args)
    print_json({name: role_summary(book, name) for name in ["_shared", *sorted(book.names())]})
    return 0


def role_summary(book: RoleBook, name: str) -> dict[str, Any]:
    summary: dict[str, Any] = {"layers": book.layers(name)}
    if name == "_shared":
        return summary
    try:
        role = book.resolve(name)
    except RoleError as exc:
        return summary | {"error": str(exc)}
    keys = ("enabled", "provider", "model", "effort", "write")
    return summary | {k: getattr(role, k) for k in keys}


def roles_scaffold(args: argparse.Namespace) -> int:
    """Write a commented stub for every role that has no file in the chosen layer yet."""
    place = Place.of(args)
    target = scaffold_dir(place, args.layer)
    created = _book(args).scaffold(target, args.layer)
    for path in created:
        print(f"created {path}")
    print(f"{len(created)} stub(s) in {target}" if created else f"nothing to add in {target}")
    return 0


def scaffold_dir(place: Place, layer: Layer) -> Path:
    if layer is Layer.GLOBAL:
        return user_roles_dir(place.home, system.environ())
    return place.repo / REPO_ROLES


ROLE_ACTIONS: dict[str, Callable[[argparse.Namespace], int]] = {
    "list": roles_list,
    "scaffold": roles_scaffold,
}


# ----- start ---------------------------------------------------------------


def reporting_of(config: config_mod.Config) -> test_reports.Reporting:
    """How the repo's test runs write reports and read the pending-tests registry."""
    return test_reports.Reporting(
        config.toolchain.report,
        config.run_dir / test_reports.FOLDER,
        functools.partial(pending_tests.read, config.repo),
        test_reports.changed_for(Git(config.repo)),
    )


def make_pipeline(config: config_mod.Config) -> gates.Pipeline:
    """The configured steps and round cap, with command gates run in the repo."""
    baseline = gates.load_baseline(config.repo).get("coverage")
    commands, threshold = config.toolchain.commands, config.gates.coverage
    missing = functools.partial(presentation.missing, config)
    live = presentation.Trial(config).liveness
    read = functools.partial(gates.read_repo_file, config.repo)
    runner = shell_runner(config.repo, config.gates.command_timeout_s)
    suite = functools.partial(suite_runs.declared, config.stories_dir)
    spec = functools.partial(story_spec.read, config)
    checks = gates.Checks(
        commands,
        threshold,
        runner,
        baseline,
        missing,
        live,
        read=read,
        suite_runs=suite,
        story_spec=spec,
        environments=functools.partial(story_spec.environment_names, config),
        design_file=functools.partial(revert_log.design_file, config.team.docs_dir),
        traced=functools.partial(requirements.trace_reasons, config),
        shares=functools.partial(shares.check, config),
        reporting=reporting_of(config),
    )
    g = config.gates
    return gates.Pipeline(g.pipeline, g.round_cap, checks, g.repeat, g.backstop)


def make_runtime(place: Place, query_fn: QueryFn) -> Runtime:
    """Wire config, roles, git, ledger, relay, state and the API key together."""
    config = _load_config(place.repo)
    locations = keys.KeyLocations(place.repo, config.team.key_file, place.home)
    return Runtime(
        config=config,
        book=role_book(config, place.home),
        git=Git(place.repo),
        ledger=Ledger(config.run_dir / LEDGER),
        relay=Relay(config.run_dir),
        state=state_mod.load(config.run_dir),
        env=auth_env(config, locations),
        secrets=locations.secret_paths(),
        providers=Providers(config.providers, system.environ()),
        query_fn=query_fn,
        pipeline=make_pipeline(config),
        prs=GhPrs(command_runner(place.repo)),
        shell=functools.partial(shell_runner, limit_s=config.gates.command_timeout_s),
    )


def auth_env(config: config_mod.Config, locations: keys.KeyLocations) -> dict[str, str]:
    """The key for api-key auth; nothing for login auth, so Claude Code uses its login."""
    if config.team.auth == config_mod.LOGIN_AUTH:
        return {}
    return keys.child_env(keys.read_key(locations.resolve().path))


def start_from(args: argparse.Namespace) -> Start:
    """The PO's task and start mode; only a resume may omit the task."""
    if args.mode is not StartMode.RESUME and not args.task:
        raise CliError("--task is required unless --resume")
    return Start(args.task or "", args.mode)


def cmd_start(args: argparse.Namespace, query_fn: QueryFn | None = None) -> int:
    """Preflight, then run the Product Owner loop in the foreground."""
    place, start = Place.of(args), start_from(args)
    pin = repin.Pin(place.repo, repin.start_argv(place.repo, args.home))
    try:
        runtime = _prepared(args, place, start, query_fn)
    except Exception as exc:
        repin.failed_start(pin, exc)
        raise
    if isinstance(runtime, int):
        return runtime
    repin.confirm(runtime)
    return _repin_or(_run(runtime, start), runtime, pin)


def _prepared(
    args: argparse.Namespace, place: Place, start: Start, query_fn: QueryFn | None
) -> Runtime | int:
    """Everything before the run; an exit code when the checkout guard ends the start."""
    config = _load_config(place.repo)
    moved = checkout.Guard(config.run_dir, Git(config.repo)).on_start()
    if moved:
        return _report(moved)
    _recover(config, start)
    _require_preflight(config, place.home)
    _reconcile(config)
    runtime = make_runtime(place, query_fn or default_query())
    runtime.report_load_faults()
    _load_dependencies(runtime)
    kept = runtime.state.cadence if start.mode is StartMode.RESUME else config.team.cadence
    runtime.state.cadence = args.cadence or kept
    _record_task(runtime.state, start)
    repin.drop_unpinned(runtime)
    return runtime


def _repin_or(code: int, runtime: Runtime, pin: repin.Pin) -> int:
    """P3: after a clean run end that asked for it, re-pin; else keep the exit code."""
    state = runtime.state
    if code != 0 or runtime.halted_by or runtime.stop_requested() or not state.repin:
        return code
    old = repin.pin_commit(runtime.config.run_dir)
    marker = repin.Marker(old, state.repin, state.sprint, repin.Outcome.TRIAL)
    state.repin = ""
    state.mark(state_mod.RunStatus.IDLE, repin.REPINNING.format(new7=marker.new[:7]))
    runtime.save()
    pin.repin(marker)


def _load_dependencies(runtime: Runtime) -> None:
    """Load story dependencies from the files; a bad list stops the start (s86 DP3)."""
    if refusal := runtime.load_dependencies():
        raise CliError(START_REFUSED.format(refusal=refusal, folder=config_mod.STORIES_DIR))


def _record_task(state: state_mod.RunState, start: Start) -> None:
    """Remember the run's task; a resume's ``--task`` is only a message to the PO."""
    if start.mode is not StartMode.RESUME:
        state.task = start.task


RECOVERED_LEADS: dict[Cause, str] = {Cause.KILLED: "the last run was killed"}
RECOVERED_LEAD = "the last run halted ({cause}) before its edits were saved"


def _recover(config: config_mod.Config, start: Start) -> None:
    """On ``--resume`` after a kill, save the dead run's edits so preflight passes."""
    if start.mode is not StartMode.RESUME:
        return
    found = recovery.recover_cut(config.run_dir, Git(config.repo))
    if found and found.sha:
        lead = RECOVERED_LEADS.get(found.cause) or RECOVERED_LEAD.format(cause=found.cause)
        saved = f"{found.label}'s edits are saved in {found.sha} (reverted)"
        print(f"agile-team start: {lead}; {saved}", file=sys.stderr)


def _reconcile(config: config_mod.Config) -> None:
    """s10: ledger the spend a crash cut off, and say so on stderr."""
    for entry in reconcile.reconcile_ledger(config.run_dir):
        print(reconcile.told_line(entry), file=sys.stderr)


def _require_preflight(config: config_mod.Config, home: Path) -> None:
    failures = Preflight(config, Git(config.repo), home).run_all() + check_config(config, home)
    if failures:
        raise CliError("preflight failed:\n  " + "\n  ".join(failures))


def _run(runtime: Runtime, start: Start) -> int:
    with pid_file(runtime.config.run_dir):
        try:
            result = asyncio.run(_po_until_sigterm(runtime, start))
        except (Exception, asyncio.CancelledError) as exc:
            return _halt_exit(runtime, exc)
    return _finish(runtime, result)


async def _po_until_sigterm(runtime: Runtime, start: Start) -> StepResult:
    """Run the PO as a task that SIGTERM (``stop --now``) cancels."""
    task = asyncio.current_task()
    system.on_signal(signal.SIGTERM, task.cancel)
    runtime.pulse.start()
    try:
        return await run_po(runtime, start)
    finally:
        runtime.pulse.end()


def _halt_exit(runtime: Runtime, exc: BaseException) -> int:
    halt.log_traceback(runtime.config.run_dir, exc)
    return _report(runtime.halt_run(halt.classify(exc)))


def _finish(runtime: Runtime, result: StepResult) -> int:
    """Print the PO's text; exit with the halt's code if a role step halted the run."""
    print(result.text)
    if runtime.halted_by:
        return _report(runtime.halt_run(runtime.halted_by))
    return 0


def _report(found: halt.Halt) -> int:
    print(f"agile-team start: {found.message()}", file=sys.stderr)
    return found.rule.exit_code


@contextmanager
def pid_file(run_dir: Path) -> Iterator[None]:
    """Clear any stale stop request and record this process for ``stop --now``."""
    system.make_dirs(run_dir)
    system.remove(run_dir / state_mod.STOP_FILE)
    path = run_dir / state_mod.PID_FILE
    system.write_text(path, str(system.pid()))
    try:
        yield
    finally:
        system.remove(path)


# ----- status / answer / stop ----------------------------------------------


def tools_report(config: config_mod.Config) -> dict[str, list[dict[str, str]]]:
    """The built-in stages and the repo's ``[[tool]]`` rows."""
    return {
        "built_in": [stage.as_dict() for stage in stages.STAGES.values()],
        "repo": [asdict(tool) for tool in config.tools],
    }


def cmd_tools(args: argparse.Namespace) -> int:
    print_json(tools_report(_load_config(repo_of(args))))
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    print_json(status_report(_load_config(repo_of(args))))
    return 0


def status_report(config: config_mod.Config) -> dict[str, Any]:
    """Run state, open questions and budget, for the liaison."""
    st = state_mod.load(config.run_dir)
    unread = Relay(config.run_dir).unread(st.told)
    return {
        "status": state_mod.shown_status(config.run_dir, st),
        "status_reason": st.status_reason,
        "cadence": st.cadence,
        "sprint": st.sprint,
        "running": state_mod.runner_alive(config.run_dir),
        "in_flight": asdict(st.in_flight) if st.in_flight else None,
        "interrupted": [asdict(i) for i in st.interrupted],
        "stories": {k: asdict(v) for k, v in st.stories.items()},
        "manager_due": st.manager_due,
        "open_questions": [asdict(m) for m in Relay(config.run_dir).open_questions()],
        "budget": budget_status(Ledger(config.run_dir / LEDGER), config.team.budget_usd),
        "boundary": asdict(st.boundary) if st.boundary else None,
        "upstream": asdict(st.upstream),
        "checkout": asdict(st.checkout) if st.checkout else None,
        "queued_messages": [t.id for t in unread],
        "queued_shares": [s.id for s in Shares(config.run_dir).pending(st.shares)],
        "shares": st.shares,
        "queued_stories": [r.id for r in StoryQueue(config.run_dir).pending(st.story_requests)],
        "story_requests": st.story_requests,
    }


def cmd_answer(args: argparse.Namespace) -> int:
    config = _load_config(repo_of(args))
    try:
        Relay(config.run_dir).answer(args.id, args.text)
    except RelayError as exc:
        raise CliError(str(exc)) from exc
    print(f"answered {args.id}")
    return 0


def _message_text(source: str) -> str:
    try:
        return sys.stdin.read() if source == "-" else system.read_text(Path(source))
    except OSError as exc:
        raise CliError(f"cannot read {source}: {exc.strerror}") from exc


def cmd_tell(args: argparse.Namespace) -> int:
    """Queue a message for the PO; the text is stored in a file, never on a command line."""
    config = _load_config(repo_of(args))
    text = _message_text(args.source)
    if not text.strip():
        raise CliError("the message is empty")
    told = Relay(config.run_dir).tell(text)
    print(f"queued {told.id} for the PO: {told.path.relative_to(config.repo)}")
    return 0


def cmd_share(args: argparse.Namespace) -> int:
    """Queue a file for the team (s120); the runner copies and commits it between steps."""
    config = _load_config(repo_of(args))
    share = shares.Share("", args.story, Path(args.source).name, b"")
    if refusal := shares.story_refusal(config, share):
        raise CliError(refusal)
    data = _share_bytes(args.source)
    share = replace(share, data=data)
    queued = Shares(config.run_dir).queue(share)
    path = shares.target_of(config.team.docs_dir, queued)
    print(shares.QUEUED.format(id=queued.id, path=path, short=queued.sha256()[: shares.SHORT]))
    return 0


TARGET_COUNTS = {Action.NEW: 1, Action.AMEND: 2}


def _story_request(args: argparse.Namespace, config: config_mod.Config) -> StoryRequest:
    """The request for ``story <action> <target…>``; USAGE when the target count is wrong."""
    action = Action(args.action)
    if len(args.target) != TARGET_COUNTS[action]:
        raise CliError(story_drafts.USAGE)
    *story, file = args.target
    default = Placing.BACKLOG.value if action is Action.NEW else ""
    plan = shares.resolved_path(config.repo, args.plan) or args.plan if args.plan else ""
    return StoryRequest(
        "", action, "".join(story), Approval(args.approved_by), plan,
        args.sprint or default, args.after, file, "",
    )  # fmt: skip


def _read_draft(request: StoryRequest) -> tuple[StoryRequest, str | None]:
    """``request`` holding the draft's text, and the read problem line when it can't be read."""
    try:
        return replace(request, text=system.read_text(Path(request.file))), None
    except OSError as exc:
        return request, story_drafts.CANNOT_READ.format(file=request.file, error=exc.strerror)


def _story_known(config: config_mod.Config, request: StoryRequest) -> Known:
    names = tuple(e.name for e in config.environments)
    stories = state_mod.load(config.run_dir).stories
    try:
        target = system.read_text(config.repo / story_spec.file_of(config, request.story))
    except OSError:
        target = None
    return Known(names, stories, target if request.story else None)


def _plan_problems(config: config_mod.Config, request: StoryRequest) -> list[str]:
    if not request.plan or system.is_file(config.repo / request.plan):
        return []
    return [story_drafts.PLAN_MISSING.format(plan=request.plan)]


def _story_checks(config: config_mod.Config, drafted: tuple[StoryRequest, str | None]) -> Checked:
    """Every problem line with a draft, as ``Checked``; its draft is set when all is clean."""
    request, unread = drafted
    known = _story_known(config, request)
    lines = (unread, *story_drafts.target_status_problems(request, known))
    checked = Checked(None, lines) if unread else draft_problems(request, known)
    more = [*option_problems(request, known), *_plan_problems(config, request)]
    return replace(checked, problems=(*checked.problems, *more))


def cmd_story(args: argparse.Namespace) -> int:
    """Check a liaison's story draft and queue it for the runner (s135); never commits."""
    config = _load_config(repo_of(args))
    request, unread = _read_draft(_story_request(args, config))
    checked = _story_checks(config, (request, unread))
    if checked.problems:
        raise CliError("\n".join(checked.problems))
    queued = StoryQueue(config.run_dir).queue(request)
    title = checked.draft.spec.title if checked.draft else ""
    approved = story_drafts.APPROVED[request.approved_by]
    text = story_drafts.QUEUED[request.action]
    print(text.format(id=queued.id, title=title, story=request.story, approved=approved))
    return 0


def _share_bytes(source: str) -> bytes:
    try:
        data = system.read_bytes(Path(source))
    except OSError as exc:
        text = shares.REFUSALS[shares.Refused.UNREADABLE]
        raise CliError(text.format(source=source, error=exc.strerror)) from exc
    if refusal := shares.data_refusal(data):
        raise CliError(refusal)
    return data


def cmd_reply(args: argparse.Namespace) -> int:
    """Reply on a story's thread as the liaison; the text comes from a file or stdin."""
    config = _load_config(repo_of(args))
    text = _message_text(args.source)
    stories = state_mod.load(config.run_dir).stories
    reason = threads.text_refusal(text) or threads.story_refusal(args.story, stories)
    if reason:
        raise CliError(reason)
    entry = threads.Threads(config.run_dir).reply(args.story, text)
    print(threads.REPLIED.format(id=entry.id, story=entry.story))
    return 0


def cmd_opinion(args: argparse.Namespace) -> int:
    """Record the liaison's opinion on a story; the text comes from a file or stdin."""
    config = _load_config(repo_of(args))
    text = _message_text(args.source)
    stories = state_mod.load(config.run_dir).stories
    reason = (
        threads.story_refusal(args.story, stories)
        or opinions.kind_refusal(args.kind)
        or threads.text_refusal(text)
    )
    if reason:
        raise CliError(reason)
    kind = opinions.Kind(args.kind)
    made = opinions.Opinions(config.run_dir).record(args.story, kind, text)
    print(opinions.RECORDED.format(id=made.id, kind=made.kind, story=made.story))
    return 0


def cmd_reviewed(args: argparse.Namespace) -> int:
    """Record that the liaison reviewed the backlog, with a summary from a file or stdin."""
    config = _load_config(repo_of(args))
    text = _message_text(args.source)
    reason = threads.text_refusal(text)
    if reason:
        raise CliError(reason)
    print(opinions.REVIEWED.format(id=opinions.Opinions(config.run_dir).review(text).id))
    return 0


def cmd_watch(args: argparse.Namespace) -> int:
    """Block until the liaison is needed; print one JSON line."""
    config = _load_config(repo_of(args))
    line = watch.Watcher(config.run_dir).until(args.timeout_s)
    print(json.dumps(line), flush=True)
    return 0


def cmd_pending_tests(args: argparse.Namespace) -> int:
    """Print the skip options of every pending test id under ``--root`` (s125 P19)."""
    config = _load_config(repo_of(args))
    registry = pending_tests.read(config.repo)
    ids = tuple(i for story_ids in registry.entries.values() for i in story_ids)
    print(test_reports.skip_line(config.toolchain.report, test_reports.Under(args.root, ids)))
    return 0


def cmd_stop(args: argparse.Namespace) -> int:
    """Ask the runner to stop after its step; ``--now`` also signals it."""
    pid = _request_stop(repo_of(args)) / state_mod.PID_FILE
    if args.stop is StopMode.NOW and system.is_file(pid):
        system.kill(int(system.read_text(pid)), signal.SIGTERM)
        print("stop requested; runner signalled")
        return 0
    print("stop requested; the team stops after the current step")
    return 0


def cmd_accept_checkout(args: argparse.Namespace) -> int:
    """Keep the current branch and HEAD as the checkout the runner expects (s61)."""
    config = _load_config(repo_of(args))
    if state_mod.runner_alive(config.run_dir):
        raise CliError("the runner is running; stop it first")
    try:
        record = checkout.Guard(config.run_dir, Git(config.repo)).accept()
    except checkout.CheckoutError as exc:
        raise CliError(str(exc)) from exc
    print(f"accepted checkout {record.text()}")
    return 0


def _request_stop(repo: Path) -> Path:
    run_dir = _load_config(repo).run_dir
    system.make_dirs(run_dir)
    system.write_text(run_dir / state_mod.STOP_FILE, "")
    return run_dir


# ----- parser ----------------------------------------------------------------

Arg = tuple[tuple[str, ...], dict[str, Any]]


@dataclass(frozen=True)
class Command:
    """One subcommand: its name, help, handler and arguments."""

    name: str
    help: str
    func: Callable[[argparse.Namespace], int]
    args: tuple[Arg, ...] = ()


GLOBAL_ARGS: tuple[Arg, ...] = (
    (("--repo",), {"default": ".", "help": "target repo root (default: cwd)"}),
    (("--home",), {"help": argparse.SUPPRESS}),
)
INIT_ARGS: tuple[Arg, ...] = (
    (("--detect",), {"action": "store_const", "dest": "func", "const": cmd_detect,
                     "help": "print the detected preset and exit"}),
    (("--preset",), {}),
    (
        ("--environment",),
        {"dest": "environment_kind", "choices": sorted(sandbox.ENVIRONMENT_KINDS)},
    ),
    (("--url",), {"default": "", "help": "web environment URL"}),
    (("--docs-dir",), {"default": "docs"}),
    (("--artifacts",), {"choices": config_mod.ARTIFACT_POLICIES, "default": "committed"}),
    (("--key-file",), {"default": config_mod.DEFAULT_KEY_FILE}),
    (("--auth",), {"choices": config_mod.AUTH_MODES, "default": config_mod.API_KEY_AUTH,
                   "help": "login: run on your Claude Code login instead of an API key"}),
    (("--budget",), {"dest": "budget_usd", "type": float, "default": 20.0}),
    (("--cadence",), {"choices": config_mod.CADENCES, "default": "sprint"}),
    (("--reconfigure",), {"action": "store_const", "dest": "mode",
                          "const": onboard.WriteMode.RECONFIGURE,
                          "default": onboard.WriteMode.CREATE}),
)  # fmt: skip
START_ARGS: tuple[Arg, ...] = (
    (("--task",), {"help": "the task for the Product Owner"}),
    (("--cadence",), {"choices": config_mod.CADENCES}),
    (("--onboard",), {"action": "store_const", "dest": "mode", "const": StartMode.ONBOARD,
                      "default": StartMode.WORK, "help": "run the onboarding sprint"}),
    (("--resume",), {"action": "store_const", "dest": "mode", "const": StartMode.RESUME,
                     "help": "continue the previous run"}),
)  # fmt: skip
ROLES_ARGS: tuple[Arg, ...] = (
    (("action",), {"choices": sorted(ROLE_ACTIONS)}),
    (("--global",), {"action": "store_const", "dest": "layer", "const": Layer.GLOBAL,
                     "default": Layer.REPO,
                     "help": "scaffold ~/.config/agile-team/roles instead of .team/roles"}),
)  # fmt: skip
STOP_ARGS: tuple[Arg, ...] = (
    (("--now",), {"action": "store_const", "dest": "stop", "const": StopMode.NOW,
                  "default": StopMode.AFTER_STEP, "help": "also SIGTERM the runner"}),
)  # fmt: skip
DASHBOARD_ARGS: tuple[Arg, ...] = (
    (("--host",), {"default": None,
                   "help": "address to bind (default: all interfaces; 127.0.0.1 on Windows)"}),
    (("--port",), {"type": int, "default": server.DEFAULT_PORT}),
    (("--token",), {"default": None, "help": "fix the write token (default: random each start)"}),
    (("--no-open",), {"action": "store_const", "dest": "browser", "const": Browser.SKIP,
                      "default": Browser.OPEN, "help": "do not open a browser"}),
)  # fmt: skip
WATCH_ARGS: tuple[Arg, ...] = (
    (("--timeout",), {"dest": "timeout_s", "type": float, "default": None,
                      "help": "print a heartbeat line after this many seconds"}),
)  # fmt: skip
PENDING_ARGS: tuple[Arg, ...] = (
    (("--root",), {"default": "", "help": "repo-relative directory pytest runs in"}),
)  # fmt: skip
STORY_ARGS: tuple[Arg, ...] = (
    (("action",), {"choices": [a.value for a in Action]}),
    (("target",), {"nargs": "+", "help": "new: <file.md>; amend: <id> <file.md>"}),
    (("--approved-by",), {"required": True, "dest": "approved_by",
                          "choices": [a.value for a in Approval]}),
    (("--sprint",), {"choices": [p.value for p in Placing], "default": None}),
    (("--after",), {"default": "", "help": "place it right after this story"}),
    (("--plan",), {"default": "", "help": "the approved plan (needs --approved-by human)"}),
)  # fmt: skip
COMMANDS = (
    Command("init", "phase A onboarding (no API calls)", cmd_init, INIT_ARGS),
    Command("config", "validate .agile-team.toml and roles", cmd_config_check,
            ((("action",), {"choices": ["check"]}),)),
    Command("requirements", "check the requirement files; print problems and AC coverage as JSON",
            cmd_requirements, ((("action",), {"choices": ["check"]}),)),
    Command("roles", "list role layers or scaffold instruction stubs", cmd_roles, ROLES_ARGS),
    Command("start", "run the team (blocks; run in the background)", cmd_start, START_ARGS),
    Command("status", "print run state as JSON", cmd_status),
    Command(
        "tools",
        "list the built-in runner stages and the repo's [[tool]] entries as JSON",
        cmd_tools,
    ),
    Command("answer", "answer a PO question", cmd_answer, ((("id",), {}), (("text",), {}))),
    Command("tell", "queue a message for the PO (a file, or - for stdin)", cmd_tell,
            ((("source",), {"help": "file holding the message, or - to read stdin"}),)),
    Command("share", "share a file with the team for a story (hash-checked at acceptance)",
            cmd_share,
            ((("source",), {"help": "the file to share; its name is kept (no stdin)"}),
             (("--story",), {"required": True, "help": "the story it is for, e.g. s118"}))),
    Command("story", "write a story (new) or replace its ACs (amend) from a draft file; "
            "the runner commits it", cmd_story, STORY_ARGS),
    Command("reply", "reply on a story's dashboard thread (a file, or - for stdin)", cmd_reply,
            ((("story",), {}),
             (("source",), {"help": "file holding the reply, or - to read stdin"}))),
    Command("opinion", "record the liaison's opinion on a story (a file, or - for stdin)",
            cmd_opinion,
            ((("story",), {}),
             (("kind",), {"help": ", ".join(opinions.Kind)}),
             (("source",), {"help": "file holding the opinion, or - to read stdin"}))),
    Command("reviewed", "record a backlog review's summary (a file, or - for stdin)",
            cmd_reviewed,
            ((("source",), {"help": "file holding the summary, or - to read stdin"}),)),
    Command("watch", "wait until the liaison is needed; print one JSON line", cmd_watch,
            WATCH_ARGS),
    Command("stop", "stop after the current step", cmd_stop, STOP_ARGS),
    Command("accept-checkout", "keep the current branch and HEAD after a checkout halt",
            cmd_accept_checkout),
    Command("pending-tests", "print the skip options for the pending test ids", cmd_pending_tests,
            PENDING_ARGS),
    Command("dashboard", "serve the read-only live dashboard (blocks; run in the background)",
            cmd_dashboard, DASHBOARD_ARGS),
)  # fmt: skip


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agile-team", description=__doc__)
    _add_args(parser, GLOBAL_ARGS)
    sub = parser.add_subparsers(dest="command", required=True)
    for command in COMMANDS:
        _add_command(sub, command)
    return parser


def _add_command(sub: Any, command: Command) -> None:
    parser = sub.add_parser(command.name, help=command.help)
    _add_args(parser, command.args)
    parser.set_defaults(func=command.func)


def _add_args(parser: argparse.ArgumentParser, args: tuple[Arg, ...]) -> None:
    for flags, options in args:
        parser.add_argument(*flags, **options)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (CliError, RoleError, keys.KeyNotFound) as exc:
        print(f"agile-team {args.command}: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
