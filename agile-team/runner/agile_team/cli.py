"""``agile-team`` command line: init | config check | roles | start | status | answer | stop.

Run from the target repo's root. Every subcommand returns an exit code; errors
print ``agile-team <cmd>: <message>`` and return 1.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import signal
import sys
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass, fields
from enum import StrEnum
from pathlib import Path
from typing import Any

from . import config as config_mod
from . import gates, keys, onboard, sandbox
from . import state as state_mod
from .dispatch import QueryFn, Runtime, shell_runner
from .git_ops import Git
from .ledger import Ledger, budget_status
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

LEDGER = "ledger.jsonl"
ANSWER_FIELDS = tuple(f.name for f in fields(onboard.Answers))
Kill = Callable[[int, int], None]


class CliError(Exception):
    """A user-facing failure; the message is printed as is."""


class StopMode(StrEnum):
    """When ``agile-team stop`` takes effect."""

    AFTER_STEP = "after-step"
    NOW = "now"


@dataclass(frozen=True)
class Place:
    """Where the CLI works: the target repo and the home holding ``~/secrets``."""

    repo: Path
    home: Path

    @classmethod
    def of(cls, args: argparse.Namespace) -> Place:
        return cls(Path(args.repo), Path(args.home))


def default_query() -> QueryFn:
    from claude_agent_sdk import query

    return query


def print_json(data: Any) -> None:
    print(json.dumps(data, indent=2))


def role_book(config: config_mod.Config, home: Path) -> RoleBook:
    """Built-in, global and repo roles; the global layer lives under ``home``."""
    return RoleBook.for_repo(config.repo, config.roles, user_roles_dir(home, os.environ))


def _load_config(repo: Path) -> config_mod.Config:
    try:
        return config_mod.load(repo)
    except config_mod.ConfigError as exc:
        raise CliError(str(exc)) from exc


# ----- init --------------------------------------------------------------


def cmd_detect(args: argparse.Namespace) -> int:
    """Print the detected preset and what it would configure."""
    print_json(detection(Path(args.repo), onboard.load_presets()))
    return 0


def detection(repo: Path, presets: dict[str, Any]) -> dict[str, Any]:
    """The preset that fits ``repo``, or the known presets when none does."""
    name = onboard.detect(repo, presets)
    if name is None:
        return {"preset": None, "known": sorted(presets)}
    preset = presets[name]
    return {
        "preset": name,
        "delivery_kind": onboard.suggest_kind(repo, preset),
        "commands": preset["commands"],
        "globs": preset["globs"],
    }


def cmd_init(args: argparse.Namespace) -> int:
    """Phase A onboarding: write the config, charter and ignores, then commit."""
    repo = Path(args.repo)
    _require_init_inputs(repo, args)
    try:
        sha = onboard.onboard(repo, answers_from(args))
    except (FileExistsError, ValueError) as exc:
        raise CliError(str(exc)) from exc
    print(f"onboarded: {sha}" if sha else "nothing to change")
    return 0


def _require_init_inputs(repo: Path, args: argparse.Namespace) -> None:
    if not Git(repo).is_clean():
        raise CliError("working tree is dirty; commit or stash first")
    if not args.preset or not args.delivery_kind:
        raise CliError("--preset and --delivery are required (see --detect)")


def answers_from(args: argparse.Namespace) -> onboard.Answers:
    """The init answers; argparse dests are named after ``Answers`` fields."""
    return onboard.Answers(**{name: getattr(args, name) for name in ANSWER_FIELDS})


# ----- config check --------------------------------------------------------


def cmd_config_check(args: argparse.Namespace) -> int:
    place = Place.of(args)
    problems = check_config(_load_config(place.repo), place.home)
    for problem in problems:
        print(f"problem: {problem}")
    print("config ok" if not problems else f"{len(problems)} problem(s)")
    return 1 if problems else 0


def check_config(config: config_mod.Config, home: Path) -> list[str]:
    """Static config problems plus every role's resolution and glob expansion."""
    book = role_book(config, home)
    known = config_mod.Known(book.names(), set(sandbox.DELIVERY_KINDS))
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
        return user_roles_dir(place.home, os.environ)
    return place.repo / REPO_ROLES


ROLE_ACTIONS: dict[str, Callable[[argparse.Namespace], int]] = {
    "list": roles_list,
    "scaffold": roles_scaffold,
}


# ----- start ---------------------------------------------------------------


