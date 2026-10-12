# ADR-011: One OS seam; unit tests touch no OS (s71)

Status: accepted (2026-10-12)

## Context

The human's rule: any shell command is mocked in a unit test, in any
language. Git is a process, a pid is OS state, and `tmp_path` is a loophole:
the `repo` fixture runs real git inside it. About 80 unit-test files used
`tmp_path`, real git or real processes, and the runner's modules called `os`,
`subprocess`, `time` and `pathlib` directly. Some injected a clock or a
`popen` for tests, but most did not. The plan and the full call table are in
`.team/run/liaison/plans/unit-test-isolation.md`.

## Decision

1. **One seam, swapped at the import.** `agile_team/system.py` is the only
   code that touches the OS: files, processes, signals, ids, the clock, the
   network, the environment. It holds thin functions and no logic. Every
   other module does `from agile_team import system` and calls
   `system.read_text(...)`. `from agile_team.system import name` is banned,
   because it binds the real function before a test can swap it.
2. **No OS object is a parameter.** Fields that exist only to inject a clock,
   a sleep, a `popen`, a pid, `which`, `environ` or a browser are removed
   (`watch.Pace`, `live.Pace`, `Pulse.pid`, `Preparer.popen` / `sleep`,
   `Router.sleep`, the PO loop's `sleep`, `Preflight.which` / `environ`,
   `cli`'s `browse` and `kill`).
3. **The repo's own fake.** `tests/fake_system.py` holds an in-memory
   `FakeSystem`. It covers files (with missing, unreadable and full-disk
   failures, and a record of writes), a reply table for commands (so git is
   faked too), processes, signals, a clock, the network and the environment.
   An autouse fixture swaps every function in `system.__all__` for it. There
   is no new dependency, and the pattern carries over to other languages
   (module mocks in JS, package variables in Go, link seams in C).
4. **Enforced twice.** Ruff `TID251` bans the OS calls everywhere except
   `system.py` (and the test infrastructure and e2e tests). An audit hook in
   `tests/conftest.py` fails a unit test that reaches the real OS anyway.
   Its banned events are a table. Calls with no audit event (pids, waits,
   `signal`, `time.sleep`, `shutil.which`, `platform`, `os.stat`) are
   patched to raise while a unit test runs. The error says "inject it, or
   move the test to `tests/e2e/`".
5. **Real OS only in `tests/e2e/`.** A unit test proves the runner's
   decisions and the calls it makes. A test whose point is the real OS or
   real git moves to e2e.
6. **Three phases, each green.** P1 adds the seam, files and clock, and the
   fake and the guard (a `LEGACY` list holds files not yet migrated). P2
   covers processes, signals and the network. P3 covers the runtime and the
   CLI, deletes `LEGACY` and adds `TID251`.

## Options considered

- **pyfakefs.** It patches Python's own file calls. Rejected: it is Python
  only, a new dependency, and it fakes neither git nor processes.
- **Pass a filesystem or runner object into every constructor.** Rejected by
  the human: it adds parameters everywhere for the sake of tests.
- **Keep `tmp_path` as "not really the OS".** Rejected: it is where real git
  ran, it leaves files behind, and it cannot simulate a full disk or an
  unreadable file.
- **Only the audit hook, no static ban.** Rejected: the hook finds a direct
  call only when a test reaches it. Ruff finds it in review.
- **One big step.** Rejected: about 80 test files and 35 modules are too
  many for one tests step and one implement step, and the suite must stay
  green between steps.

## Consequences

- Unit tests are fast, leave nothing behind and can simulate failures. They
  run the same under xdist, because each worker has its own fake and
  monkeypatch undoes it after every test.
- Any new OS call needs a `system` function, a fake method (a unit test
  fails if the fake misses one) and an e2e test of the real function.
- An unscripted command in the fake succeeds with empty output. A test whose
  flow depends on git's answer must script it.
- `os.path.basename`, `signal.SIGTERM` and other pure names stay where they
  are. Only calls that touch the OS go through the seam.
- A test moved to e2e is removed by the unit-tester and recreated by the
  integration-tester in the same story's e2e step. For that stretch the
  suite runs without it.
- `unattended/runner` is not covered yet (a later story).
