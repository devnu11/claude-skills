# agile-team protocol reference

Loaded on demand by the liaison. Everything here is implemented in
`runner/agile_team/`.

## CLI

Run from the target repo root, or pass `--repo PATH`. The installed skill
runs as `uv run --frozen --quiet --project ~/.claude/skills/agile-team/runner agile-team`.
`--frozen` uses the skill's tested `uv.lock` and never rewrites it. When the
team works on this runner itself, it runs on a pinned copy instead (see
`self-hosting.md`).

| Command | What it does |
|---|---|
| `init --detect` | Print the detected stack preset, commands, globs and suggested delivery kind as JSON. No writes. |
| `init --preset P --delivery K [--url U] [--docs-dir D] [--artifacts committed\|ignored] [--key-file F] [--budget USD] [--cadence sprint\|until-blocker]` | Phase A: write `.agile-team.toml`, `.gitignore` lines, `.team/CLAUDE.md`, a stub per role in `.team/roles/`; commit `chore(team): onboard agile team`. |
| `init … --reconfigure` | Re-run phase A; keeps every value already in the config and never overwrites the charter. |
| `config check` | Validate config, every role's resolution and glob placeholders. Exit 1 on problems. |
| `roles list` | JSON: each role's layers (built-in, global, repo: `replace`, `addendum` or `stub`) and its resolved model, provider, effort and write scope. |
| `roles scaffold [--global]` | Write a commented stub for `_shared` and every enabled role that has no file yet, in `.team/roles/` (default) or the global dir. Never overwrites. |
| `start --task T [--cadence C] [--onboard] [--resume]` | Preflight, then run the team in the foreground (the liaison backgrounds it): the runner drives the pipeline and calls the PO for judgement (see "Routing"). With `--resume`, `--task` is optional and reaches the PO as "New from the human". Exit codes: see "Run status and stops". |
| `status` | JSON: run `status` and `status_reason` (why the runner stopped, what a waiting run waits on, or `null`), current `sprint`, stories with their pipeline step, `sprint` (`null` = backlog) and routing fields (`hold`, `developer`, `previous`; see "Routing"), open questions, spend, the pending sprint `boundary` (or `null`), `upstream` (the review stack; see "Sprint boundaries"), `checkout` (the branch and HEAD the runner expects, or `null`; see "Checkout guard") and `queued_messages` (ids of `tell` messages the PO has not been handed yet, e.g. `["t3"]`). |
| `answer ID TEXT` | Answer PO question `ID`. |
| `tell SOURCE` | Queue a message for the PO. `SOURCE` is a file, or `-` for stdin; the text never goes on a command line. Stored as `.team/run/liaison/messages/t<N>.md`; prints `queued t<N> for the PO: <path>`. Works in any run state (running, waiting, halted, stopped). Exit 1 on an empty text (`the message is empty`) or an unreadable file. See "Liaison messages". |
| `watch [--timeout S]` | Block, polling the run files every 2 s (no tokens), until something needs the liaison. Then print one JSON line and exit 0. See "Watch". |
| `stop [--now]` | Stop after the current role step; `--now` also SIGTERMs the runner, which stops cleanly with status `stopped` (exit 143). |
| `accept-checkout` | Keep the current branch and HEAD as the team's after a `checkout-changed` halt (see "Checkout guard"). Refused (exit 1) while a runner is alive, on a detached HEAD, or with a git operation in progress. |
| `dashboard [--host H] [--port 8765] [--no-open]` | Serve the read-only live dashboard until interrupted (the liaison backgrounds it). Prints `dashboard: http://localhost:<port>/` once it is listening and, when it listens on all interfaces, a second line `from other machines: http://<host>.local:<port>/` (the hostname as is if it has a dot). Opens the localhost URL in a browser unless `--no-open`. Default host: `0.0.0.0` (all interfaces), `127.0.0.1` on Windows (no second line). `--port 0` picks a free port and prints the real one. Exit 1 if the address can't be bound. See "Dashboard". |

`init` (without `--detect`) in a directory that is not a git work tree prints
`agile-team init: not a git repository: <repo>; run git init first` and exits 1.

