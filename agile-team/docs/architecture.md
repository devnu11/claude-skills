# agile-team runner: architecture

The runner (`agile-team/runner/agile_team/`) is the program that runs the team.
The skill (`agile-team/SKILL.md`) only drives its CLI. This document covers the
components, their boundaries and how data flows between them. The last
sections are per-story designs. Each one is the contract a developer
implements against and a reviewer checks against.

## Components

| Module | Owns | Talks to |
|---|---|---|
| `cli.py` | subcommands (`COMMANDS` table), `status_report` | config, state, relay, ledger, `po_tools.run_po` |
| `po_tools.py` | the PO's MCP tools (`Tools`, `SCHEMAS`) and the PO loop | `Runtime`, `RunState`, events, relay |
| `dispatch.py` | `Runtime`: refusal, planning, running and settling one role step | gates, guard, sandbox, git, ledger, state, events |
| `gates.py` | `StoryState`, `Pipeline` (step machine), `dispatch_refusal`, command gates | roles (`Handoff`) |
| `state.py` | `RunState` and `state.json` load/save | gates (`StoryState`) |
| `events.py` | `events.jsonl` append-only log (`EventKind`) | none |
| `relay.py` | outbox/inbox with the liaison | none |
| `ledger.py` | per-step cost, budget checkpoints | none |
| `guard.py`, `sandbox.py`, `keys.py` | write scopes, quarantine, Customer Proxy sandbox, key hygiene | git |
| `roles.py`, `config.py` | role layering, handoff parsing, `.agile-team.toml` | none |

```mermaid
flowchart LR
  liaison[[liaison / human]] -- answer, stop, status --> cli
  cli -- start --> po[po_tools.PoRun]
  po -- MCP tool calls --> tools[po_tools.Tools]
  tools -- run_role --> rt[dispatch.Runtime]
  tools -- open_story / start_sprint --> st[(state.RunState)]
  rt -- refusal --> gates[gates.dispatch_refusal]
  rt -- gate / advance --> pipe[gates.Pipeline]
  rt --> st
  rt --> ev[(events.jsonl)]
  tools --> ev
  tools --> relay[(outbox / inbox)]
  relay --> liaison
```

### One role step

1. The PO calls `run_role(role, brief, story)`.
2. `Runtime.refusal` runs `_run_refusal`, `_role_refusal` and `_story_refusal`
   in order. The first reason wins and goes back to the PO as
   `{"status": "refused", "reason": …}`. No side effects happen before this point.
3. `plan` → `_execute` (a fresh `query()`) → `settle`: cost, handoff, quarantine
   and commit, gate, save.

Rule: refusals are pure checks. Any state change happens only after every
check has passed. This holds for every PO tool too.

## Requirements (interim)

Structured `REQ-NNN.md` files arrive with s1. Until then, each story design
below lists its rules (`B1`, `B2`, …). When s1 lands, these rules move into
REQ files. Do not add a free-form `requirements.md`: s1 treats one as a
legacy problem.

---

## s3: Backlog and sprint membership

Developer: **developer-cli** (runner Python: `gates.py`, `state.py`,
`po_tools.py`, plus the built-in `roles/product-owner.md`). The Architect has
already updated `reference/protocol.md`, `SKILL.md` and the README row
in this design step.

### Rules

| # | Rule |
|---|---|
| B1 | `StoryState.sprint: int \| None`. `None` means the story is in the backlog. A number is the sprint the story is committed to. |
| B2 | `open_story` puts a new story in the backlog (`sprint = None`). |
| B3 | `start_sprint(goal, stories)` is the **only** way into a sprint. Nothing else sets `sprint` to a number. |
| B4 | `start_sprint` replaces the sprint's scope. It opens sprint `N+1`. Every listed story that is not done gets `sprint = N+1`. Every other story that is not done goes back to the backlog (`None`). A done story never changes: it keeps the sprint it finished in (or `None` for legacy stories). |
| B5 | A story is in at most one sprint (a single int). Carrying an unfinished story over means listing it again. Adding a story mid-sprint means a new `start_sprint` that lists the old stories plus the new one. That starts sprint `N+1` and queues the Manager again. This is intended: sprint scope changes get a Manager review. |
| B6 | `start_sprint` refuses, with no side effects (sprint number, status, `manager_due`, state file and events all unchanged), when `stories` is missing or empty, or when any id is not an opened story. |
| B7 | A story-bound step on a backlog story is refused with exactly `story sN is in the backlog; add it to a sprint`. Ungated roles (`manager`, `scribe`) and story-less steps are unaffected. |
| B8 | `state.json` written before s3 has no `sprint` key on stories. Those stories load into the backlog (`None`). Nothing else changes: `step`, `rounds`, `status` and `commit` are kept. |
| B9 | `story_status` and `agile-team status` show each story's `sprint` (`null` = backlog) and the current sprint number. |

