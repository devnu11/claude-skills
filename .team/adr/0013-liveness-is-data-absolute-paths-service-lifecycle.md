# ADR-0013: Liveness is data; absolute paths; service lifecycle and gate trial

**Date:** 2026-10-10 (s26 done)  
**Status:** Accepted  
**Relates to:** ADR-0009 (routing in code), ADR-0008 (team presents product), s13 (presentation layout)

## Context

**Sprint 8, events e451–e458:** The integration-tester passed a presentation for `s4`, the e2e gate said "presentation ready", and the customer-proxy bounced it: nothing listened on 127.0.0.1:8799.

Root cause analysis found two coupled failures:

1. **Relative path bug (L1):** The runner's `cli` did not resolve `--repo` to an absolute path. When `--repo .team/run/customer/dashboard/presentation/workspace` was passed to `uv run --directory agile-team/runner …`, the cwd changed to `agile-team/runner` first, so the relative path resolved to the wrong place. The sandbox held `.agile-team.toml` correctly, but the runner's `Popen` tried to read from `agile-team/runner/.team/run/customer/…`.

2. **Gate liveness (L10):** The "presentation ready" gate checked that PRESENTATION.md and workspace/ existed, not that the service was actually running. With no early warning, the Proxy spent a query starting a delivery that the integration-tester never tested.

After the root cause, the team decided not to rely on the integration-tester to test service startup in isolation. Instead, the runner itself runs a **trial** from the presentation (the same sandbox and prepare command the Proxy gets), and the gate gates on liveness. This makes the gate trustworthy: a pass means something answered.

## Decision

### 1. Absolute paths (L1)

`cli.repo_of(args)` returns `Path(args.repo).resolve()`. Every use of `args.repo` throughout `cli` calls `repo_of` once. `Prepared.expand` also calls `.resolve()` on `{repo}` and `{sandbox}` placeholders, so prepare commands never depend on cwd.

**Consequence:** Paths in the runner are absolute; sandbox roots work from any cwd.

### 2. Address and port placeholders (L2)

`Delivery` gains `probe: str = ""` (the path joined to `url` that the trial probes). `Prepared.address()` extracts `(host, port)` from the delivery's `url` using `urlsplit` and scheme defaults (`http` → 80, `https` → 443, no port → `""`). `Prepared.expand` fills `{repo}`, `{sandbox}`, `{host}`, and `{port}` in the prepare command.

**Consequence:** The delivery's port lives in one place (`url`); the prepare command sees it via placeholder.

### 3. Liveness is data (L3)

`presentation.Check(StrEnum)` has `FILES` and `SERVICE`. `presentation.Recipe` pairs a need with a check type. `presentation.PRESENTATIONS` maps delivery kind to recipe; only `"web"` uses `Check.SERVICE`. Everything else uses `Check.FILES`.

The runner never branches on a kind or delivery name; `Checks.presented` uses the recipe's check type (code, not configuration).

**Consequence:** Adding a service delivery requires one data row, not code changes.

### 4. Service startup and probe (L4, L5)

`Preparer._serve(prepared, prepare)` starts the service when `prepare` is set, then always runs `_await_answer`. `_start` does `stop_stale`, then `_refuse_busy`, then `Popen` with `start_new_session=True`, stdout/stderr to log, write the pid file. `_await_answer` probes up to 120 times with 0.25s between attempts.

`http_answers(url)` makes an HTTP GET with a 2s timeout. It returns `True` only for status 200 and, if the response is JSON, valid JSON. Any `OSError` or `ValueError` is "no answer".

**Consequence:** Services are started reliably with output capture; probes are fast and wait bounded.

### 5. Stale service cleanup (L7)

Before laying out, `stop_stale(root)` reads the pid file. If the pid is a process group leader (`os.getpgid(pid) == pid`), it sends SIGTERM to the group, waits 10 seconds polling, then sends SIGKILL. It always deletes the pid file. A dead pid or missing file is silent.

