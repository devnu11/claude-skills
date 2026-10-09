# agile-team runner: implementation guidelines

These rules apply to every change in `agile-team/runner/`. The repo charter
(`.team/CLAUDE.md`) is the source of truth; this file adds how to apply it.

## Shape of code

- Functions do one job, ideally in 8 lines or fewer, with at most 2
  parameters besides `self` (constructors excepted). Split a function before
  it grows past that.
- No boolean parameters or flags. Use a `StrEnum` (see `StartMode`,
  `StopMode`, `Verdict`).
- Prefer tables to branching: `cli.COMMANDS`, `gates.STEP_ROLES`,
  `po_tools.SCHEMAS`, `_status_refusal`'s reasons dict. A new case is a new
  row.
- Brief docstrings on public functions and classes. Comments inside a
  function only for pitfalls that are not obvious.

## Refusals and side effects

- A PO tool or a step check that can refuse returns
  `refused(reason)` → `{"status": "refused", "reason": …}`.
- Check every refusal **before** changing any state. A refused call leaves
  `state.json`, `events.jsonl` and the relay untouched.
- A reason says what is wrong **and** what to do next ("…; add it to a
  sprint", "…; open it with open_story"). The PO acts on the reason text.
- Chain refusal checks with `or` (or `next(...)` over a tuple). The first
  reason wins, so order checks from the most specific to the most general.

## State compatibility

- `state.json` from an older runner must still load. Add new dataclass
  fields **last**, with a default that is safe for old data. Document what
  the default means in `reference/protocol.md`.
- Do not write migration code when a default does the job.

## Process enforced in code

A rule the prompts describe (gates, formats, state transitions, sprint
membership) is also checked by the runner. When you add or change such a
rule, update in the same story:

- the role prompt that states it (`runner/agile_team/roles/*.md`);
- `agile-team/reference/protocol.md`;
- `agile-team/SKILL.md` and the README row when the liaison or human sees
  the change.

## Routing (s19)

- The router decides who runs next, and its decisions are data:
  `router.PICKERS` (what kind of work comes first), `router.ROLE_HINTS`
  (which role takes a story step), `router.BRIEF_PATHS` (what a standard
  brief points at), and `handover.HANDOVERS` (when the PO is needed). A new
  reason to call the PO is a new `HANDOVERS` row, not an `if` in the router.
- Briefs point at files; they never paste a file's contents. The one
  exception is the gate's reason on a bounce.
- A new per-story design goes in `docs/design/<story>.md`, with one line in
  `architecture.md`'s story index.

## Errors and halts

- Do not catch broad exceptions inside the runner just to print them. An
  unexpected error goes up to `cli._run` (or, inside a role step, to
  `Runtime._step_failed`), which logs it to `crash.log` and records a halt.
- Every halt goes through `Runtime.halt_run`. A new kind of stop is a new row
  in `halt.HALTS`, and a new limit phrasing is a new row in
  `halt.LIMIT_PATTERNS` (see ADR-001).

## Events and the dashboard contract

- `dashboard/fixtures/snapshot.json` is the contract for what the dashboard
  renders. Event `data` shapes must match it.
- New event kinds go in `events.EventKind`; never reuse a kind for a
  different shape.
- The dashboard is read-only. `dashboard/snapshot.py` reads only the files
  `watched_files` lists (plus the role book). It never writes, never runs git
  and never reads key files. A new data source is a new entry there and in
  the "Dashboard" section of `reference/protocol.md`.
- Read JSONL that another process is appending to through
  `snapshot.read_jsonl`, which skips torn and blank lines. `Ledger.entries`,
  `Relay` and `EventLog` raise on a torn line, so they suit the runner,
  which writes those files, but not readers running alongside it.
- The server serves fixed routes (`server.ROUTES`) and never builds a file
  path from a request. A new route is a new row there, documented in the
  protocol.
- `index.html` is one vanilla-JS file with no build step. Its only outside
  URL is the pinned `mermaid@11.4.1` (tested). Colours come from the CSS
  tokens in `:root`. Every panel survives a missing or empty snapshot
  section (it shows an `.empty` line).

## Quality bar

- Coverage stays at 95% or more (currently 100%); `ruff check` and
  `ruff format --check` are clean.
- Run tools from the repo root:
  `uv run --directory agile-team/runner pytest --cov`.
- Tests never touch the real home directory. The suite points
  `AGILE_TEAM_HOME` at a scratch dir.
- No new runtime dependency without an ADR. The dashboard uses only the stdlib.
