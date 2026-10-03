"""``agile-team`` command line: init | config check | start | status | answer | stop.

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
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path
from typing import Any

from . import config as config_mod
from . import gates, keys, onboard, preflight, sandbox
from . import state as state_mod
from .dispatch import QueryFn, Runtime, shell_runner
from .git_ops import Git
from .ledger import Ledger, budget_status
from .relay import Relay, RelayError
from .roles import RoleBook, RoleError, expand_globs

LEDGER = "ledger.jsonl"


class CliError(Exception):
    """A user-facing failure; the message is printed as is."""


def default_query() -> QueryFn:
    from claude_agent_sdk import query

    return query


# ----- init --------------------------------------------------------------


def cmd_init(args: argparse.Namespace) -> int:
    repo, presets = Path(args.repo), onboard.load_presets()
    if args.detect:
        return _print_detection(repo, presets)
    if not Git(repo).is_clean():
        raise CliError("working tree is dirty; commit or stash first")
    if not args.preset or not args.delivery:
        raise CliError("--preset and --delivery are required (see --detect)")
    answers = onboard.Answers(
        preset=args.preset,
        delivery_kind=args.delivery,
        docs_dir=args.docs_dir,
        artifacts=args.artifacts,
        key_file=args.key_file,
        budget_usd=args.budget,
        cadence=args.cadence,
        url=args.url,
    )
    try:
        sha = onboard.onboard(repo, answers, reconfigure=args.reconfigure)
    except (FileExistsError, ValueError) as exc:
        raise CliError(str(exc)) from exc
    print(f"onboarded: {sha}" if sha else "nothing to change")
    return 0


def _print_detection(repo: Path, presets: dict[str, Any]) -> int:
    name = onboard.detect(repo, presets)
    if name is None:
        print(json.dumps({"preset": None, "known": sorted(presets)}))
        return 0
    preset = presets[name]
    print(
        json.dumps(
            {
                "preset": name,
                "delivery_kind": onboard.suggest_kind(repo, preset),
                "commands": preset["commands"],
                "globs": preset["globs"],
            },
            indent=2,
        )
    )
    return 0


# ----- config check --------------------------------------------------------


def cmd_config_check(args: argparse.Namespace) -> int:
    config = _load_config(Path(args.repo))
    problems = check_config(config)
    for problem in problems:
        print(f"problem: {problem}")
    print("config ok" if not problems else f"{len(problems)} problem(s)")
    return 1 if problems else 0


def check_config(config: config_mod.Config) -> list[str]:
    """Static config problems plus every role's resolution and glob expansion."""
    book = RoleBook.for_repo(config.repo, config.roles)
    problems = config_mod.validate(config, book.names(), set(sandbox.DELIVERY_KINDS))
    values = config.placeholders()
    for name in sorted(book.names()):
        try:
            role = book.resolve(name)
            expand_globs(role.write, values)
            expand_globs(role.read, values)
        except RoleError as exc:
            problems.append(f"role {name}: {exc}")
    return problems


def _load_config(repo: Path) -> config_mod.Config:
    try:
        return config_mod.load(repo)
    except config_mod.ConfigError as exc:
        raise CliError(str(exc)) from exc


# ----- start ---------------------------------------------------------------


def make_runtime(repo: Path, home: Path, query_fn: QueryFn) -> Runtime:
    """Wire config, roles, git, ledger, relay, state and the API key together."""
    config = _load_config(repo)
    source = keys.resolve(repo, config.team.key_file, home)
    baseline = gates.load_baseline(repo).get("coverage")
    checks = gates.Checks(
        config.toolchain.commands, config.gates.coverage, shell_runner(repo), baseline
    )
    return Runtime(
        config=config,
        book=RoleBook.for_repo(repo, config.roles),
        git=Git(repo),
        ledger=Ledger(config.run_dir / LEDGER),
        relay=Relay(config.run_dir),
        state=state_mod.load(config.run_dir),
        env=keys.child_env(keys.read_key(source.path)),
        secrets=keys.secret_paths(repo, config.team.key_file, home),
        query_fn=query_fn,
        checks=checks,
    )


def cmd_start(args: argparse.Namespace, query_fn: QueryFn | None = None) -> int:
    repo, home = Path(args.repo), Path(args.home)
    config = _load_config(repo)
    failures = preflight.run_all(config, Git(repo), home) + check_config(config)
    if failures:
        raise CliError("preflight failed:\n  " + "\n  ".join(failures))
    runtime = make_runtime(repo, home, query_fn or default_query())
    if not args.resume and not args.task:
        raise CliError("--task is required unless --resume")
    runtime.state.cadence = args.cadence or config.team.cadence
    return _run(runtime, args)