**Consequence:** Services from earlier steps or killed runners are never reused; the port is free.

### 6. Service teardown (L9)

`Prepared.stop()` ends the process group (as before) and deletes the pid file; it is idempotent. Every path out of the Proxy step (pass, fail, hold, `CancelledError`) calls it. An exception while planning after `prepare` is caught and calls `stop()` before re-raising.

**Consequence:** Zombie services are impossible; cleanup is guaranteed.

### 7. Presentation ready gate with trial (L10)

The e2e gate checks files first (as today). For `Check.SERVICE` recipes, it then runs a `Trial`: `prepare` with the same sandbox and order the Proxy will get, probes it, then stops it.

- `NotUp` → `Outcome(BOUNCE, reason)` at e2e (round +1)
- `PortBusy` → `Outcome(HOLD, reason)` at e2e (round unchanged, hand-over to PO)
- Pass → `Outcome(PASS, "presentation ready; <url> answered")`

**Consequence:** The gate detects a dead service and stops early; a pass guarantees delivery readiness.

### 8. Proxy return on not-up (L11)

If the Proxy's own `prepare` raises `NotUp`, the Proxy does not run and nothing is billed. With an `e2e` step, the story returns to e2e with no round (`Verdict.RETURN`, the s13 return path). Without e2e it is refused (as before).

**Consequence:** A service failure during Proxy setup is cheap; the integration-tester gets the exact error in the reason.

### 9. Port conflict holds (L12)

A `PortBusy` from the gate creates a `Trigger.GATE_HOLD` hand-over: `"<story>: <role>'s gate is on hold: delivery '<name>' cannot start: <host>:<port> is already in use…; fix it, then continue_story"`.

**Consequence:** The PO can diagnose and fix port conflicts without retrying the gate.

### 10. Self-contained presentations (L13, role rule)

The integration-tester's presentation holds no repo paths, only copies of what the customer needs (ADR, protocol section, files to try) and captured command output (test and ruff results, with command and exit code). The Proxy's sandbox can't read repo paths, so this rule ensures the presentation works in isolation.

**Consequence:** Presentations are portable; Proxy doesn't need repo access for reading.

## Consistency rules

- **Precedence (L10):** Files are checked before liveness; a liveness pass stops the trial's service.
- **Placeholders (L1, L2):** Every `Path(args.repo)` calls `repo_of`; every `{repo}`, `{sandbox}`, `{host}`, `{port}` uses `.resolve()` or `urljoin`/`urlsplit`.
- **Stale cleanup (L7):** Before every new start. Deletes pid file always (even on `ProcessLookupError`).
- **Teardown (L9):** `finally` block in `Runtime.plan` and `_await_answer`'s exception sequence ensure `stop()` is called.
- **Trial vs. Proxy (L4, L10, L11):** Trial has its own `prepare_fn` (injectable for tests); Proxy uses the same flow. Trial stops after probing; Proxy stops in `finally`.

## Tradeoffs

- **Trial + Proxy startup cost:** Starting the service twice adds a few seconds per Proxy story. Reusing the trial's service would break L7 (can't tell stale from current).
- **Log tail on stop:** The reason's log tail is read before `stop()`, so output on SIGTERM is not included. Intended: the reason says why it was not up, not how the runner stopped it.
- **Trust the self-contained rule:** The gate doesn't verify; the Proxy judges whether the presentation is truly self-contained (no repo paths).
- **Readiness = 200:** A delivery whose health needs more than one URL is a new design, not in this story.

## References

- Story: `.team/stories/s26.md`
- Design: `agile-team/docs/design/s26.md` (rules L1–L13, modules, test checklist, reason strings)
- Review: `.team/reviews/s26.md` (round 0 and round 1, all defects fixed)
- Related: ADR-0008 (presentation layout), ADR-0009 (routing), s13 (presentation design)