### Membership lifecycle

```mermaid
stateDiagram-v2
  [*] --> backlog: open_story
  backlog --> sprintN: start_sprint lists it
  sprintN --> sprintN1: start_sprint lists it again (carry-over)
  sprintN --> backlog: start_sprint omits it (not done)
  sprintN --> done: last pipeline step passes (keeps N)
  done --> done: start_sprint never moves it
```

### Legacy state and self-hosting (B8)

Loading needs **no migration code**. `StoryState.sprint` has the default
`None` and comes last among the fields, so `StoryState(**data)` in
`state._story` fills it in when the key is missing. The rule needs no special
cases:

- A story already past design (say, at `implement` with a `commit`) keeps its
  step, rounds and commit. Once it is back in a sprint, it carries on where it
  was.
- The current sprint's stories are **not** inferred. The old state has no
  record of which stories the sprint held, and guessing "all of them" would
  silently commit the whole backlog.
- A story that is `needs_manager` or `blocked` and sits in the backlog still
  gets its status refusal first. The Manager can still rule on it, because
  `manager` is ungated.

What happens on the first `start --resume` after s3 (this repo's own run
included): the PO's next `run_role` on a story returns the backlog refusal.
The PO calls `start_sprint(goal, [unfinished ids])`, which opens sprint
`N+1` and queues the Manager. The PO runs the Manager, and work continues at
each story's existing step. The cost is one Manager step, and the refusal text
tells the PO what to do. A runner process that is already running keeps its
loaded code until it restarts.

### Changes by module

#### `gates.py`

- `StoryState`: add `sprint: int | None = None` as the **last** field, after
  `delivery`. Positional construction (`StoryState(id, title, step)`) and
  legacy loading depend on this.
- New `_backlog_refusal(story: StoryState) -> str | None`:
  returns `f"story {story.id} is in the backlog; add it to a sprint"` when
  `story.sprint is None`, else `None`.
- `dispatch_refusal` checks in this order: ungated role → no story → status
  → **backlog** → step:

  ```python
  return _status_refusal(story) or _backlog_refusal(story) or _step_refusal(role, story)
  ```

  Status comes first so that a done, blocked or capped story gives the more
  useful reason (a legacy done story says "is done", not "in the backlog").
  `dispatch.Runtime._story_refusal` already ends with `dispatch_refusal`, so
  it needs no change. B7 is met through it.

#### `state.py`

- `RunState.unknown_stories(self, ids: list[str]) -> list[str]`: the ids not
  in `self.stories`, in the order given.
- `RunState.begin_sprint(self, ids: list[str]) -> None`: increments
  `self.sprint`, then applies B4 to each story whose status is not `DONE`
  (`self.sprint` if its id is in `ids`, else `None`). It must stay at 8 lines
  or fewer.
- `from_json` / `_story`: unchanged (B8 holds through the dataclass default).

#### `po_tools.py`

`Tools.start_sprint` becomes refusal-check-then-act. Suggested split, each
function at most 8 lines and 2 parameters:

| Function | Job |
|---|---|
| `start_sprint(self, args)` | `ids = list(dict.fromkeys(args.get("stories") or []))` (dedupe, keep order); refuse via `_sprint_refusal`; else `_begin_sprint`; return the result. |
| `_sprint_refusal(self, ids) -> str \| None` | Applies B6 using the reason strings below. |
| `_begin_sprint(self, goal, ids) -> None` | `state.begin_sprint(ids)`; `status = RUNNING`; append the `manager_due` entry; `save()`; emit `SPRINT_START`. |