Preflight refuses to start when: the tree is dirty (except on `--resume`
after a kill or a checkout halt that left a step's edits, see "Interrupted
steps"); with `auth = "api-key"`,
no key file exists, the repo key file is not gitignored, or a key file is not
mode 600; with `auth = "login"`, `ANTHROPIC_API_KEY` is set in the environment; a toolchain
command's executable is missing; `config check` fails.

## Relay files (`.team/run/`, always gitignored)

`outbox.jsonl`, one JSON object per line, written by the PO:

```json
{"id": "m3", "kind": "question", "text": "…", "stories": ["s2"], "at": 1730000000.0}
```

`kind` is one of `question`, `update`, `sprint-end`, `blocked`, `done`,
`failed`, `stopped`. A `question` blocks only the stories it lists. While a
question is open and nothing else can move, the runner keeps running and
waits for the answer. The runner itself posts an `update` at each sprint
end that pushed review branches (or built them without pushing; see
"Sprint boundaries"). A
`manual` delivery's acceptance script arrives as a `question`; the answer is
the human's test result. The runner itself posts `blocked`, `failed` or
`stopped` when it halts (see "Run status and stops"), and a `question` when
the checkout changed under it (see "Checkout guard").

`inbox.jsonl` holds `{"id", "text", "at"}` answers, written by `answer`.

Other run files: `state.json` (resume state; `task` holds the last
non-resume `start --task`, `""` in older files; `po_cost` holds the PO
session's last running cost, see "Ledger cost"; `in_flight` the role step
running now as `{role, story, brief}`, else `null`; `interrupted` the
interrupted steps not yet shown to the PO, see "Interrupted steps";
`checkout` the `{branch, head}` the runner expects, `null` until the first
check, see "Checkout guard"; `told` the `tell` message ids already handed to
the PO; `unsaved` the cause of a halt whose salvage was skipped because the
checkout moved, else `null`, see "Interrupted steps"),
`ledger.jsonl` (per-step cost), `turns.jsonl` and `heartbeat.json` (the
live meter, see "Live meter and health"), `runner.pid` (the live runner's pid; a
stale one is ignored and the next `start` overwrites it), `stop`, `crash.log` (append-only tracebacks of every error the
runner handled, each headed `--- <time> <ExceptionType>`),
`customer/<delivery>/` (Customer Proxy sandboxes), `presentation/<story>/`
(what the Integration Tester presents to the Customer Proxy: see
"Presentation"), `api-key` (default key location).

### Liaison messages

`tell` writes the text to a draft in `.team/run/liaison/messages/`, then
links it to the next free `t<N>.md` (one more than the highest number there).
A concurrent `tell` never overwrites one, and the router never sees a
half-written file. Other files in that folder are ignored. `tell` never
touches `state.json`.

At each router pass, right after the checkout check, the router reads the
inbox answers and the messages not yet in `state.json` `told`. Either one
ends the pass with a `human_message` hand-over. Answer lines come first,
then one line per message:

```text
The human sent you a message (t3): read .team/run/liaison/messages/t3.md.
```

The text itself is not in the prompt; the PO reads the file. So a running
team gets a message when its current role step ends, or within one 5 s poll
while it waits on answers. A message sent while the PO is mid-turn waits for
that turn to end. A stopped or halted run (including `checkout-changed`)
keeps it, and `start --resume` hands it over at its first router pass. That
pass is before the PO's first turn unless a `--task` or pending interrupted
steps give the PO a turn first. `start --resume --task T` still works.

### Watch

`watch` polls every 2 s. Each poll reads `outbox.jsonl` and the shown status
(`status` and `status_reason`, with `interrupted` for a dead runner). A torn
outbox line counts as no poll. Triggers, in order:

| Trigger | Fires when |
|---|---|
| `message` | the outbox has entries after the ones already reported (all of them when the outbox got shorter) |
| `status` | the status is not plain `running` (`running` with no reason) and `(status, status_reason)` differs from the last one seen: halted, waiting on answers, budget, limit, interrupted, done, sprint end, idle |
| `health` | the live meter's health (see "Live meter and health") turned `red` since the last one seen |

When one fires, or at the first poll after `--timeout S` with nothing fired,
it prints one line and exits 0:

```json
{"triggers": ["message", "status"], "messages": [{"id": "m7", "kind": "blocked", "text": "…", "stories": [], "at": 1791800000.0}], "status": "blocked", "status_reason": "session limit, resets 9pm (Europe/Berlin)", "was": {"status": "running", "status_reason": null}}
```

The line also carries `"health": {"level", "reason"}`. A timeout line has
`"triggers": ["heartbeat"]` and `"messages": []` (this watch heartbeat is
not `heartbeat.json`). `was` is
the status seen before. What was
reported is kept in `.team/run/liaison/watch.json`
(`{messages, status, status_reason, health}`), so nothing is lost between two
watches. The first watch in a repo (no `watch.json` yet) does not report the
history: it takes the outbox, status and health as they stand as already
seen, writes `watch.json` at once, and then waits like any watch. Only what
comes after fires. Its heartbeat line still shows the current `status` and
`health`. An unreadable `watch.json` counts as empty memory: that watch
reports the whole outbox, and `was.status` is `null`. Run one watch
at a time. Every halt and every PO `notify_user` also posts an outbox entry,
so `message` catches a halt even when the status ends up as it was.

## Run status and stops

`state.json` `status` (shown by `status`):

| Status | Set by | Meaning |
|---|---|---|
| `idle` | runner | The run ended normally: the PO ended its turn and nothing could move, or a stop took effect after a step. |
| `running` | runner | The run is going (PO turns and router passes). Every `start` sets it, which clears any stop below. |
| `sprint-end`, `done` | PO (`notify_user`) | The sprint or the whole task finished. |
| `blocked` | PO (`notify_user`) or runner | Nothing can move without the human, or a usage limit was hit. |
| `failed` | runner | The runner crashed. |
| `stopped` | runner | `stop --now` (SIGTERM) ended the run, or `accept-checkout` kept a new HEAD. |
| `checkout-changed` | runner | Someone else moved the checkout; the run halted and asks the human (see "Checkout guard"). Shown red on the dashboard. |
| `interrupted` | derived by `status` and the dashboard, never stored | `state.json` says `running`, but `runner.pid` is missing or names a dead process: the runner was killed outright (`kill -9`, power loss, Ctrl-C). `running` is `false`. |

`status` also shows `running` (a live process holds `runner.pid`),
`in_flight` and `interrupted`.

`status_reason` says why the runner stopped (`null` otherwise). For example:
`session limit, resets 2:20pm (America/Edmonton)`, `crashed: RuntimeError:
boom` or `stopped by stop --now`. Older `state.json` files load with `null`.
While the router waits on open questions, `status_reason` names what it waits
on, and `status` stays as it was: `waiting on answers: s40 waits on m42; the
run waits on m43`. That is one entry per story an open question names (ids in
the order asked), then the questions that name no story. The reason clears
when an answer is handed over or a step runs (s47).

When the runner halts, it saves the status and reason, posts a note of the
same kind to the outbox, appends the traceback to `crash.log`, prints **one**
line to stderr (`agile-team start: <reason>; <advice>`) and exits:

| Exit | Cause | Status | Advice in the note and line |
|---|---|---|---|
| 0 | the run ended (see "Routing") | `idle`, or what the PO set | — |
| 1 | CLI error or failed preflight | unchanged | the error |
| 70 | any other error in the PO loop | `failed` | ``details in .team/run/crash.log; run `agile-team start --resume` to continue`` |
| 75 | a session or usage limit, in the PO or in a role step | `blocked` | ``run `agile-team start --resume` after the reset`` |
| 77 | spend reached `team.budget_usd` (see "Budget ceiling") | `blocked` | ``raise team.budget_usd in .agile-team.toml and commit it, run `agile-team accept-checkout`, then run `agile-team start --resume` `` |
| 78 | the checkout changed under the runner (see "Checkout guard"); the note is a `question` | `checkout-changed` | ``put the checkout back, or keep it with `agile-team accept-checkout`, then run `agile-team start --resume` `` |
| 130 | Ctrl-C | unchanged | — |
| 143 | `stop --now` (SIGTERM) | `stopped` | ``run `agile-team start --resume` to continue`` |

- A limit is recognized from the SDK's error text by a pattern table. The
  reset time is copied from that text (`resets 2:20pm (America/Edmonton)`).
  The runner never sleeps or resumes by itself.
- A limit inside a role step stops the run as well. The PO's `run_role`
  returns `{"status": "halted", "reason": …}`, and every later `run_role` in
  that process is refused (`the run is blocked (<reason>); end your turn`).
  Other errors in a role step reach the PO as a tool error, as before, and
  are logged to `crash.log`. That includes an error after the role ran:
  reading its handoff, gating, or applying a Manager ruling. `run_role`
  logs every crash of a role step once. The router turns it into an
  `error` hand-over.
- The first stop in a process wins. Only one note is posted, even when the PO
  then hits the same limit.
- `start --resume` sets `running` and clears `status_reason` before the PO's
  first turn, so a limit stop never leaves the resumed PO refused. When the
  PO's own query failed with an SDK error result (a limit included), its
  session id is saved, so the resume continues that session.
- A step cut off mid-way never leaves its edits in the tree (see
  "Interrupted steps"). The halt note ends with
  `; <role> on <story>'s edits are saved in <sha> (git cherry-pick -n <sha>)`.
  The stderr line does not change.
- When a question is open at the halt, the note ends with
  `; waiting on answers: s40 waits on m42`, in the same format as the waiting
  `status_reason` (s47). The stored `status_reason` and the stderr line do
  not change.

### Checkout guard

The runner records the branch it runs on and the commit it expects
(`state.json` `checkout`). Only its own git writes move the record: step and
PO commits, quarantine, saving an interrupted step, the sprint-start merge.
`accept-checkout` moves it on the human's word. While the record is `null`,
the first check that passes records the live branch and HEAD.

The checkout matches when HEAD is attached, no rebase, merge, cherry-pick,
revert or bisect is in progress, and the branch and HEAD equal the record.
The runner checks:

- on `start` and `start --resume`, before saving a killed run's edits and
  before preflight;
- on every router tick: before every router step and boundary stage, and on
  every 5 s poll while it waits for answers;
- before every PO turn;
- before every commit or quarantine, so before and after every role step;
- before every gate (also the PO's `pass_tests`);
- before saving an interrupted step.

On a mismatch the run halts at once: status `checkout-changed`, a
`status_reason`, one `question` note (`<reason>; <advice>`), exit 78. Nothing
else runs on the changed tree: no commit, quarantine, gate, salvage or
further step. A role step that already ran keeps its cost in the ledger, and
its edits stay uncommitted in the tree for the human to judge, until the
next `start --resume` saves them (see "Interrupted steps"). The PO's
`run_role` returns `{"status": "halted", …}`. The reason reads:

```text
checkout changed: expected feat/x at a3cc264; found detached HEAD at 92a38ea; last HEAD move: HEAD@{2026-10-11 16:14:54 +0200} checkout: moving from feat/x to 92a38ea
```

`found` may also read `other-branch at 1b2c3d4` or end `with a rebase in
progress`. `last HEAD move` is the newest HEAD reflog entry, or `no reflog
entry`.

The record outlives the run. Every `start` (with `--task`, `--resume` or
both) compares it with the live checkout, so a change made between runs
(a pull, merge, rebase or commit of your own) halts the next `start` with
exit 78 too. Only a repo with no record yet starts without a comparison.

`start --resume` checks again and halts again (exit 78) while the mismatch
remains, without posting a second question. Two ways on:

- **Put it back** (check out the team branch at the recorded commit). The
  next `start` passes and answers the open checkout question
  `restored: <branch> at <sha7>`.
- **Keep it**: `agile-team accept-checkout` (no runner alive, HEAD attached,
  no operation in progress). It records the live branch and HEAD, sets
  `stopped` (``checkout accepted: <branch> at <sha7>; run `agile-team start --resume` ``),
  logs a `checkout` event (`{action: "accepted", from, to}`) and answers the
  question `accepted: <branch> at <sha7>`. Use it after the liaison rebases the
  branch, or after any commit of the human's own (a budget raise, a
  reconfigure).

### Interrupted steps

The runner records the role step in flight (`in_flight`: role, story,
brief) when the step starts and clears it when the step settles. A step
that ends without settling is **interrupted**. It also gets a `step-end`
event with `"status": "interrupted"`, so no step is left open (see "Live
meter and health"). Its cause is one of:

| Cause | When the edits are saved |
|---|---|
| `error` | at once, when a role step raises an error that is not a limit (the PO still gets the error text) |
| `limit`, `crash`, `sigterm` | when the run halts (see the table above) |
| `killed` | on `start --resume`, when `state.json` says `running` and `runner.pid` is missing or dead |
| `checkout` (or any cause whose halt found the checkout moved) | not at the halt: the tree is not the team's (s61). The cause goes in `state.json` `unsaved`. The edits are saved on the next `start --resume`, once the checkout is back or accepted. Any run that starts clears `unsaved`. |

Saving means: every changed path, in scope or not, goes into one commit
`chore(team): interrupted step by <role> on <story>` (body `cause: <cause>`),
which is reverted at once, so the tree is clean. With nothing in flight,
the edits are the PO's own turn's (`by product-owner`). The sha is stored
on the story (`interrupted`) and logged as a `step-interrupted` event
(`{cause, commit, brief}`). A step with no edits records no sha.

- The next prompt for **any** role on that story says so and offers the
  work back (``git cherry-pick -n <sha>``). The offer is cleared when a step
  on the story settles.
- Every cause but `error` is also queued in `state.json` `interrupted`. The
  PO's next opening prompt gets an `## Interrupted steps` section (role,
  story, cause, sha, brief), and the queue is cleared. With pending
  interrupted steps, `start --resume` without `--task` gives the PO a turn
  before any router pass.
- `start --resume` after a kill prints
  `agile-team start: the last run was killed; <role> on <story>'s edits are saved in <sha> (reverted)`
  before preflight. After a checkout halt it prints
  `agile-team start: the last run halted (checkout) before its edits were saved; <role> on <story>'s edits are saved in <sha> (reverted)`.
  A dirty tree with no interrupted run behind it (any other status with no
  `unsaved`, a live pid, or a plain `start`) is still refused. No wrapper
  should stash or clean the tree before a resume.
- If git fails while saving, the error goes to `crash.log`, the tree is
  left as it is, and preflight refuses it on the next start.

## Dashboard

`agile-team dashboard` is an HTTP server (Python stdlib). Reads need no
auth. It never serves files by path. Its one write queues a backlog reorder
request (s83). The request is accepted only from `127.0.0.1` or `::1` and
only with the token printed in the local URL
(`dashboard: http://localhost:<port>/?token=<t>`). The token is random at
each start unless `--token T` is given, and it never appears in the
snapshot, the events or any log. The dashboard never writes `state.json`:
the runner applies the request between steps.

| Route | Returns |
|---|---|
| `GET /` | the dashboard page (`index.html`, packaged with the runner; vanilla JS, no build step). It loads `api/snapshot`, then follows `api/stream` and reconnects by itself. Its only outside resources are two pinned libraries from `cdn.jsdelivr.net`: `mermaid@11.4.1` for the Flow chart, and `markdown-it@14.1.0` for the question, answer and handoff text (raw HTML shown as text, http(s) links only, no images). If either can't load, the page shows plain text instead. |
| `GET /api/snapshot` | the snapshot as JSON |
| `GET /api/file?kind=K&id=I` | a story's file as `text/plain`. `K` is `story` (`.team/stories/`), `design` (`<docs>/design/`), `review` (`.team/reviews/`) or `acceptance` (`.team/acceptance/`). The file is `<folder>/<I>.md`, and `I` must be an opened story's id. Anything else is a 404. |
| `POST /api/reorder` | body `{"story", "position", "version"}`: `position` is the place in the Backlog group, and `version` is the snapshot's `run.order_version`. It needs the `X-Agile-Team-Token` header and a localhost peer, else 403. A bad body gets 400. Otherwise it writes `.team/run/reorders/r<N>.json` and answers 202 `{"id": "r<N>", "status": "queued"}`. |
| `GET /api/stream` | Server-Sent Events. It sends a `data:` line holding the full snapshot JSON right away, and again whenever a watched file changes or the health verdict (level and reason) changes (both checked once a second). Otherwise it sends a `: keepalive` comment every second. |
| anything else | 404 (methods other than GET and POST: 501) |

**Reorder requests (s83).** Each time the router ticks (before news and
work), it applies pending requests in number order. A request is pending
until its id is in `state.reorders`. The checks, first refusal wins: the
order changed since the page saw it (`version` differs: "…; reload"), an
unknown or done story, a current-sprint story, a place outside the
Backlog, then `move_refusal`. A request that passes is applied with
`Priority.with_move`. It may pull, since the human's request is its own
reason. It is logged as a `priority` event with `role` `null` and
`source` `human (dashboard)`. Every PO `priority` event carries `source`
`product-owner`. The new Backlog order is saved as `state.human_order`.
The PO's next hand-over prompt starts with a `From the dashboard:` section.
After that, a PO `prioritise` or `move_story` that changes the relative
order of `human_order`'s stories still in the Backlog is refused without a
reason. `start_sprint` is exempt.

The snapshot has these keys: `generated_at`, `run` (status, sprint, cadence,
task, budget, Manager checkpoint percentage, round cap, `manager_due`,
`order`: the priority queue, `backlog`: the queued stories outside the
current sprint, `order_version`: a 12-hex digest of both), `pipeline`
(enabled steps), `roles` (name,
model, provider, with PO overrides applied), `stories` (in priority order;
state plus `opened_at`, `repeated`, the story file's `acceptance`,
`position`, `tier`, `hold`, `wait`: `{"reason", "on"}` or
`null`, and from s83 `disputes`, `developer`, `commits`, `files` (the
`/api/file` kinds that exist) and `label`: `cancelled`, `held` or `""`).
`reorders` lists the last 20 reorder requests with `status`
`pending`/`applied`/`refused` and `reason`. The **Backlog** tab lists
`run.order` in two groups, Current sprint (no handles) and Backlog (up,
down, top, drag). A click expands a row to show the story file, state,
file links, spend, recent events and open questions. The board keeps that order in every column and shows each
unfinished story's `#position`. A story that cannot move shows one pill,
`⏸ <reason>`: `questions`, `manager` (a repeated setback), `round cap`,
`needs the human` (blocked, or an open question names it) or `held` (any
other hold). Below the pill is a `waits on: …` line with the open question
ids and texts, and the last step's summary or the repeated reason. The
timeline shows `escalation`, `fault` and `priority` events. The remaining
keys are `requirements` (from `<docs>/requirements/REQ-*.md`, with
`history` from `requirement-changed` events), `events` (`events.jsonl` plus
outbox and inbox entries as `message`/`answer` events), `ledger`, `messages`,
`answers` and `upstream` (remote, branch, team branch, push permission, the
last end report, the pending boundary and the review stack: each sprint's
branch, base, PR number and URL, `mode` `none`/`draft`/`ready`/`closed`,
`check` `unchecked`/`pass`/`fail`; the Board tab shows it as the **Review
stack** card, and the timeline shows `boundary` events), `turns` (the
`turns.jsonl` lines of the last 10 minutes, at most 500), `heartbeat`
(`heartbeat.json` as written, or `null`) and `health` (`{"level", "reason",
"model_note"}`; see "Live meter and health"). The contract is
`runner/agile_team/dashboard/fixtures/snapshot.json`. The Tokens tab's role
and story tables show turns per step, the latest step's turns and context
per turn next to tokens and cost (see "Turns and context"). The timeline
shows each step-end's turns and each `po-session` renewal.

Watched and read files: `.team/run/{state.json, events.jsonl, ledger.jsonl,
outbox.jsonl, inbox.jsonl, heartbeat.json, turns.jsonl}` (only the last
256 KiB of `turns.jsonl`), `.agile-team.toml`, `.team/stories/*.md` and
`<docs>/requirements/REQ-*.md`. A missing file gives an empty section. A
torn last line, which can appear while the runner is appending, is skipped.
Each snapshot re-reads `.agile-team.toml`, so a budget, round cap or
pipeline edit shows within a second. While the file is missing or does not
parse, the snapshot uses the config from start. Role files are read once, at
start.

The Board never scrolls sideways: its columns share the page width, and a
column with no cards collapses to a narrow strip. The Tokens tab's bar chart
switches between tokens and dollars. Only that chart changes, and the choice
holds across live updates.

Anyone who can reach the port can see the run (task, stories, questions and
spend). It never shows keys. Use `--host 127.0.0.1` to keep it local to the
machine.

### Live meter and health

The runner, never an agent, measures every query it drains: each role
step, and the PO's own queries.

**`turns.jsonl`**, one line per turn (one model response, one
`message_id`; a response split over several SDK messages counts once):

```json
{"at": 1791800000.0, "role": "developer-cli", "story": "s29", "step": "implement", "turn": 12, "model": "claude-sonnet-4-5-20250929", "tokens": {"input": 3, "output": 412, "cache_read": 81234, "cache_creation": 1200}, "tools": ["Bash"], "cost_usd": 0.0313, "message_id": "msg_01…"}
```

`model` is the model that actually answered. `tools` names the tools the
turn called. `cost_usd` is an estimate from per-family rates (0 on a
`billing = "free"` provider, `null` for an unknown model). The ledger's cost
stays the truth.

**`heartbeat.json`**, rewritten atomically (temp file, then rename) by a
thread in the runner. It is written when a query opens or closes, after each
turn and tool end, when runner-side work starts or ends, and every
`[health] beat_s` (20 s) in between, including while a tool or the tests
gate runs. A failed write never stops the thread. Its first failure goes to
`crash.log`:

```json
{"version": 2, "pid": 4242, "beat": "beating", "at": 1791800020.0, "mono": 523000.0, "started_at": 1791799000.0,
 "chore": null,
 "step": {"role": "developer-cli", "story": "s29", "step": "implement", "started_at": 1791799500.0,
          "turn": 12, "model": "claude-sonnet-4-5-20250929", "configured_model": "sonnet",
          "last_turn_at": 1791800012.5, "quiet_since": 1791800012.5,
          "tool": {"name": "Bash", "started_at": 1791800013.0},
          "tokens": {"input": 30, "output": 5120, "cache_read": 912340, "cache_creation": 40100},
          "cost_usd": 0.4213}}
```

`beat` is `beating`, or `ended` once the runner has exited through Python
(done, halted, stopped, crashed). After a `kill -9` it stays `beating`
and goes stale. `at` is the last write (wall clock). `mono` is the
system's monotonic clock at the same moment. That clock stops while the
machine sleeps, so a reader can tell a sleep from a late beat. `step` is the
innermost open query (a role step inside the PO's `run_role` call), else
`null`. `chore` is runner-side work such as `{"what": "settling
developer-cli on s29", "since": …}`, else `null`. Other chores are
`gate: implement on s29` while a gate runs, `sprint boundary: <stage>`,
`quality checks for s29`, `running named tests for <role> on s29`, and
`waiting for answers to m3` while the PO waits on the human. `quiet_since` is when
the query last had the floor back: its last turn, a tool's end, the end of
an inner query (a role step inside `run_role`), or the end of a chore.

**Interrupted steps.** A step that ends without a handoff (an error, a
limit, `stop --now`, a crash, a budget or checkout halt) gets a `step-end`
event with `"status": "interrupted"`, `reason` (for example `exit 143
(SIGTERM)`), `cause`, `halt` (the run's halt reason or `null`), and the
turns, tokens, `estimate_usd` and `model` measured so far. It has no
`cost_usd`, because nothing was ledgered. A runner killed outright gets this
event at the next `start --resume`, with cause `killed`. Every
`step-start` has exactly one `step-end`.

**Health** is one table in the runner (`health.RULES`). The first match does
not win: the worst level among the matching rows wins, and the reason joins
those rows' words.

| Level | When |
|---|---|
| red | the run is halted (`blocked`, `failed`, `stopped` by `stop --now` or another SIGTERM, `checkout-changed`): `halted: <reason>` |
| red | turns still arriving while the run is halted |
| red | the runner is gone (`interrupted`, or the heartbeat's pid is dead) |
| red | no turn for `red_quiet_s` (10 min) |
| red | the machine slept: wall time since the last beat exceeds the monotonic time since it by more than `stale_s`: `the machine slept for 11 min` |
| red | heartbeat older than `stale_s` (90 s), unless the excuse below applies (and not when the machine slept) |
| amber | heartbeat older than `stale_s` but excused: the last beat showed a tool open or runner-side work, the machine was awake, and the beat is no older than `red_quiet_s`: `heartbeat 2 min old while runner: gate: implement on s29 for 2 min` |
| amber | no turn for `amber_tool_s` (3 min) while a tool runs |
| amber | no turn for `amber_quiet_s` (5 min) with no tool running |
| green | runner-side work in progress (`runner: settling … for 2 min`, `runner: waiting for answers to m3 for 12 min`); the quiet rows do not apply during it |
| green | a query is open and turns are arriving |
| idle | otherwise (`idle`, `done`, `sprint-end`, and a graceful `stop`) |

A graceful `agile-team stop` (status `stopped` with no halt behind it, and
likewise `accept-checkout`) is neutral. It is `idle` whatever the heartbeat
says, with no red, no `⚠` and no `health` trigger. `state.json`'s
`halt_kind` tells the two stops apart: it holds the halt (`sigterm`,
`limit`, `crash`, `budget`, `checkout`) that set the status, and is `null`
otherwise. "No turn" counts from `quiet_since` (the last time the query had
the floor back), or from the query's start before its first turn. A red reason reads, for example, `no turn for 11 min, heartbeat
4 min old`. A late beat during a long tool or a gate is amber, not red. Under load
the beat thread can fall behind, and the last beat already says what is
running. A heartbeat without `mono` (version 1) is never excused. Any other watcher can apply the same rules to
`heartbeat.json` and `state.json`. `agile-team watch` does this for you
(the `health` trigger).

On the dashboard, the status row's pill takes the health colour (fill and
border). With a query open it reads `● developer-cli on s29 · 3.2k/min
▂▃▅▇▆▅▃▂▁▂ · 8 s`: the team's tokens per minute over the last 5 minutes, a
10-minute sparkline, and the age of the last turn. With no query open it
shows the health reason (for example the halt and its reset time), or
`▶ developer-cli on s29 · 2 min` while an old runner with no heartbeat has a
step open. The run-status pill beside it only names the status: `stopped`
is plain, because a graceful `agile-team stop` is neutral. The red of
`stop --now` and the other halts is on the health pill. Hover or
tap the pill for the step and turn, the answering model (and `configured
sonnet, answering opus` when they differ), the step's tokens and estimated
dollars, the current tool and how long it has run, and the time of the last
turn. A step that follows an interrupted one for the same role and story
shows `↻ restarted`.

The Flow tab has a **Story / Sprint / Run** toggle, remembered per browser.
It defaults to Story: the active step's story, or another story picked in
the box beside it. Each role box shows that role's ledger tokens and dollars
for the scope. A role that has not touched the story in focus is dimmed.
The active box adds its live rate, sparkline, turn, tool and the step's
estimate, outlined in the health colour.

On red, the tab title gets a `⚠` prefix. On `localhost` (a secure context)
the page also shows a desktop notification. It asks permission once, at your
first click. Over the LAN by hostname, browsers allow no notifications, so
only the title changes.

## `.agile-team.toml`

```toml
[team]
docs_dir = "docs"
artifacts = "committed"        # or "ignored"
key_file = ".team/run/api-key" # falls back to ~/secrets/anthropic-api-key
auth = "api-key"               # or "login": run on the human's Claude Code login
cadence = "sprint"             # default; the liaison asks at every start
budget_usd = 20.0              # ceiling: the run halts when spend reaches it
manager_every_pct = 25         # Manager checkpoint every N% of budget

[toolchain]
preset = "python"
test = "uv run pytest"
coverage = "uv run pytest --cov --cov-report=term"  # must print a total %
lint = "uv run ruff check ."
static = "uv run ruff format --check ."
pragma = "# pragma: no cover"

[[toolchain.targeted]]         # optional; how the runner runs named tests for a developer (s69)
root = ""                      # repo-relative dir the ids are relative to; the longest holding root wins
command = "uv run pytest -q --no-header {tests}"   # must hold {tests}: the quoted ids
# A parallel suite (s70): with pytest-xdist in the dev dependencies, add `-n auto`
# to `test`, `coverage` and the targeted `command`. pytest-cov merges the
# workers' coverage into one TOTAL line, so the gate reads it unchanged. This repo
# runs `uv run --directory agile-team/runner pytest -n auto --cov --cov-report=term -q`
# and `uv run --directory agile-team/runner pytest -q --no-header -n auto {tests}`.
# Test IDs must not hold a live value (pid, clock, temp path): xdist refuses
# to run when its workers collect different IDs.

[toolchain.globs]              # {source} {tests} {e2e} {ci} in role globs
source = ["src/**"]
tests = ["tests/**", "!tests/e2e/**"]
e2e = ["tests/e2e/**"]
ci = [".github/workflows/**"]

[gates]
coverage = 95
round_cap = 3
repeat = 2                     # the same setback this many times in a row escalates to the Manager
backstop = 4                   # this many bounces/returns in a row between two steps, any reasons, escalate too
command_timeout_s = 300        # each gate/check command; at the limit its process group is killed and the gate bounces
ci_timeout_s = 1800            # how long the sprint boundary waits for the review PR's CI checks (s81)
steps = ["design", "tests", "implement", "quality", "review",
         "design-review", "e2e", "acceptance"]   # drop steps to skip them

[health]                       # optional; the live meter's thresholds in seconds (see Live meter and health)
beat_s = 20                    # heartbeat.json rewrite interval; must be below stale_s
stale_s = 90                   # heartbeat older than this: red (amber while a tool or chore runs, awake); also the sleep threshold
amber_tool_s = 180             # no turn this long while a tool runs: amber
amber_quiet_s = 300            # no turn this long, no tool: amber
red_quiet_s = 600              # no turn this long: red

[upstream]                     # optional; these are the defaults (see Sprint boundaries)
remote = "origin"              # "" turns sync and pull requests off
branch = "main"                # merged in at sprint start; what the bottom PR targets
prefix = "team/sprint-"        # review branch names: <prefix><sprint>

[[delivery]]                   # one or more
name = "cli"
kind = "package"               # package | script | web | library | harness | manual
prepare = "uv venv {sandbox}/venv && uv pip install --python {sandbox}/venv {repo}"
bin = ["venv/bin"]             # prepended to the Proxy's PATH
e2e = ""                       # this delivery's e2e suite, run with the full checks at sprint boundaries
url = ""                       # web only; its host and port fill {host} and {port}
probe = ""                     # web only: path joined to url that must answer 200 (e.g. "api/snapshot")
commands = []                  # harness only: the Proxy's Bash allowlist
# prepare placeholders: {repo}, {sandbox} (absolute paths), {host}, {port} (from url)

[roles.integration-tester]
enabled = false                # disable a role
[roles.developer]
model = "opus"                 # override any frontmatter field
[roles.developer-embedded]
extends = "developer"          # add a role without a file
[roles.scribe]
provider = "local"             # run on a [providers.*] endpoint (see Providers)
model = "qwen3-coder"          # that provider's model name

[providers.local]              # any name but "anthropic", which is built in
base_url = "http://localhost:11434"
kind = "anthropic"             # the only kind so far; see Providers
token_env = ""                 # env var holding its token; empty sends a placeholder
billing = "free"               # free (ledgered as 0) | reported (Claude-priced)
```

Stories pick a delivery with `open_story(…, delivery="cli")`; the default is
the first one. The name must equal a configured `[[delivery]]` `name`
exactly (no prose, no case folding). Any other name is refused before the
story opens: `delivery 'x' is not a configured [[delivery]]; use one of: cli,
web`. With no `[[delivery]]` configured, the refusal says so and lists no
names. One check (`Config.delivery_refusal`) serves every path that sets a
story's delivery.

## Roles

Built-ins live in `runner/agile_team/roles/`. Frontmatter is data:

```yaml
name: unit-tester
model: sonnet          # CLI alias: opus | sonnet | haiku, or a full model id
effort: medium         # low | medium | high | xhigh | max
provider: anthropic    # default; or a [providers.<name>] from the config
tools: [Read, Grep, Glob, Write, Edit, Bash]
write: ["{tests}"]     # !glob excludes; {placeholders} from [toolchain.globs]
read: ["**"]
extends: _shared       # or another role, e.g. developer-cli extends developer
enabled: true
```

### Your instructions: global and repo layers

Two layers of human-written role files sit on top of the built-ins:

| Layer | Directory | Applies to |
|---|---|---|
| global | `~/.config/agile-team/roles/` (`$AGILE_TEAM_HOME/roles/` when set) | every repo |
| repo | `.team/roles/` | this repo |

- `<role>.md` **without** frontmatter is an addendum, appended to the role's
  prompt (global first, then repo). HTML comments are dropped, so a
  scaffolded stub changes nothing until you write in it.
- `<role>.md` **with** frontmatter replaces the role (or adds one). Repo beats
  global beats built-in.
- `_shared.md` addenda apply to every role.

`roles scaffold` writes the stubs; `roles list` shows what each layer does.
Global files can live in a dotfiles repo; the runner only reads them.

System prompt order: `_shared` (+ `_shared` addenda) → role chain bodies →
global addendum → repo addendum → `.team/CLAUDE.md` →
`.team/briefs/<role>.md` → file scope.

## Providers

A role's `provider` picks the endpoint its step talks to. Every provider so far
has a **Claude front end**: the step still runs in Claude Code, with the same
tools, guard hooks, sandbox and handoff, and only the model behind the
Anthropic Messages API changes. Ollama, a LiteLLM proxy or any other
Anthropic-compatible server works. For a provider other than `anthropic`, the
step's environment gets:

- `ANTHROPIC_BASE_URL` set to `base_url`;
- `ANTHROPIC_AUTH_TOKEN` set from `token_env`;
- `ANTHROPIC_API_KEY` blanked, so the project key never leaves for that endpoint;
- Claude Code's default and subagent model variables pinned to the role's
  `model`.

`billing` controls the ledger. With `free`, the step is recorded at $0 and does
not count towards the budget ceiling. With `reported`, the step keeps
`total_cost_usd`, which Claude Code prices at Claude rates (for a resumed PO
query, only its own share: see "Ledger cost").

Preflight probes `base_url` and checks `token_env` for every provider that an
enabled role uses. The PO's kickoff lists each such role as
`role (provider: model)`. `set_role_model` takes a provider, so the PO can move
a struggling role back to `anthropic`.

Which roles suit a local model: Scribe and Code Quality Czar; Unit and
Integration Tester are worth a try. Keep PO, Architect, DevOps, Code Reviewer
and Manager on Claude. DevOps runs on Opus at high effort, like the Architect,
because the tooling and hooks it writes run around every other role. Weak tool use mostly shows up as bad handoffs, which bounce
and count a round. At the round cap, the PO gets the story.

**Other vendors.** `kind` names the harness. Supporting another vendor's agent
CLI (Codex, Gemini, …) would mean adding a `ProviderKind` and a dispatch path
that runs that CLI in place of `query()`. That path would lose the PreToolUse
guard and keep only the post-step diff audit and quarantine. Role files would
not change.

## Handoff block

Every role ends with:

````
```handoff
{"status": "done", "summary": "…", "changed_files": [], "open_questions": [],
 "next_role": null, "friction": ""}
```
````

`status`: `done`, `changes_requested`, `blocked`, `failed`. The Architect
adds `"developer": "<role>"` (a string or `null`) to name the developer
specialisation a story needs; the runner uses it for the implement step (see
"Routing"). `friction` is
optional: what slowed the step down or would make it cheaper. It is logged on
the step-end event for the Manager. A developer at `implement` may add
`"dispute": {"test": "<test id, file path first>", "rule": "<design rule
id>", "reason": "…"}` with status `changes_requested` when a test contradicts
the design (see "Test disputes"). A dispute without `test` and `rule`, or
with another status, is a malformed handoff. The unit-tester may add
`"tests": "changed"` or `"tests": "confirmed"` when a story is back at
`tests` with its code in (see "Back at tests with the code in"). The Manager adds `"ruling"` (`rescope`,
`upgrade_model`, `revise_design`, `escalate`, `advance`), optionally
`"ruling_reason": "<why>"` (a string; it defaults to the summary and is
logged on the `ruling` event), and may add `"followups":
{"<role>": "<question>"}`. On a story escalated for a repeated setback it
must add `"fault": "<role>"` or `"fault": "runner"` (see "Repeated
setbacks"). It may name a fault on any other story it is run on too, for
example a `blocked` story whose gate reason is a runner fault. A `fault` that is not a non-empty string is a malformed
handoff. The runner appends each follow-up to that role's
next brief under "Questions from the Manager" and clears it once the role
hands off; the answer comes back in that role's `friction`. A missing or
malformed block fails the step (and counts a round).

### What the Manager sees

The Manager's runner context carries `budget` (the corrected
`budget_status`: `spent_usd`, the ceiling `budget_usd`, `remaining_usd`,
`pct_used`, `by_role`, tokens and `po_overcount_usd`; see "Ledger cost"), `spend_by_role`
(steps, cost, cost per step, tokens, `turns_per_step`, `latest_turns` and
`context_per_turn`, most expensive first; see "Turns and context"),
`long_running_roles`, `friction_since_last_review` (friction from step-ends
since its last step) and `pending_followups`, beside the review reasons,
overrides and capped stories. It also carries
`test_disputes_since_last_review` (story, role, test, rule, rounds for each
test dispute since its last step). When it runs on a story escalated for a
repeated setback, it also carries `repeated_setback` (see "Repeated
setbacks"; its `code` entry says whether the story's code is already in:
`{"implemented", "code_commits", "code_in"}`), and `stories_at_round_cap` leaves that story out. The Manager raises every role in
`long_running_roles` as friction in its summary, with one proposal: split
the step, change the brief, or change the tools.

### Rulings

A ruling applies to the story that the Manager's step runs on, at any step
and in any status (active, at the round cap, blocked). It moves the story
(`rescope` → first step, `revise_design` → `design`, `escalate` → blocked,
`advance` → the next enabled step, `active`) and resets its rounds, test
disputes, open dispute and setback loop. `advance` is for a gate no role
can satisfy. It moves on from where the story is when the ruling applies
(after any fault), and passing `implement` this way counts as an
implement pass. The Manager's report carries
`"ruling": {"ruling", "applied": true, "now_at"}`, and the `ruling` event
logs `{ruling, reason, now_at}` (`reason` is the handoff's
`ruling_reason`, else its summary). When the ruling cannot
apply, the report says why and the story does not change:
`{"ruling", "applied": false, "why"}`. That happens when the step has no
story (`a ruling needs a story; run the manager on that story`), the story
is done (`story sN is done; a ruling cannot move it`), or `advance` is
asked at the last enabled step (`story sN is at <step>, its last step;
advance cannot mark it done`). On a repeated
setback the `fault` applies first and a ruling in the same handoff then
wins; see "Repeated setbacks".

### Ledger cost

Each ledger entry's `cost_usd` is what that one query cost. Claude Code's
`total_cost_usd` is a running total for the **session** (ADR-004 in the
docs). A role step always starts a fresh session, so its figure is already
its own. The PO resumes one session, so the runner ledgers only the
difference:

- `own = reported − base` when `reported ≥ base`, else `reported` (a drop
  means the counter restarted). `base` is the running total last seen for
  the session the query resumes, or `0` for a fresh session or a different
  session.
- `state.json` keeps `po_cost: {"session", "reported"}` with the raw
  figure, so `start --resume` keeps the baseline. An older `state.json`
  takes its baseline from the last PO ledger entry.
- The provider's `billing` applies to the own cost. A query with no result
  ledgers `0` and leaves `po_cost` as it was.
- A PO query that is never ledgered (an error result) is still in the
  next query's running total, so that query's difference pays for it.

Ledger lines are never rewritten. PO entries written before s25 are running
totals, so they are corrected when the ledger is read (ADR-007):

- A PO entry with `at` before `1791694950` (2026-10-11 05:02:30 UTC, when
  s25 began ledgering deltas) is legacy. Legacy PO entries, in file order,
  each count only `figure − previous legacy PO figure`, or the figure
  itself when it is lower (a new session). Other entries count as written.
- One function (`ledger.corrected`) does this, and every reader goes
  through it: `status`, `budget_status`, `spend_by_role`,
  `long_running_roles`, the budget checkpoints, the ceiling, the Manager's
  runner context and the dashboard snapshot. They all show the same spend.
- `budget_status` (and `status`'s `budget`) carries `po_overcount_usd`, the
  amount the correction takes off the raw ledger. In this repo that is
  about $1,024.87: ADR-004's $256.93 covered only lines up to 196, and the
  same PO session ran on to line 310.

### Budget ceiling

`team.budget_usd` is a ceiling. The runner halts the run when the corrected
spend, rounded to 4 places as `budget_status.spent_usd` shows it, is at or
over `budget_usd`. It checks:

- after every role step has landed (committed and gated; a step is never
  cut off for budget);
- after every PO query is ledgered;
- at run start, before the PO's first turn. A `start --resume` that is still
  over the ceiling halts at once, with no query and no spend.

The halt is like a limit stop: status `blocked`, `status_reason`
`budget reached: spent $X of $Y`, one `blocked` note to the liaison, every
later `run_role` refused, and exit 77. After a halt, no further PO query
starts in that process. The run can pass the ceiling by at most the step or
PO query that was in progress. To carry on, the human raises `budget_usd` in
`.agile-team.toml`, commits it, runs `agile-team accept-checkout` (the commit
is not the runner's, see "Checkout guard"), and runs `agile-team start --resume`. The
file is tracked and preflight refuses a dirty tree, so an uncommitted raise
is refused (`working tree is dirty (.agile-team.toml); commit or stash
first`) and the run stays `blocked`. The runner never commits the raise for
the human. The config is read
afresh at start, and `status` and the dashboard re-read it on every call, so
nothing else needs a restart. Under `unattended`, exit 77 ends the job as
failed (it is not a limit to wait out). The Manager checkpoints
(`manager_every_pct`) still apply below the ceiling, on corrected spend.

### Turns and context

Each ledger entry (`ledger.jsonl`, one per role step and per PO query)
records the step's `turns` beside its tokens and cost. The `step-end` event
carries `turns` too. Ledger lines written before turns were recorded count
as steps but are left out of turn averages. Per role (and per story on the
dashboard):

| Field | Meaning |
|---|---|
| `turns_per_step` | turns ÷ steps that recorded turns |
| `latest_turns` | the turns of the role's most recent such step |
| `context_per_turn` | (input + cache read + cache write tokens) ÷ turns: the average context a turn re-sends |

`long_running_roles` lists each role whose last 3 measured steps include at
least 2 of more than 30 turns, with those turns and its `context_per_turn`.

There is **no turn cap**: turns are reported, and no step is stopped for
them. If a cap is ever added, the role gets one warning turn to write its
handoff before the cap ends the step.

Every query (role steps and the PO) runs with `strict_mcp_config` and
`ENABLE_CLAUDEAI_MCP_SERVERS=false`. It loads only the MCP servers the
runner passes (the PO's `team` tools, the Customer Proxy's sandbox servers),
never the human's claude.ai connectors. Why: `docs/adr/ADR-003-lean-context.md`.

### The PO stays in its lane

The PO may read only `.team/**` and the docs directory, so it cannot read
source or tests. Diagnosis goes to the architect, reviewer or devops.

## Pipeline and gates

design (architect) → tests (unit-tester; gate: test command **fails**, or
see "Back at tests with the code in") →
implement (developer-*; gate: tests pass and coverage ≥ threshold, or ≥
`.team/baseline.json` coverage when old debt keeps the total lower; the gate
runs the suite **once**, through the `coverage` command only: a zero exit
with a high enough total passes, and a non-zero exit never passes. It
bounces as a coverage shortfall when the output shows a total below the
requirement and no failing test, and as `tests fail` otherwise) → quality
→ review → design-review → e2e (integration-tester; gate when `acceptance`
is enabled: a `done` handoff passes only with a complete presentation and,
for a `web` delivery, a service that starts from it and answers its probe)
→ acceptance (customer-proxy).

A failed gate or `changes_requested` moves the story back and adds a round
(a test dispute is the exception: see "Test disputes"; the same setback
twice in a row escalates instead: see "Repeated setbacks"). At
`round_cap` the runner refuses every role but the Manager on that story.
`blocked` and `failed` do not count a round. When `e2e` is enabled,
`run_role(customer-proxy)` on a story with no complete presentation does not
start the Proxy. The runner moves the story back to `e2e` **without** a round
(gate event `verdict: "return"`) and reports `{"status": "returned", …}`. The
same happens when a `web` delivery's service does not come up for the Proxy
(the reason holds its output). The runner then runs the integration-tester
itself.

### Runner results and runner tools

Only the runner runs the full suite and coverage (s69). Roles get the
results in their briefs instead:

- The tests gate's `test` run and the implement gate's `coverage` run are
  kept per story, whatever the verdict, in `.team/run/results/<story>/<name>.json`
  (exit code, the last 60 output lines, the HEAD they ran at, where they ran).
- Before a quality-czar step the runner runs `lint` and `static` (when set),
  and `coverage` only when the kept run is missing or not at HEAD. That time
  is a runner chore on the heartbeat. The quality czar has no shell; it judges
  these results.
- A brief carries `## Runner results` with the kept runs its step needs:
  implement: `test`, `coverage`; quality: `coverage`, `lint`, `static`;
  review: `coverage` (`results.BRIEF_RESULTS`).
- A developer step has two runner tools: `run_tests` (named test files or
  node ids, repo-relative or as pytest prints them) and `run_new_tests` (the
  test files the unit-tester committed for the story). They refuse a
  directory, an empty list and an unresolvable id, so they never run the
  full suite. The runner runs each `[[toolchain.targeted]]` command (the row
  whose `root` holds the test) under `command_timeout_s`, as a runner chore,
  and logs a `tests-run` event with the tests, exit codes and seconds. With
  no `[[toolchain.targeted]]` rows the tools refuse, and the developer names
  tests in Bash.

### Time limits

Every command the runner runs for a gate has a time limit:
`[gates] command_timeout_s`, 300 s by default. This covers the test and
coverage commands, the dispute's test run, the gates' git lookups and the
full checks at sprint boundaries. Each command gets the full limit. Each
runs in its own process group with stdin at `/dev/null`. At the limit the
runner kills that group (`SIGKILL`) and nothing else. It then reads what the
group wrote, for at most 5 s more. The command counts as exit code 124.

- At `tests` and `implement` a timeout **bounces** (the story stays at the
  step and a round counts). The reason starts
  `the command did not finish in time:` and ends with the output's tail. The
  tail's last two lines are
  `timed out after 300s, so the runner killed its process group: <command>`
  and either `the hanging test: <file>::<test> (line N)` or a line saying no
  test is named. At `tests` a timeout never counts as a failing test. A
  `"tests"` claim does not pass it either.
- The hung test is named from a stack frame in the output, in faulthandler's
  format or the traceback format pytest-timeout prints. Set a per-test
  timeout (pytest-timeout) or pytest's `faulthandler_timeout` below the gate
  limit so there is a frame to find. This repo's runner suite uses
  `pytest-timeout`, so a hanging test fails by itself and the suite goes on.
- The runner suite's per-test limit (s72) is **1 s for a unit test**
  (`timeout = 1` in `[tool.pytest.ini_options]`) and 30 s for a test in
  `tests/e2e/` (`e2e_timeout = 30`, same table). `tests/time_limit.py` marks each test
  with its world's limit at collection, covering setup, call and teardown. A
  test over it fails as `FAILED <test id> - Failed: Timeout (>1.0s) from
  pytest-timeout.` A slow unit test is made fast (fake clock, a fake instead
  of the real call) or moved to `tests/e2e/`; no test sets its own limit.
- At a sprint boundary a timed-out check fails with `timed out`.
- `[gates]` is human-owned: a role's edit to it is quarantined.

### Unit tests touch no OS

The rule for every repo the team works on, in any language: **a unit test
runs no shell command and touches no OS.** That means no process (git
included), no signal, no real pid, no clock or sleep, no network, no
environment and no filesystem, a temp dir included. The unit-tester mocks
them at the repo's OS seam. A test that needs the real OS is an e2e test.
The unit-tester can't write the e2e glob, so it removes such a test from the
unit suite and lists it in its handoff summary as
`moves to e2e: <test id> (<what it proves>)`. The integration-tester
recreates each one under the e2e glob in the same story's e2e step.

The agile-team runner follows the rule itself (s71):

- `agile_team/system.py` is the only module that touches the OS. Other
  modules import it as a module (`from agile_team import system`) and call
  `system.read_text(...)`, `system.run(...)`, `system.now()`. A
  `from agile_team.system import name` import is not allowed.
- Every unit test runs against `tests/fake_system.FakeSystem`, swapped in by
  an autouse fixture. It holds files in memory (it can also simulate a
  missing file, an unreadable file or a full disk), a reply table for
  commands (git included), a clock, ids, signals and the network.
- An audit hook in `tests/conftest.py` fails a unit test that reaches the
  real OS anyway, and so does a patch on calls that raise no audit event
  (pids, waits, `signal`, `time.sleep`, `shutil.which`, `platform`,
  `os.stat`). The message names the call and ends with
  `inject it, or move the test to tests/e2e/`. Tests under `tests/e2e/` run
  on the real OS.
- Ruff `TID251` (`banned-api` in `agile-team/runner/pyproject.toml`) bans
  direct OS calls (`subprocess`, `os.environ`, `time.sleep`,
  `ThreadingHTTPServer`, …) everywhere except `system.py`, `tests/e2e/`,
  the fake, the guard and its own test, `tests/conftest.py`,
  `tests/dashboard_node.py` and `scripts/`. A new OS call needs a new
  `system` function, a matching `FakeSystem` method and an e2e test.
- The move ran in three phases, each with a green suite: files and the clock
  (s71), processes, signals and the network (s76: `system.run`,
  `spawn_piped`, `spawn_logged`, `killpg`, `http_get`, `listen_http`, …;
  only `system.py` calls `os.killpg`), then the runtime and the CLI (s77:
  `async_sleep`, `which`, `home`, `cwd`, `open_browser`, `on_signal`) and
  ruff `TID251`. Every unit test now runs in the fake world; only
  `tests/e2e/` runs on the real OS.

### Repeated setbacks

A **setback** is a gate outcome that sends a story back or holds it:
`bounce`, `return` or `hold`, including a gated role's malformed handoff
(which now logs a `gate` event like any bounce). Passes and test disputes
are not setbacks. For each setback the runner records, on the story's
`streak` in `state.json`: step, step sent to, role, verdict, `author`
(`role` when the reason is a role's handoff, `runner` when the runner's own
gate, return or hold wrote it), the reason, the event id and a **key**:

`<step>><to_step> <normalised reason>`

The reason is lowercased and passed through a table of patterns
(`loops.NORMALISE`): date-times and clock times → `<time>`, URLs → `<url>`,
`host:port` → `<host>`, anything with a `/` → `<path>`, ids such as `s4` or
`e451` → `<id>`, commit shas → `<sha>`, other numbers → `<n>`, runs of
whitespace → one space. So `nothing is listening at 127.0.0.1:8799` and
`nothing is listening at 127.0.0.1:8800` share a key. Two different failing
tests do not.

- A setback with the same key as the last one extends the streak, and a
  different key restarts it at 1. A pass in between does not reset it, so a
  ping-pong between two steps still counts. A Manager ruling or fault
  clears it.
- When the streak would reach `[gates] repeat` (default 2, at least 2), the
  runner does **not** send the story round again. The gate verdict becomes
  `escalate`: the story stays at its step, gets no round, becomes
  `needs_manager`, and `repeated` holds the full reason. The gate event is
  an `escalation` event: the gate fields plus `key`, `author`, `count` and
  `history` (the earlier setbacks' event ids). Every setback's `gate` event
  carries `key`, `author`, `count` and `history` too.
- An escalation is not a hand-over. The router's next step is the
  `manager` **on that story**, with a brief that starts `Story sN hit the
  same setback N times in a row…` and a `repeated_setback` entry in the
  runner context: the reason verbatim (the last gate or job output), key,
  count, author, the history (roles, steps, verdicts, reasons, event ids)
  and the story's `gate`, `step-end`, `test-dispute`, `escalation`,
  `ruling` and `fault` events since the first setback. If the escalating
  step also handed over (questions, blocked), the PO gets the story first,
  and the Manager runs after `continue_story`.
- While a story is escalated, `run_role` of any gated role on it is
  refused: `story sN repeated a setback (<key>); the manager rules on it
  first`.
- The Manager names the owner of the fault with `"fault"`:

  | `fault` | Effect |
  |---|---|
  | a role with an enabled step | the story goes to that role's step, `active` |
  | another known role (e.g. `devops`) | `active`, step kept; the PO gets `off_pipeline_fault` and briefs that role |
  | `runner` | `blocked`; flagged as a runner fault in the `fault` event (`kind: "runner"`); the runner posts an `update` note to the human naming the story and reason, and the PO gets `runner_fault` |

  A fault resets the story's rounds and disputes, clears its open dispute,
  hold, `streak` and `repeated`, so the loop costs no role a round. A
  `ruling` in the same handoff applies after the fault and wins.
- A fault works the same on a story that did **not** repeat a setback (s45),
  for example a `blocked` or `needs_manager` story the PO runs the manager
  on. Its `reason` is the story's last gate reason.
- A fault is not applied if there is no story, the story is done, the fault
  is missing (only on a repeated setback) or the role is unknown. Then
  nothing changes, the PO gets `fault_not_applied` with the reason, and a
  `ruling` in the same handoff is reported as not applied too (`the fault was
  not applied, so the ruling was not either`, so `ruling_not_applied`).
- The Manager's report carries `"fault": {"fault", "kind", "applied",
  "reason", "now_at"}` (or `"why"`), and a `fault` event logs `{fault, kind,
  reason, now_at}`. Every fault or ruling the Manager names is in the report
  with `applied` true or false. The PO's `run_role` result and the router's
  hand-over carry the same report.
- The next standard brief on the story says `The same setback repeated, so
  the manager ruled on it: <reason>`. The Manager's `followups` tell the
  fault role what to fix.
- Role prose seldom repeats word for word, so two summaries saying the same
  thing differently are two keys. The round cap and the backstop still
  apply to them.
- **Backstop.** A `bounce` or `return` from one step to another extends the
  story's `run` when it crosses the same pair of steps as the last one,
  whatever its reason; a new pair restarts it at 1. A pass of the step that
  sends the story back, a fault or a ruling empties it; holds and in-place
  bounces leave it alone. When the run would reach `[gates] backstop`
  (default 4, at least 2), the setback escalates exactly as above, with
  `rule: "backstop"` on the escalation event, every reason in `repeated`,
  and a brief that starts `Story sN bounced between <step> and <to_step> N
  times in a row…`. If both rules fire, the repeat rule wins. Gate events
  carry `bounces` (the run length, 0 when the setback does not count). The
  backstop is for runs that include returns, which count no round; pure
  bounces reach the round cap first.

### Back at tests with the code in

Each story counts how often it has passed the implement gate
(`implemented` in `state.json`) and records the sha of every commit the
runner makes for a developer step on it (`code_commits`, whatever the
step's outcome). The story's **code is in** when `implemented > 0`, or when
one of those commits is in the branch (`git merge-base --is-ancestor <sha>
HEAD`). A ruling, a review or a closed dispute can send a story back to
`tests` after its code is in, and a developer can commit code and then
dispute a test (s46). Its suite may then be green already. In that case,
with no dispute open and a `done` handoff:

- A red suite passes, as on a first pass.
- A green suite passes when the handoff says `"tests": "changed"` (the
  unit-tester changed tests for the story) or `"tests": "confirmed"` (it
  checked that the existing tests already cover it). The gate reason is
  `tests pass on code from an earlier pass; tests <claim>`.
- A green suite without a claim bounces back to `tests` with a round:
  `tests pass on code from an earlier pass; write a failing test, or hand
  off "tests": "changed" or "tests": "confirmed"`.
- A `changes_requested` goes where its `next_role` points, as with an open
  dispute.

The unit-tester's prompt says `Code from an earlier pass is in…` while this
applies. On a first pass (`implemented` is 0 and no recorded developer
commit is in the branch) the gate still needs a red suite, and a claim is
ignored. A `state.json` written before s46 loads `code_commits` as `[]`; a
story stranded that way is moved on by the Manager's `advance` ruling. An open dispute's own gate (below) takes
precedence. Any other value of `tests` is a malformed handoff. A
`state.json` written before s24 loads `implemented` as 1 for stories past
`implement` and as 0 for the rest.

### Test disputes

Developers cannot edit tests. When a test contradicts the design, the
developer hands off `changes_requested` with a `dispute` (see "Handoff
block"):

1. The runner moves the story from `implement` to `tests` without running
   the implement gate. It logs a `test-dispute` event (the gate fields plus
   `test`, `rule` and `disputes`) instead of a `gate` event. The first
   `round_cap` disputes on a story count no round, and each later one counts
   a round. A Manager ruling resets the count.
2. Every step on the story gets `Test dispute (raised|confirmed): <test>
   contradicts <rule>: <reason>` in its prompt until the story is back at
   `implement`. When the dispute opens, the runner runs the test command
   once and keeps what it says about the test (`output` on the dispute):
   the lines from the first one naming the test (40 at most) plus later
   lines naming it, or `the test command passes, so <test> is not failing`,
   or, when the output never names it, its tail. The next line of the
   prompt quotes it: `Output of the test command when the dispute was
   raised:` and the output in a code block.
3. At `tests`, the unit-tester either fixes the test and hands off `done`,
   or confirms it with `changes_requested` and `next_role: architect`. A
   `done` passes only when the test file's content changed since the
   dispute was raised; otherwise it bounces and counts a round, with a
   reason naming the test id, the file and the baseline hash. Confirming
   moves the story to `design`, counts a round and marks the dispute
   `confirmed`. The red-tests gate does not run while a dispute is open.
4. The architect rules on a confirmed dispute (it keeps the rule or changes
   the design) and hands off `done`. Back at `tests`, a `done` then passes
   whether or not the test changed, and the story goes on to `implement`.

A dispute is free only when the unit-tester upholds it. If the tester
confirms the test, the developer's round is spent all the same.

How "changed" is checked (s30):

- **Path.** When a dispute is raised, the runner resolves the test file
  (the test id up to `::`) to a tracked path at the repo root. It uses the
  path as given if git tracks it. Otherwise it uses the only tracked file
  that ends with `/<path>` (a runner-relative id such as
  `tests/test_x.py` resolves to `agile-team/runner/tests/test_x.py`). With
  no match, several matches, or an unreadable file, the dispute is
  rejected: the developer's step bounces back to `implement` with a
  round, and the reason says to give the path from the repo root.
- **Baseline.** The dispute stores the resolved `file` and a `baseline`:
  the sha256 of the file's content as it was when the dispute was raised,
  with whitespace and comments removed. Python is compared by its tokens.
  Other files are compared line by line, with whitespace collapsed and
  whole-line comments dropped for known suffixes. The gate compares the
  working tree's file with the baseline, not commits. Editing only
  whitespace or comments is not a change. Changing an assertion, a
  parameter row, a string or a test name is. A deleted file counts as
  changed.
- **Repeats.** The same "unchanged" bounce twice in a row escalates to the
  Manager (see "Repeated setbacks"), so it never runs into the round cap
  by itself.
- **Older disputes.** A dispute saved before s30 has no baseline. It
  passes at the next `done`.
- **Way out.** `pass_tests(story, reason)` (PO tool) moves a story stuck
  at `tests` to the next step. Stuck means one of these: an open dispute,
  `needs_manager`, `blocked`, or a repeated setback. The runner runs the
  test command first and refuses on a red suite, or on a story that is not
  stuck or not at `tests`. The move resets the story's rounds, disputes
  and setback history, clears its hold, and passes `reason` to the next
  brief as a note. It logs a `tests-passed` event and queues a Manager
  review.

## Presentation

The Integration Tester presents each story to the Customer Proxy; the Proxy
never builds or repairs an environment (a broken one is `changes_requested`
to `integration-tester`).

- Before each integration-tester step the runner creates
  `.team/run/presentation/<story>/` if it is missing and, for every delivery
  kind but `manual`, `workspace/` in it as a git repo (`git init`, only when
  `workspace/.git` is missing). It never wipes them (s65): the presentation
  survives a bounce from acceptance back to e2e, and only the tester
  replaces what is in it.
- **Git stays in the workspace** (s65). The integration-tester (step `e2e`)
  and the Customer Proxy (step `acceptance`) are *confined*, per the
  `dispatch.GIT_CONFINED` table. Their workspace is the story's
  `workspace/` for the tester, and the Proxy's copy
  `<sandbox>/presentation/workspace` for the Proxy. Their Bash runs with
  `GIT_CEILING_DIRECTORIES=<.team/run, resolved>`, so git in a directory
  with no `.git` below the run dir says "not a git repository" instead of
  finding the team repo, even from a script. It also runs with
  `CLAUDE_BASH_MAINTAIN_PROJECT_WORKING_DIR=1`. The guard then allows any
  git command whose directory and paths all lie inside the workspace. The
  directory is the step's cwd, moved by a `cd DIR &&` before the command,
  then by `-C`. The paths are `--git-dir`, `--work-tree`, `-c` values, and
  the path arguments of `init`, `clone`, `remote`, `config`, `submodule`,
  `worktree`, plus the repository of `push`/`fetch`/`pull`. That lets
  `git init demo`, `git -C demo rebase main` and `git clone demo copy` run.
  In the step's own cwd only the read-only list below is allowed. Anything
  else is denied:
  `<role> may not run `git <sub>` on <target>: in this step git works only inside <workspace>, and the team repo <repo> is the runner's. …`.
  A `cd` followed by anything but `&&` makes the directory unknown, and
  later git is denied unless it has an absolute `-C` inside the workspace.
  A confined step's Bash may not mention `GIT_CEILING_DIRECTORIES`,
  `GIT_DIR`, `GIT_WORK_TREE`, `GIT_DISCOVERY_ACROSS_FILESYSTEM` or
  `CLAUDE_BASH_MAINTAIN_PROJECT_WORKING_DIR`.
- The tester builds the workspace the way a customer would have it (for this
  runner: `agile-team init` already run, plus the run files the ACs need),
  writes `PRESENTATION.md` (what to try for each AC), and adds real
  live-run output such as `agile-team status` as `live-status.json` when an
  AC needs a live run.
- The presentation is self-contained. The Proxy's sandbox can't read repo
  paths, so `PRESENTATION.md` never names one and the presentation holds no
  links into the repo. Anything an AC cites (an ADR, a protocol section,
  files to try, test, coverage or ruff output) goes into the presentation
  as a verbatim copy or as captured output with its command and exit code
  (for example `docs/` and `evidence/`).
- Complete = `PRESENTATION.md` is not blank and, except for `manual`,
  `workspace/` holds something besides `.git`. Otherwise the e2e gate
  bounces with `story sN has no presentation: <path> is missing or empty`.
- **Up and answering** (s26). Each kind's row in `presentation.PRESENTATIONS`
  says whether its check is `files` or `service`; only `web` is `service`.
  For a service, once the files are complete, the e2e gate runs a trial: it
  prepares the sandbox exactly as for the Proxy (presentation copied in),
  starts the delivery's `prepare` in the background, and probes
  `url` + `probe` every 0.25 s for up to 30 s. It passes (`presentation
  ready; <url> answered`) only on HTTP 200 (and, for a JSON response, a
  body that parses), then stops the service. A start that exits or never
  answers bounces to `e2e` with a round:
  `story sN presentation is not up: delivery '<name>' did not start: the start command exited with code <rc> before <url> answered. Last output: …`
  (or `… did not answer <url> within 30s. …`), quoting the last 20 lines of
  its output. A port that another process holds puts the gate on **hold**
  (no round, the PO gets a `gate_hold` hand-over):
  `delivery '<name>' cannot start: <host>:<port> is already in use by a process the runner did not start; stop it or change the delivery's url`.
- For the Proxy step the runner copies the dir to `<sandbox>/presentation/`
  (symlinks kept as links) **before** the delivery's `prepare` runs, so a
  `web` prepare can serve `{sandbox}/presentation/workspace`. A `web`
  service is started and probed the same way before the Proxy starts. The
  Proxy's prompt quotes `PRESENTATION.md` and gives the copy's absolute
  path.
- A service is never reused. Its process group id is in
  `.team/run/customer/<delivery>.pid` and its output is in `<delivery>.log`
  next to it. Before each start, the runner stops a group still named
  there (left by an earlier step or a killed runner). It stops the service
  when the Proxy's step ends (pass, fail, halt or crash) and deletes the pid
  file. It never kills a process it did not start (s41). It signals a group
  only when the pgid is the leader's own pid and is not the runner's own
  group. It signals a pid from the pid file only when that process still
  leads its group and started no later than the file was written (checked
  with `ps -o etime=`). A stale or reused pid is ignored and the file is
  deleted. If the leader is gone but other members of its group still hold
  the port, the start holds on the busy port.
- Stopping a service (s82) ends its whole process group, not just the shell
  the runner started. It sends SIGTERM to the group and returns only once the
  leader is reaped and no process is left in the group (the shell, `uv` and
  the server alike). A group still alive after 10 s gets SIGKILL and 5 s more.
  Then the stop waits up to 5 s for the delivery's port to refuse
  connections. It never waits more than 20 s, and it never signals a leader
  that had already exited before the stop. If the port is still in use at the
  deadline, the trial puts the gate on **hold**:
  `story sN presentation did not stop: delivery '<name>' did not let go of <host>:<port>: it was still in use 5s after the service was stopped; keep the service in its start command's process group`.
  A start that never came up adds that line to its bounce reason. After the
  Proxy's step, the next start holds on the busy port.
- Service lifecycle (s58). The e2e gate's trial stops its service on purpose,
  because a gate leaves nothing running. The Proxy step does not reuse that
  service. Planning the step (`plan()`) starts a fresh one from the copied
  presentation and probes it. Nothing between the plan and the Proxy's
  session stops it. It stops only when the session ends, or when the plan's
  own set-up fails.

The Manager must also run after `start_sprint`, after any `set_role_model`,
and when spend crosses each `manager_every_pct` checkpoint. The runner runs it
before any other step while one of these is due (see "Routing").

## Routing: the runner drives, the PO judges

`start` alternates **PO turns** with **router passes**. A PO turn resumes the
PO's session with one prompt (the kickoff, the resume note or a hand-over)
and lasts until the PO ends its turn. A router pass runs steps with no PO
involved, in this order:

0. the pending sprint **boundary** (sync, full checks, review branches,
   push; see "Sprint boundaries"), one stage per step, or its DevOps fix
   step. A held boundary is skipped. While a boundary is pending, no sprint
   story moves;
1. the `manager`, story-less, while `manager_due` is not empty;
2. the `manager` on a story escalated for a repeated setback (in the
   current sprint, not held, not blocked by a question; see "Repeated
   setbacks");
3. the `scribe`, on each story that has just reached done (`scribe_due`);
4. the next step of the movable story that comes first in the **priority
   ranking** (see "Story priority"). A movable story is in the current sprint,
   `active` and not held, and no open question blocks it. A story that is not
   movable keeps its place in the order and is skipped until it is released.
   Step 2 also takes the escalated story that comes first in the ranking.

The role for a story step is the first of these that fits the step: the PO's
`set_developer` choice, the role a bounce named (`next_role`), the role that
just bounced at this step, the Architect's `developer`, and finally the
step's default role.

Each step gets a **standard brief**. It lists the paths that exist from
`.team/stories/<id>.md`, `<docs>/design/<id>.md` (else
`<docs>/architecture.md`) and `.team/reviews/<id>.md`. It adds the previous
step's role, status and summary; on a bounce or return,
`Sent back to this step: <gate reason or reviewer summary>`; and any
`continue_story` note from the PO.

The pass ends at the first step whose report matches a row of the
`HANDOVERS` table. The PO then gets every matching reason in one prompt:

| Trigger | When |
|---|---|
| `refused` | the step was refused |
| `error` | the step raised an error other than a limit (traceback in `crash.log`) |
| `stopped` | the handoff is `blocked` or `failed` |
| `gate_hold` | the gate put a `done` step on hold for an environment reason (e.g. a `web` delivery's port is in use by another process); `continue_story` once it is fixed |
| `bad_handoff` | the `manager` or `scribe` gave no valid handoff |
| `questions` | the handoff has `open_questions` |
| `quarantine` | the step's out-of-scope changes were quarantined |
| `round_cap` | the story reached the round cap (not an `escalate` verdict) |
| `unroutable` | a bounce names a `next_role` that owns no pipeline step |
| `ruling_not_applied` | the Manager ruled but the ruling could not apply (see "Rulings") |
| `runner_fault` | the Manager put a setback on the runner; the story is blocked and the human was told |
| `off_pipeline_fault` | the Manager put a setback on a role with no pipeline step; brief it, then `continue_story` |
| `fault_not_applied` | the Manager's `fault` was not applied (missing, unknown role, no story or a done story); the reason is in the line |
| `sync_conflict` | rebasing the team branch onto upstream at sprint start conflicts (the stopping commit and its files, grouped by directory with a count; the rebase was aborted and the branch is unchanged) |
| `push_permission` | the review branches are built and checked, and the human has not yet said whether the team may push |
| `push_rejected` | a review branch push was refused (its remote branch moved) |
| `boundary_error` | a boundary stage raised an error (traceback in `crash.log`) |
| `boundary_escalated` | the same boundary failure repeated after a fix and the Manager reviewed it |
| `ci_green` | the review PR's CI checks all passed; the line says it is **ready to merge**, and the PO tells the human. This is the only text that calls a PR ready |
| `ci_failed` | the review PR's CI failed; the line names each failing check (workflow / job), its link and its failing test lines. The PO opens a bug story at once, records it with `record_ci_bug`, tells the human the PR is **NOT** ready, and lists the story first in the next sprint |
| `ci_pending` | the CI checks were still running at `[gates] ci_timeout_s`; the line names them. The PR is NOT ready; `continue_boundary` waits again |

The runner also hands over `human_message` (the inbox has answers the PO has
not seen, listed by id with the question, or `tell` messages it has not
been handed, each as a path to read; see "Liaison messages"), `sprint_end` (every story
in the sprint is done and the sprint's end boundary has finished; a
`Review: …` line says what was pushed) and `stalled` (nothing can move; the
reason for each story is listed, or the held boundary). Gate bounces, `changes_requested` to a pipeline role, a
gated role's malformed handoff and `returned` do **not** hand over. The
runner passes their reasons on in the next standard brief. An `escalate`
verdict does not hand over either: the runner runs the Manager on the
story.

- A story named in a hand-over is **held** (`hold` in `status`): the router
  skips it until the PO calls `continue_story(story, note)` or runs a step on
  it with `run_role`. A done story never moves again, so its hold does not
  stop its Scribe; the Scribe runs after the PO's turn. `continue_story`
  clears a done story's hold too (for example after `ruling_not_applied`),
  and its note reaches the Scribe's brief if the Scribe is still due.
- PO tools added: `continue_story(story, note)` releases a held story (done
  or not) and adds `note` to its next brief. It refuses a `blocked` story,
  with or without a hold, because releasing it would leave the sprint
  stalled (s45). Run the manager on that story with a ruling or a fault
  instead. `set_developer(story, role)` picks the
  developer for that story; it refuses an unknown role or one that is not a
  developer. `pass_tests(story, reason)` (s30) moves a story stuck at
  `tests` on when the suite is green (see "Test disputes").
- When nothing can move but a question is open, the runner waits for an
  answer (polling every 5 s, no timeout). `stop` ends the wait. Each poll
  reads the inbox first, so an answer ends the wait within one poll, whether
  or not a PO session is running, and the PO gets it as a `human_message`
  hand-over. While it waits, `status_reason` lists each story and the
  question ids it waits on (`waiting on answers: s40 waits on m42`). A
  `stalled` hand-over never happens while a question is open.
- The run ends when a stop is requested, the run halts, the PO sets
  `sprint-end` (sprint cadence), `done` or `blocked`, or the PO ends a turn
  and the next pass finds only "sprint complete" or "nothing can move" without
  running a step.
- `start --resume` with no `--task` runs a router pass first. The PO gets a
  turn only when that pass hands over; its prompt then starts with the resume
  note. Exception: with interrupted steps pending, the PO gets the first
  turn (see "Interrupted steps").
- Each hand-over is logged as a `handover` event:
  `{"triggers": [...], "stories": [...], "steps": n}`.
- `state.json` additions: per story `developer`, `po_developer`, `hold`,
  `note`, `previous` (the last gated step: role, status, summary, verdict,
  reason, next_role), `dispute` (the open test dispute: test, rule, reason,
  `file` (resolved at the repo root) and `baseline` (content hash when
  raised, s30), stage `raised` or `confirmed`, `output` (the test command's
  output about the test when raised, s46)), `disputes` (disputes since
  the last ruling), `implemented` (implement-gate passes), `code_commits`
  (shas of the developer steps' commits on the story, s46), `streak` (the
  setbacks since the key last changed), `run` (the bounces and returns in a
  row between one pair of steps), `repeated` (the repeated reason while
  escalated, else `null`), `escalated_by` (`repeat`, `backstop` or
  `null`) and `interrupted` (saved work from an interrupted step, offered to
  the next step; see "Interrupted steps"); run-level `order` (the PO's
  story order; see "Story priority"), `scribe_due`, `delivered` (answer ids the
  PO has seen), `goal` (the current sprint's goal), `boundary` and
  `upstream` (see "Sprint boundaries"). Older files load with these empty. On the first run after
  the upgrade, every answer already in the inbox counts as seen.

## PO sessions

The PO is the only role whose session lasts across turns. To keep it from
growing for a whole sprint, the runner **renews** it at two boundaries:
`start_sprint`, and a story reaching done. Each boundary adds a reason to
`state.json` `po_renew_due`. Before the PO's next turn that resumes a
session, the runner renews it once for all the reasons queued, then clears
them:

1. **Compact** (`po_renew_path: "compact"`, the default). One PO query on
   the session with `/compact Keep only what your next turns need: open
   decisions; pending questions with their ids and the stories they block;
   what is next and why; paths to artifacts …`. It worked if the stream
   holds a `compact_boundary` system message. The turn then goes on in the
   same session.
2. **Handoff** (fallback). If no boundary came back, `po_renew_path` becomes
   `"handoff"` from then on (it is saved in `state.json`), and the runner deletes
   `.team/po/handoff.md`. It then asks the PO to write that file (the same
   list) and starts a **fresh** session. The fresh session's first prompt
   holds the kickoff header (mode, cadence, roles, the task), the handoff,
   the `story_status` JSON, the open questions and the prompt the turn was
   going to send. The new session id is saved when that query ends. If the
   PO writes no handoff, the old session goes on (`kept`).

Neither path relies on the PO's memory for the human: every open question
is listed again from the inbox (`- q3 (blocks s5): …`), and answers are
handed over from `delivered` as before. Each renewal is logged as a
`po-session` event: `{"path": "compact" | "handoff" | "kept", "reasons":
[...], "pre_tokens": n | null}`. Renewal queries are ledgered as PO
entries. A halt during a renewal keeps `po_renew_due`, so the next run
renews again. The PO may write `.team/po/**`. Older `state.json` files load
with no reasons and the `compact` path.

## Backlog and sprints

Each story in `state.json` has `sprint`: the number of the sprint it is
committed to, or `null` when it is in the backlog.

- `open_story` puts a story in the backlog. It refuses an existing id and a
  `delivery` that is not a configured `[[delivery]]` name (empty means the
  first one), and changes nothing when it refuses.
- `start_sprint(goal, stories)` is the only way into a sprint. It opens sprint
  `N+1` with exactly the listed stories. Unfinished stories it does not list
  go back to the backlog. Done stories never move; they keep the sprint they
  finished in. It refuses an empty list or unknown ids (`unknown stories: s7;
  open them with open_story first`) and changes nothing when it refuses.
- The `sprint-start` event carries `{"sprint", "goal", "stories"}`.
- `run_role` on a backlog story is refused: `story sN is in the backlog; add
  it to a sprint`. The status refusals (done, blocked, round cap) come first.
  `manager`, `scribe` and story-less steps are not affected.
- A story is in at most one sprint. To carry it over or add it mid-sprint,
  list it in the next `start_sprint`, which queues the Manager again.
- `state.json` from before backlogs existed loads every story into the
  backlog. Step, rounds, status and commit are kept. On resume, the runner
  tells the PO that nothing can move, and the PO starts a sprint with the
  stories to continue.
- `start_sprint` opens the sprint's **start boundary**, and it is refused
  while a boundary is pending (`sprint N <edge> boundary is still pending
  (…); finish it first`). See "Sprint boundaries".
- The order in which `start_sprint` lists its stories is their priority
  within each group. Started stories still come first (see "Story
  priority").

## Story priority

Started stories are finished before new ones are started (s51). A story is
**started** when it has commits in the tree: the runner recorded its first
commit (`commit` in `state.json`). A step that committed nothing does not
start a story. Every unfinished story is in one **group**:

| Group (`tier`) | Stories |
|---|---|
| `in progress` | started (or pulled, below) and not held |
| `held` | started (or pulled) and held: a `hold`, `blocked` or `needs_manager` |
| `not started` | everything else |

`state.json` `order` is the PO's explicit list of story ids. It covers
sprint stories and the backlog. One rule ranks every story. These keys are
compared in turn:

1. done stories come last;
2. the group: `in progress`, then `held`, then `not started`;
3. the story's index in `order`; stories not in `order` come after those
   that are;
4. the id, with numbers compared as numbers (`s9` before `s10`).

So the order ranks stories within each group, and a started story always
runs before a story not started. The unfinished stories in this ranking are
the **queue**. A story's **position** is its place in the queue (1 = next).
The router follows the ranking (see "Routing"). Holds, open questions, the
round cap and blocks never change `order`. While a started story is held it
ranks after the stories in progress, and its position changes. Once it is
released, it goes back to its place. The router skips a held story, so it
never stops another story from routing. A file without `order` or `pulled`
loads with empty lists.

**Pulling ahead.** The PO can pull a not-started story ahead of the started
ones on purpose, with a reason. Pulled ids are kept in `state.json`
`pulled`, and a pulled story ranks as if started. A pull without a reason is
refused: `pulling s45 ahead of started stories needs a reason; give one, or
place them after the started stories`. A pulled story leaves `pulled` at
the next change once it has a commit or is done.

PO tools:

- `prioritise(stories, reason)` puts the listed ids first, in the order
  given. Every other unfinished story keeps its place in the PO's order
  after them (its place in `order`, not in the queue, so the groups are
  never written into `order`). When the
  list names a started story, a not-started id listed before it is pulled,
  and one listed after it is unpulled. A list that names no started story
  leaves the pulls as they are.
- `move_story(story, position, reason)` moves one story to `position` on
  the board. Moved before a started story, a not-started story is pulled.
  Moved after all of them, it is unpulled. In `order` the story goes next to
  its nearest neighbour on the board in the group it ranks in (after the one
  before it, else before the one after it), so it lands at `position`
  whenever its group allows, and every other story keeps its place in
  `order`. When the groups place the story elsewhere for
  now (a started story moved behind not-started ones, or a held one moved to
  1), the move is kept and the result adds a `note`: `s21 ranks #2, not #4:
  stories in progress come first, then held started ones, then the rest; its
  place in the order is kept`.
- `start_sprint(goal, stories)` puts the sprint's stories first, in the
  order listed, within each group. It never pulls from its list, except for
  the s81 CI bug story, which is pulled. Its reason is the goal (plus `CI
  failed on the pushed code; sN fixes it` for that pull).

Each change builds the new `order` from the old one, never from the queue,
so a held story keeps the place the PO gave it, even when the PO reorders
other stories while it is held. A story opened later has no explicit place until the
PO gives it one. Refusals change nothing:
`no stories listed; pass the story ids in the order to work on them`,
`unknown stories: s7; open them with open_story first`, `done stories have
no place in the order: s1`, `position must be a whole number from 1 to N`,
and the pull refusal above. Each change is logged as a `priority` event
(role `product-owner`; `story` is the moved story for a move):
`{"change": "set" | "move" | "sprint", "order": [...], "moves": [{"story",
"from", "to"}], "reason": "...", "pulled": [...]}`. `order` is the queue
after the change. `moves` lists only the stories whose position changed.
`pulled` lists the stories this change pulled ahead. `story_status` returns
the stories in ranking order, with `order` set to the queue and `pulled`.
The snapshot gives each unfinished story its `tier`.

## Sprint boundaries: sync, full checks, review stack

At each sprint's start and end the runner runs a **boundary**: code steps,
not prompts, that no role can skip. It is saved as `state.json` `boundary`
(`edge` `start`/`end`, `sprint`, `stage`, `hold`, `failure`, `streak`,
`rounds`, `escalated`, `restack`, `note`) until it finishes. Each stage logs
a `boundary` event (`edge`, `sprint`, `stage`, `outcome`, plus `note`,
`reason`, `sha`, `files`, `branch`, `branches`, `checks`, `hold`, `key`,
`count`, `history`, `ci`, `prs`, `results`, `story` where they apply). While a boundary is pending, no story
in the current sprint moves: `run_role` of a gated role on one is refused
with `sprint N <edge> boundary is at <stage>…; the sprint's stories move
once it passes`.

**Skipped.** With `[upstream] remote = ""`, no such remote, a failed
`git fetch` or no `<remote>/<branch>`, the whole boundary is skipped with
one `skipped` event and a note. This is not an error. (At a sprint end whose
fetch failed, the sprint is still added to the stack.)

**Start** (opened by `start_sprint`, before any role runs, including the
Manager):

1. **sync**: fetch. Drop stack entries whose commits are all in main (see
   below). Then rebase the team branch onto `<remote>/<branch>`
   (non-interactive, no autosquash, no autostash; commits already upstream,
   merge commits and commits that become empty are dropped). There is never
   a merge, `-s ours` or `-X ours` (s59, ADR-012). After a rebase the
   runner pairs each old commit with its copy (author, date and message, in
   order; a dropped commit maps to the last kept copy, or to the target)
   and rewrites the team hashes in `state.json`: each story's `commit`,
   `code_commits` and interrupted sha, the run's interrupted shas,
   `upstream.last_end` and each stack entry's `start`/`end`. Then it
   records the checkout and saves. `upstream.checked` is not rewritten, so
   the full checks run again. A path only one side touched must keep that
   side's version. Otherwise the branch is reset to where it was and the
   boundary holds `error`. On a conflict the rebase is aborted, the team
   branch is unchanged, and the PO gets `sync_conflict` with the stopping
   commit and its files grouped by directory. The human rebases by hand and
   the PO calls `continue_boundary`. The runner remaps from the HEAD it
   recorded at that boundary's first sync (`boundary.sync_from`, saved
   before the rebase starts), so a hand rebase is rewritten too, and so is
   a rebase that a crash cut off before the hashes were saved. If git stops
   the rebase for a reason other than a conflict (for example, an untracked
   file would be overwritten), the boundary holds `error` and the rebase is
   left stopped. The human finishes it (`git rebase --continue`) or aborts
   it (`git rebase --abort`), then the PO calls `continue_boundary`. Hashes
   quoted in reviews and stories are not rewritten.
2. **check**: the full checks on the team branch (skipped when HEAD is the
   sha that last passed them).
3. **review**, **push** and **ci**, only when an entry was dropped (a PR was
   merged): the stack is rebuilt and pushed so the next PR is retargeted,
   and the PR that is no longer a draft has its CI watched.

**End** (opened when every sprint story is done, before the `sprint_end`
hand-over):

1. **sync**: fetch, drop merged entries, and add this sprint's entry:
   branch `<prefix><N>`, range `start..end` (start = the previous entry's
   end, or `git merge-base HEAD <remote>/<branch>` for the first one).
2. **check**: the full checks on the team branch.
3. **review**: in the scratch worktree `.team/run/review/`, each entry's
   own commits (`start..end`, no merges, only those whose patch is not in
   main) are cherry-picked onto the latest main, each on the branch below.
   This uses `rerere` and skips picks that come out empty. The branch is
   then set. An entry with nothing left is in main and drops out. The
   bottom and the newest branch get the full checks.
4. **push** (needs `gh` and permission): each branch is pushed with
   `--force-with-lease` against the sha the runner last pushed. Then its PR
   is created or updated: the bottom one is **ready** with base `main`, and
   each other one is a **draft** based on the branch below. A PR that is
   closed (or merged elsewhere) is left alone. The runner posts an `update`
   to the human with the PRs (`open` or `draft`). That update never calls a
   PR ready.
5. **ci** (s81, after a push): for each non-draft PR the runner runs
   `gh pr checks <n> --watch`, all under one deadline of `[gates]
   ci_timeout_s` (default 1800 s). It then reads `gh pr checks <n> --json
   name,state,bucket,link,workflow`. While no checks are reported yet (right
   after a push), it looks again every 10 s, at most 12 times. For each
   failing or cancelled Actions check it reads `gh run view --job <id>
   --log-failed` and keeps the failing test lines (pytest `FAILED …` and
   `ERROR …::`, go `--- FAIL:`, `N failed`; at most 20; else the last 10
   lines). The result is saved per stack entry as `ci` (`pr`, `url`,
   `head`, `verdict`, `checks` with `name`, `workflow`, `bucket`, `link`,
   `lines`). It is also logged on the stage's `boundary` event (`ci`, `prs`,
   `checks`, `results`). Verdicts:
   - **green** (every check passed or was skipped, at least one passed):
     the boundary finishes. The PO gets `ci_green` ("ready to merge") and
     tells the human.
   - **red** (any check failed or was cancelled, even with others still
     pending): the boundary is held `ci_failed`. The PO gets the failing
     checks with job names and test lines, opens a bug story at once,
     calls `record_ci_bug(story)` and tells the human the PR is NOT ready.
     `continue_boundary` waits for the checks again, for when the human
     re-ran them. Only green or a recorded bug story finishes the
     boundary.
   - **pending** (the deadline passed): held `ci_pending`, naming the
     running checks. The PR is not ready; `continue_boundary` waits again.
   - **none** (no checks reported, only skipped ones, or no non-draft PR):
     the boundary finishes. The human is told that no CI result exists, and
     the PR is not called ready.

   The CI stage blocks the router while it waits, as a runner chore
   (`sprint boundary: ci`), so health stays green. If the run is stopped
   during the wait, resume waits again. The sprint-end hand-over then says
   `Review: …` with the CI text.

**Full checks**: the `[toolchain]` `lint`, `static`, `test` and `coverage`
commands (coverage must reach the gate or the baseline), then each
delivery's `e2e` command. Every configured check runs, and the failed ones
are quoted (`<name> failed (<why>): <command>` plus the last 30 lines).

**Failures.** A failed check or a rebuild conflict becomes a **DevOps fix
step**, whose brief quotes the output. Failed checks on the team branch or
a review branch are fixed on the team branch. For that step DevOps may also
write source, tests and e2e tests, and the runner commits it and checks or
rebuilds again. A conflict is resolved in the review worktree, in exactly
the conflicting files, and recorded with `git rerere`, so later rebuilds
reuse it. A fix step that hands over (blocked, questions…) holds the
boundary. Each failure is a setback keyed `<edge>><stage> <normalised
output>` (see "Repeated setbacks"). The same failure again, or
`round_cap` fix steps, **escalates**: the boundary is held, `manager_due`
gets `sprint N <edge> boundary failed K times at <stage>; see
repeated_boundary`, and the Manager's context carries `repeated_boundary`
(reason, key, count, history, events). The PO then gets
`boundary_escalated` with the Manager's summary.

**Permission.** The first push asks: the PO gets `push_permission`, asks
the human once, and records the answer with `set_push_permission` (`yes`
or `no`). `state.json` keeps it in `upstream.push` for every later sprint.
With `no`, or without `gh` (missing or logged out), the branches are built
and checked locally, and the human is told their names and that no CI
result exists (`local` event with `ci: none`).

**Safety.** The runner pushes only branches that start with `[upstream]
prefix`, never the team branch, never `[upstream] branch`. The only force
is the lease on a review branch. Roles still cannot run git commands that
write.

**PO tools.** `continue_boundary(note)` releases a held boundary. Its stage
reruns, and the note reaches the next fix brief. After an escalation it
also resets the streak and rounds. At the `ci` stage it waits for the checks
again. `set_push_permission(answer)`. `record_ci_bug(story)` works only
while the boundary is held `ci_failed`, and only for a story that exists
and is not done. It records the story in `upstream.ci_bug` and finishes the
boundary with a `done` event (`ci: red`, `story`). The `Review:` text reads
`checks failed, story sN opened`. While `ci_bug` names a story that is not
done, `start_sprint` is refused unless that story is listed first. The
sprint that lists it clears `ci_bug`.

**Ready.** Only a green CI result produces the words "ready to merge": the
`ci_green` hand-over and its `Review:` text. A red, pending, missing or
unwatched result is always reported as NOT ready.

`state.json` `upstream`: `team_branch`, `push` (`unasked`/`yes`/`no`),
`stack` (per entry: `sprint`, `branch`, `start`, `end`, `title`, `stories`,
`head`, `checked`, `check`, `pushed`, `pr`, `url`, `base`, `mode`, `ci`),
`last_end`, `checked` (the last team sha that passed), `closed` (the last
sprint whose end boundary finished), `report` and `ci_bug` (the bug story
for a failed CI, until a sprint lists it first).

CI: the repo's workflows skip draft PRs (`if:
github.event.pull_request.draft == false`, with the `ready_for_review`
trigger), so only the bottom, non-draft PR runs CI, and only it is watched.
Once `ci_green` says it is ready, merge it with **Rebase and merge**.

## Enforcement

- PreToolUse hook: Write/Edit/NotebookEdit outside the role's write globs are
  denied. The Customer Proxy's Read/Grep/Glob are limited to its sandbox
  (which holds the presentation copy), `.team/stories/`, `.team/acceptance/`
  (so it can read and rewrite its own report) and `<docs>/customer/`; its
  Bash may not name a forbidden root, `..`, or repo paths outside the
  sandbox. The Integration Tester may also write `.team/run/presentation/**`.
- Before any Bash check, for every role, the hook joins line continuations
  as bash and zsh do: a newline after an odd run of `\` is deleted along with
  the last `\`. After an even run (escaped `\\` pairs) the newline stays and
  ends the command. A `#` comment that ends in `\` does not continue in the
  shell, so a command that holds `#` is also checked in a second view. In
  that view, continuations are joined except on a line that holds `#`. The
  key-name, git, allowlist and path checks run on every view, and a denial in
  any view denies the command. A quoted `#` can over-deny, but no view
  under-denies.
- Forbidden roots: for each positive glob in `[toolchain.globs]` `source`,
  `tests` and `e2e`, the leading path segments before the first segment that
  holds `*`, `?`, `[` or `{` (`agile-team/runner/agile_team/**` →
  `agile-team/runner/agile_team`; `src/main.py` → `src/main.py`). `!` globs and
  globs that start with a wildcard give none. A root nested in another root is
  dropped. With no roots at all, the hook forbids `src`.
- Proxy Bash words: the hook denies a word when the shell (bash or zsh) could
  expand it to a forbidden root or a path under it, read from the repo root.
  Over-denying is accepted. Literal and wildcard words go through the same
  steps:
  1. Words are unquoted by `shlex`. If shlex can't parse the command, the
     whitespace-split words have `'`, `"` and `\` deleted.
  2. Denied: a `..` segment anywhere. Also denied, in any segment except the
     last: a `{` or `(`, or a leading `.` together with `*`, `?` or `[`. Such a
     segment could climb (`..`) or span a `/`.
  3. The word is normalized: leading `.` and `/` are stripped, `a//b` and
     `a/./b` become `a/b`, a trailing `/` is dropped. It is then compared
     without regard to case.
  4. A word made only of `*` and `?` (`ls *`) passes.
  5. The word's segments are paired with each root's segments, from the left.
     The word is denied if the root runs out first, or if a `**` segment is
     reached. It passes if the word runs out first (an ancestor) or if a pair
     doesn't match. A segment with `[`, `{` or `(` matches any one segment.
     Any other segment is matched with `fnmatch`, where `?` counts as `*`.

  So `agile-team status`, `cat agile-team/docs/*.md` and `echo {1..3}` pass.
  `cat agile-team/runner/agile_*/cli.py`, `cat */runner/agile_team/cli.py` and
  `cat {,}agile-team/runner/agile_team/cli.py` are denied. With flat roots
  (`src`), so are `cat src*` and `cat {,}src`, while `ls *` passes. Not
  covered: `$VAR`, `$(…)`, `~`, a change of cwd (`cd`), and words glued to
  `--opt=` or `<`.
- The Proxy's Bash cwd is its sandbox, so a relative path such as
  `cat agile-team/docs/customer/x.md` passes the hook but does not reach the
  docs. The Proxy reads customer docs with the Read tool.
- Every role: no writes under `.git/`; no Read/Grep/Glob/Write of the key
  files or `~/secrets/` (hook plus Claude Code `permissions.deny` rules); Bash
  may not mention `ANTHROPIC_API_KEY` or the key paths; Bash git is limited to
  `status`, `diff`, `log`, `show`, `blame`, `grep`, `ls-files`, `rev-parse`,
  `describe` and `cherry-pick -n`, so no role can commit, rewrite history or
  push. Only the runner pushes, and only review branches (see "Sprint
  boundaries"). The check sees through prefixes (s65): `X=1 git commit`,
  `env git commit`, `command git commit`, `timeout 5 git commit` and
  `/usr/bin/git commit` count as `git commit`. A confined step
  (integration-tester, Customer Proxy) may also run any git inside its
  workspace, and nothing outside it (see "Presentation").
- Every role: Bash may not hold an open wait loop. A segment that starts
  with `until` or `while` is denied unless some segment starts with
  `timeout` or `gtimeout`. `while read …` and `while IFS= read …` (a loop
  that ends with its input) and `for` loops pass. Run a suite in the
  foreground, or give the wait a deadline (see the "Never wait without a
  deadline" role rule).
- Every role: Bash may not signal the runner's process group, which holds
  the runner and the agent CLIs it starts (s41). `pkill` and `killall` are
  denied, because the agent's command line holds its whole prompt and can
  match. `kill $(…)`, `` kill `…` `` and `xargs kill` are denied, because
  their targets are picked at run time. A `kill` target of `0`, `-1`,
  `-<runner pgid>`, or a pid in the runner's group is denied. Stop your own
  work by the pid you saved (`cmd & PID=$!` … `kill $PID`). Residual risk:
  the hook cannot resolve a variable target (`kill $p`, `kill $PPID`), so
  that passes. The repo's own code and scripts never use `pkill` or
  `killall` either (s76): `tests/e2e/test_kill_words_e2e.py` scans every
  tracked code file (`tests/kill_words.py`) and fails CI on a use outside
  the guard's denylist and its test tables.
- Every role but DevOps: Bash may not run the full suite or coverage (s69,
  `suite_check.SUITE_RULES`). The check looks at segments that start with a
  launcher (`uv`, `python…`, `poetry`, `timeout`, `env`, `exec`, `command`,
  `xargs`, a shell's `-c` string, `pytest` itself, …), after any leading
  `NAME=value` words. Such a segment is a full run, and is denied, when it
  runs `pytest` and not every path it names is a test file or node id
  (`tests/`, `.` and `tests/*.py` are not, so `pytest tests/test_x.py tests/`
  is a full run). Any `--cov…` flag or `coverage run` is denied too. Write
  option values with `=` (`--foo=1`): a spaced value counts as a path, which
  makes the run full. Redirects (`2>&1`, `>out`) are not paths, but a
  redirect target after a space (`> out`) is, so write `>out` or pipe to
  `tail`. The reason says how to ask the runner (`run_tests`,
  `run_new_tests`). A run that names only tests
  (`pytest -q tests/test_x.py::test_y`) passes, except for the code reviewer
  and the quality czar, who run no tests. Residual risk: pytest run from a
  script, a `make` target, a `$VAR` or `python -mpytest`, and other test
  tools, are not seen. DevOps is exempt only so the onboarding sprint can
  record its coverage baseline; its role file (s75) tells it to run only
  what proves its change, normally one named test, and to leave the full
  suite and coverage to the runner's gate.
- A change to `.agile-team.toml` outside `[toolchain]` and `[[delivery]]` is
  quarantined, so no role can widen its own scope for the next run.
- Residual risk: the key is in the runner's environment, so a role's Bash could
  still read it through an interpreter (e.g. `python -c 'import os; …'`). Use
  a project-scoped key with a Console spend cap.
- After each step the runner diffs the tree. Out-of-scope changes are
  committed as `chore(team): quarantine out-of-scope changes by <role>` and
  reverted at once; the PO gets the sha.
- In-scope changes: the first commit of a story is `feat(<story>): <title>`,
  later ones `fixup! feat(<story>): <title>`. Every step commit has a body
  `<role>: <handoff summary>`, so a fixup says what it changed. Story-less
  steps commit `chore(team): <role> step`; the PO's own story edits commit as
  `chore(team): product-owner step` before the next role runs. Nothing is
  autosquashed.
- Proxy OS sandbox: Claude Code `sandbox.filesystem.denyRead` on the repo with
  `allowRead` for the sandbox, stories, `.team/acceptance` and customer docs, plus
  `permissions.deny` rules `Read(/<repo>/<root>)` and `Read(/<repo>/<root>/**)`
  for each forbidden root, so the rules never cover `<docs>/customer/` unless a
  source or test glob does. A delivery that serves locally (a kind whose start
  is `background`, today `web`) also gets `sandbox.network.allowLocalBinding:
  true`, so the Proxy's sandboxed `curl` reaches the service on 127.0.0.1;
  other kinds get no `network` key (s58). Needs bubblewrap (Linux) or Seatbelt
  (macOS). On macOS, an e2e test runs the bundled claude CLI with these
  settings. A sandboxed `curl` gets 200 from a live local service, and it
  exits 7 without the `network` key. Linux is not verified end to end; the
  test is skipped there.

## Delivery kinds

| kind | prepare | Proxy tools |
|---|---|---|
| `package` | build and install into `{sandbox}` | Bash, Read/Grep/Glob, Write; cwd = sandbox |
| `script` | copy scripts and samples into `{sandbox}` | same as package |
| `web` | start the server in the background (it can serve `{sandbox}/presentation/workspace`); the step waits until `url` + `probe` answers 200; stopped after the step | Playwright MCP, Bash limited to `curl`, Read, Write |
| `library` | build the package; Proxy works in `{sandbox}/consumer` | Bash, Read/Grep/Glob, Write/Edit |
| `harness` | anything DevOps defines | Bash limited to `commands`, Read, Write |
| `manual` | nothing | Read, Write; its acceptance script goes to the human as a question |

When the story has a presentation, every kind gets its copy in
`{sandbox}/presentation/` before `prepare` runs. Every kind except `manual` has a `workspace/` in it.