def make_pipeline(config: config_mod.Config) -> gates.Pipeline:
    """The configured steps and round cap, with command gates run in the repo."""
    baseline = gates.load_baseline(config.repo).get("coverage")
    commands, threshold = config.toolchain.commands, config.gates.coverage
    checks = gates.Checks(commands, threshold, shell_runner(config.repo), baseline)
    return gates.Pipeline(list(config.gates.steps), config.gates.round_cap, checks)


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
        providers=Providers(config.providers, os.environ),
        query_fn=query_fn,
        pipeline=make_pipeline(config),
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
    config = _load_config(place.repo)
    _require_preflight(config, place.home)
    runtime = make_runtime(place, query_fn or default_query())
    runtime.state.cadence = args.cadence or config.team.cadence
    return _run(runtime, start)


def _require_preflight(config: config_mod.Config, home: Path) -> None:
    failures = Preflight(config, Git(config.repo), home).run_all() + check_config(config, home)
    if failures:
        raise CliError("preflight failed:\n  " + "\n  ".join(failures))


def _run(runtime: Runtime, start: Start) -> int:
    with pid_file(runtime.config.run_dir):
        result = asyncio.run(run_po(runtime, start))
    print(result.text)
    return 0


@contextmanager
def pid_file(run_dir: Path) -> Iterator[None]:
    """Clear any stale stop request and record this process for ``stop --now``."""
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / state_mod.STOP_FILE).unlink(missing_ok=True)
    path = run_dir / state_mod.PID_FILE
    path.write_text(str(os.getpid()))
    try:
        yield
    finally:
        path.unlink(missing_ok=True)


# ----- status / answer / stop ----------------------------------------------


def cmd_status(args: argparse.Namespace) -> int:
    print_json(status_report(_load_config(Path(args.repo))))
    return 0


def status_report(config: config_mod.Config) -> dict[str, Any]:
    """Run state, open questions and budget, for the liaison."""
    st = state_mod.load(config.run_dir)
    return {
        "status": st.status,
        "cadence": st.cadence,
        "sprint": st.sprint,
        "running": (config.run_dir / state_mod.PID_FILE).exists(),
        "stories": {k: asdict(v) for k, v in st.stories.items()},
        "manager_due": st.manager_due,
        "open_questions": [asdict(m) for m in Relay(config.run_dir).open_questions()],
        "budget": budget_status(Ledger(config.run_dir / LEDGER), config.team.budget_usd),
    }


def cmd_answer(args: argparse.Namespace) -> int:
    config = _load_config(Path(args.repo))
    try:
        Relay(config.run_dir).answer(args.id, args.text)
    except RelayError as exc:
        raise CliError(str(exc)) from exc
    print(f"answered {args.id}")
    return 0


def cmd_stop(args: argparse.Namespace, kill: Kill = os.kill) -> int:
    """Ask the runner to stop after its step; ``--now`` also signals it."""
    pid = _request_stop(Path(args.repo)) / state_mod.PID_FILE
    if args.stop is StopMode.NOW and pid.is_file():
        kill(int(pid.read_text()), signal.SIGTERM)
        print("stop requested; runner signalled")
        return 0
    print("stop requested; the team stops after the current step")
    return 0


def _request_stop(repo: Path) -> Path:
    run_dir = _load_config(repo).run_dir
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / state_mod.STOP_FILE).touch()
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
    (("--home",), {"default": str(Path.home()), "help": argparse.SUPPRESS}),
)
INIT_ARGS: tuple[Arg, ...] = (
    (("--detect",), {"action": "store_const", "dest": "func", "const": cmd_detect,
                     "help": "print the detected preset and exit"}),
    (("--preset",), {}),
    (("--delivery",), {"dest": "delivery_kind", "choices": sorted(sandbox.DELIVERY_KINDS)}),
    (("--url",), {"default": "", "help": "web delivery URL"}),
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
                      "default": StartMode.DELIVERY, "help": "run the onboarding sprint"}),
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
COMMANDS = (
    Command("init", "phase A onboarding (no API calls)", cmd_init, INIT_ARGS),
    Command("config", "validate .agile-team.toml and roles", cmd_config_check,
            ((("action",), {"choices": ["check"]}),)),
    Command("roles", "list role layers or scaffold instruction stubs", cmd_roles, ROLES_ARGS),
    Command("start", "run the team (blocks; run in the background)", cmd_start, START_ARGS),
    Command("status", "print run state as JSON", cmd_status),
    Command("answer", "answer a PO question", cmd_answer, ((("id",), {}), (("text",), {}))),
    Command("stop", "stop after the current step", cmd_stop, STOP_ARGS),
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
    except (CliError, keys.KeyNotFound) as exc:
        print(f"agile-team {args.command}: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