Successful result: `{"sprint": N, "stories": ids, "next": "run the manager"}`.

`manager_due` entry: `f"sprint {N} start: {goal} ({', '.join(ids)})"`. The
Manager uses it to check that the scope is realistic.

`SPRINT_START` event data: `{"sprint": N, "goal": goal, "stories": ids}`. This
matches `dashboard/fixtures/snapshot.json`.

`story_status` adds a top-level `"sprint": state.sprint`. The per-story
`sprint` already comes through `vars(s)`.

`SCHEMAS` entries:

```python
"open_story": (
    "Register a story; it starts in the backlog until start_sprint lists it.",
    {"id": str, "title": str, "delivery": str},
),
"start_sprint": (
    "Begin the next sprint with exactly the listed story ids; unfinished stories "
    "not listed go back to the backlog. The manager must run next.",
    {"goal": str, "stories": list},
),
```

#### Refusal strings (tests may assert them exactly)

| When | Reason |
|---|---|
| `stories` missing or empty | `no stories listed; pass the story ids this sprint commits to` |
| unknown ids | `unknown stories: s7, s9; open them with open_story first` (all unknown ids, comma-separated, in the order given) |
| step on a backlog story | `story s3 is in the backlog; add it to a sprint` |

#### `cli.py`

`status_report` already includes `"sprint"` (the current sprint) and
`asdict(story)`, so each story gains `sprint` automatically. No code change is
needed. Tests must cover it (B9).

#### `roles/product-owner.md` (built-in, developer-cli edits it)

Replace step 3 of "How you work" and add a "Backlog and sprints" section that
says:

- `open_story` puts a story in the backlog. Only stories in the current
  sprint can move. `run_role` refuses a backlog story with "story sN is in
  the backlog; add it to a sprint".
- `start_sprint(goal, stories=[…])` lists **every** story the sprint commits
  to, including unfinished ones carried over. Unfinished stories you leave
  out go back to the backlog. Then run the `manager`.
- To add a story mid-sprint, start a new sprint that lists the current
  stories plus the new one (the Manager reviews the change).
- After a resume, if `story_status` shows unfinished stories with
  `sprint: null`, start a sprint with the ones to continue.
- Sprint cadence: "the sprint's stories" means the stories whose `sprint`
  equals the current sprint.

### Test checklist (for the Unit Tester)

Existing helpers that build stories for steps must now put them in a sprint
(`sprint=1`): `tests/test_dispatch.py::open_story` and
`tests/test_gates.py::story`. `test_po_tools.py::test_start_sprint_requires_manager`
must open a story and pass `stories`. These are contract changes, not
weakened tests.

1. B1/B2: `open_story` stores `sprint is None`; `story_status` shows
   `"sprint": null` for it.
2. B8: `RunState.from_json` of a story dict without `sprint` gives `None`; a
   round trip keeps `sprint=2`.
3. B6: an empty list, a missing key and unknown ids are each refused. After
   each refusal, `state.sprint`, `status`, `manager_due` and the events log are
   unchanged. The unknown-ids reason names every unknown id.
4. B3/B4: given s1 in sprint 1 (unfinished), s2 done in sprint 1, s3 in the
   backlog, then `start_sprint(stories=["s3"])` → s3 = 2, s1 = `None`, s2 = 1.
   Listing a done story leaves its sprint unchanged.
5. B5: listing s1 again carries it to sprint 2. Duplicate ids appear once
   in the event and the result.
6. Event, `manager_due` entry and result have the shapes given above.
7. B7: `run_role` on a backlog story at its correct step is refused with the
   exact string. `manager` and `scribe` on a backlog story are not refused by
   it. A story-less architect step is not refused.
8. Order: a done backlog story says "is done"; a needs-manager backlog story
   says "round cap".
9. B9: `story_status` has the top-level `sprint`; `cli.status_report` stories
   carry `sprint`.

### Out of scope

Removing a single story from a sprint without starting a new one, and story
priority or ordering within the backlog, are both out of scope. So is
dashboard rendering, which is s4/s5: the snapshot fixture already carries
`stories[].sprint` and the `sprint-start` event's `stories`.