def _run(runtime: Runtime, args: argparse.Namespace) -> int:
    from .po_tools import run_po

    run_dir = runtime.config.run_dir
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / state_mod.STOP_FILE).unlink(missing_ok=True)
    (run_dir / state_mod.PID_FILE).write_text(str(os.getpid()))
    try:
        result = asyncio.run(run_po(runtime, args.task or "", args.onboard, args.resume))
    finally:
        (run_dir / state_mod.PID_FILE).unlink(missing_ok=True)
    print(result.text)
    return 0


# ----- status / answer / stop ----------------------------------------------


def cmd_status(args: argparse.Namespace) -> int:
    config = _load_config(Path(args.repo))
    st = state_mod.load(config.run_dir)
    relay = Relay(config.run_dir)
    print(
        json.dumps(
            {
                "status": st.status,
                "cadence": st.cadence,
                "sprint": st.sprint,
                "running": (config.run_dir / state_mod.PID_FILE).exists(),
                "stories": {k: asdict(v) for k, v in st.stories.items()},
                "manager_due": st.manager_due,
                "open_questions": [asdict(m) for m in relay.open_questions()],
                "budget": budget_status(Ledger(config.run_dir / LEDGER), config.team.budget_usd),
            },
            indent=2,
        )
    )
    return 0


def cmd_answer(args: argparse.Namespace) -> int:
    config = _load_config(Path(args.repo))
    try:
        Relay(config.run_dir).answer(args.id, args.text)
    except RelayError as exc:
        raise CliError(str(exc)) from exc
    print(f"answered {args.id}")
    return 0


def cmd_stop(args: argparse.Namespace, kill: Callable[[int, int], None] = os.kill) -> int:
    config = _load_config(Path(args.repo))
    run_dir = config.run_dir
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / state_mod.STOP_FILE).touch()
    pid_file = run_dir / state_mod.PID_FILE
    if args.now and pid_file.is_file():
        kill(int(pid_file.read_text()), signal.SIGTERM)
        print("stop requested; runner signalled")
    else:
        print("stop requested; the team stops after the current step")
    return 0


# ----- parser ----------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agile-team", description=__doc__)
    parser.add_argument("--repo", default=".", help="target repo root (default: cwd)")
    parser.add_argument("--home", default=str(Path.home()), help=argparse.SUPPRESS)
    sub = parser.add_subparsers(dest="command", required=True)
    _add_init(sub)
    check = sub.add_parser("config", help="validate .agile-team.toml and roles")
    check.add_argument("action", choices=["check"])
    check.set_defaults(func=cmd_config_check)
    _add_start(sub)
    sub.add_parser("status", help="print run state as JSON").set_defaults(func=cmd_status)
    answer = sub.add_parser("answer", help="answer a PO question")
    answer.add_argument("id")
    answer.add_argument("text")
    answer.set_defaults(func=cmd_answer)
    stop = sub.add_parser("stop", help="stop after the current step")
    stop.add_argument("--now", action="store_true", help="also SIGTERM the runner")
    stop.set_defaults(func=cmd_stop)
    return parser


def _add_init(sub: Any) -> None:
    init = sub.add_parser("init", help="phase A onboarding (no API calls)")
    init.add_argument("--detect", action="store_true", help="print the detected preset and exit")
    init.add_argument("--preset")
    init.add_argument("--delivery", choices=sorted(sandbox.DELIVERY_KINDS))
    init.add_argument("--url", default="", help="web delivery URL")
    init.add_argument("--docs-dir", default="docs")
    init.add_argument("--artifacts", choices=config_mod.ARTIFACT_POLICIES, default="committed")
    init.add_argument("--key-file", default=config_mod.DEFAULT_KEY_FILE)
    init.add_argument("--budget", type=float, default=20.0)
    init.add_argument("--cadence", choices=config_mod.CADENCES, default="sprint")
    init.add_argument("--reconfigure", action="store_true")
    init.set_defaults(func=cmd_init)


def _add_start(sub: Any) -> None:
    start = sub.add_parser("start", help="run the team (blocks; run in the background)")
    start.add_argument("--task", help="the task for the Product Owner")
    start.add_argument("--cadence", choices=config_mod.CADENCES)
    start.add_argument("--onboard", action="store_true", help="run the onboarding sprint")
    start.add_argument("--resume", action="store_true", help="continue the previous run")
    start.set_defaults(func=cmd_start)


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
