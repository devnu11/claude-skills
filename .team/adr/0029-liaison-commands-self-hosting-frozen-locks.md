# ADR-0029: Liaison commands in the runner, self-hosting, frozen and locked uv

**Decision:** `agile-team tell` and `agile-team watch` commands replace private liaison shell scripts. A self-hosting pin script lets the team run on a pinned copy of the runner it is modifying. All documented uv commands freeze their locks at install time, and CI enforces locked resolution.

**Date:** 2026-10-11

## Context

The liaison today runs the team using two private shell scripts (`.team/run/liaison/team-resume.sh` and `watch-team.sh`) not in the repo. Any new user must write these scripts. Only one part is repo-specific: how to run the team on a pinned copy of the runner it is changing.

The runner also depends on uv's ability to re-resolve dependencies, but users install skills into their dotfiles once (`.claude/skills/`). If the runner later rewrites its lock file, every `dotfiles apply` in the user's shell stops and asks, blocking unattended jobs.

## Decision

### Liaison commands (s62 AC1, AC2)

| # | Rule | Consequence |
|---|---|---|
| T1 | **Tell queues a message.** `agile-team tell <file>` (or `-` for stdin) stores the text in `.team/run/liaison/messages/t<N>.md`, never on a command line. Next N is one more than existing numbers; N+1 on race. Draft is unlinked in a `finally`. Exits 0 on success, 1 on missing file or empty text. | Messages are never passed as arguments to runner commands, so a role's `pkill -f` cannot match them. |
| T2 | **Router delivers unread messages.** `Relay.unread(state.told)` lists messages the PO has not yet seen. At each router tick (after checkout check), unread messages become a `Pass([Trigger.HUMAN_MESSAGE], lines, stories)` joined with answers. Each message line is `The human sent you a message ({id}): read {path}.` with path repo-relative. | Message delivery happens through the normal inbox flow, so it wakes a waiting run without a stop and resume. Messages are kept until the PO turns, then delivered. `state.told` holds delivered ids to prevent re-delivery. |
| T3 | **Watch polls the run until something changes.** `agile-team watch [--timeout S]` reads the outbox and shown status every 2 seconds. Fires and exits with one JSON line when: (a) new outbox entries, (b) status or reason changed from quiet (`running` with no reason), or (c) timeout reached (heartbeat). Polls cost no tokens. | The liaison detects new messages, role transitions (halted, blocked, waiting, done), and status changes without shell loops or repeated API calls. `watch.json` remembers what was reported, so nothing is lost between runs. |
| T4 | **Status includes queued messages.** `status` JSON gains `queued_messages: [t1, t3, …]` listing unread ids. | The liaison and dashboards can show what messages are pending. |

### Resume from a dirty tree (s62 AC3)

| # | Rule | Consequence |
|---|---|---|
| R1 | **Salvage skips when checkout moved (s61).** `save_interrupted(cause)` sets `state.unsaved = cause` when it does not salvage (s9) because the checkout changed. `halt_run` then persists the cause. | A checkout halt leaves a dirty tree, but the cause is saved. |
| R2 | **Resume salvages unsaved edits.** `recover_cut(run_dir, git)` picks the first non-None of: status `interrupted` → `Cause.KILLED`, `state.unsaved` → that cause, else `None`. With a cause, it runs salvage (s9), clears `unsaved`, records checkout, and saves. | Resume works from a dirty tree without a wrapper script, whether the run was killed or halted for any reason. |
| R3 | **Messages tell what halted.** `agile-team start` prints `the last run <halted|was killed>; <role>'s edits are saved in <sha> (reverted)`. | The user knows the run state when they resume. |

### Self-hosting (s62 AC4)

| # | Rule | Consequence |
|---|---|---|
| P1 | **Pin script builds a dated copy.** `sh agile-team/runner/scripts/pin-runner.sh <commit>` extracts `agile-team/runner` from git at that commit into `.team/run/runner-pin/` (prefix stripped), and writes the full sha to `.team/run/runner-pin.commit`. Exits 2 on usage, 1 on any other error. | The team can run on a pinned runner it is not allowed to modify (the working copy). |
| P2 | **Pin validates the commit.** Checks: commit exists, is on the checked-out branch, has `agile-team/runner/pyproject.toml`, and the team is stopped. | Only accepted code can be pinned. Pinning only happens when the runner is not in use. |
| P3 | **Pinned runner uses its lock.** Unattended jobs run `uv run --frozen --project .team/run/runner-pin agile-team …`. The `--frozen` flag prevents re-resolution, using only the pinned `uv.lock`. | The job's runner never rewrites its lock, so it doesn't disrupt the user's dotfiles. |

### Frozen and locked (s62 AC5, AC7, AC8)

| # | Rule | Consequence |
|---|---|---|
| F1 | **Documented uv commands freeze.** Every `uv run --project …` in docs (SKILL.md, protocol.md, self-hosting.md, customer docs) and README has `--frozen`. A test enforces this. | Users installing the skill follow frozen commands, so their `uv.lock` never changes. |
| F2 | **CI enforces locked resolution.** `.github/workflows/agile-team.yml` and `unattended.yml` use `uv sync --locked --dev` and `uv run --locked …`. | A lock out of step with `pyproject.toml` fails CI and cannot be merged. |
| F3 | **Lock files are versioned.** `uv.lock` commits with `pyproject.toml` changes. Tests use the committed lock, never rewrite it. | Lock is canonical; no local re-resolution surprises. |

## Consequences

**Positive:**
- No private scripts needed. Users get `tell` and `watch` commands in the repo, same as any other skill.
- Liaison, devops, and any unattended job runner use standard `uv run --frozen` installs. Dotfiles stay stable.
- Self-hosting is explicit and auditable: `.team/run/runner-pin.commit` pins the exact code used.
- Watch is free: no model calls, no token cost. Liaison can poll in tight loops without worrying about budget.
- Dirty-tree recovery is automatic: both `kill` and checkout-halt cases are salvaged on `start --resume`.
- Message delivery is native: goes through the router, wakes waiting runs, works on any status.

**Tradeoffs:**
- Pin script runs `git archive` + `tar`, which are slower than a symlink, but correct (no shared state).
- `tell` and `watch` only work in a git repo with a runner home (`~/.claude/skills/…` or `.team/run/runner-pin`). Early test/dev requires an agile-team checkout.
- Watch polls every 2 seconds, so liaison response is capped at ~4 seconds on average. Acceptable for human-in-loop (s47 offers faster ← model call).

**Future:**
- As live meters (s44) ship, watch fires on health changes without polling the meter itself.
- Snapshots could embed `queued_messages` for dashboard display.
- An unattended framework could wrap `start --resume` and retry on policy.

## References

- Story: `.team/stories/s62.md`
- Design: `agile-team/docs/design/s62.md`
- Review: `.team/reviews/s62.md`
- Related: ADR-0009 (routing), ADR-0020 (unattended), ADR-0028 (checkout guard), s9 (salvage), s47 (answers wake router)
