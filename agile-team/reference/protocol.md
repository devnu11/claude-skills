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
| `init --detect` | Print the detected stack preset, commands, globs and suggested acceptance environment kind (`environment_kind`) as JSON. No writes. |
| `init --preset P --environment K [--url U] [--docs-dir D] [--artifacts committed\|ignored] [--key-file F] [--budget USD] [--cadence sprint\|until-blocker]` | Phase A: write `.agile-team.toml`, `.gitignore` lines, `.team/CLAUDE.md`, a stub per role in `.team/roles/`; commit `chore(team): onboard agile team`. |
| `init … --reconfigure` | Re-run phase A; keeps every value already in the config and never overwrites the charter. A section under its old name is rewritten as `[[environment]]` (see "Acceptance environments"). |
| `config check` | Validate config, every role's resolution and glob placeholders. Prints each warning as `warning: <text>` first (warnings never change the exit code), then the problems. Exit 1 on problems, else 0. |
| `roles list` | JSON: each role's layers (built-in, global, repo: `replace`, `addendum` or `stub`) and its resolved model, provider, effort and write scope. |
| `roles scaffold [--global]` | Write a commented stub for `_shared` and every enabled role that has no file yet, in `.team/roles/` (default) or the global dir. Never overwrites. |
| `start --task T [--cadence C] [--onboard] [--resume]` | Preflight, then run the team in the foreground (the liaison backgrounds it): the runner drives the pipeline and calls the PO for judgement (see "Routing"). With `--resume`, `--task` is optional and reaches the PO as "New from the human". Exit codes: see "Run status and stops". |
| `status` | JSON: run `status` and `status_reason` (why the runner stopped, what a waiting run waits on, or `null`), current `sprint`, stories with their pipeline step, `sprint` (`null` = backlog) and routing fields (`hold`, `developer`, `previous`; see "Routing"), open questions, spend, the pending sprint `boundary` (or `null`), `upstream` (the review stack; see "Sprint boundaries"), `checkout` (the branch and HEAD the runner expects, or `null`; see "Checkout guard") and `queued_messages` (ids of `tell` messages the PO has not been handed yet, e.g. `["t3"]`). |
| `tools` | JSON `{"built_in": [...], "repo": [...]}` (s99): `built_in` is the runner's stage table in order, each `{"name", "label", "description", "when", "attach"}`; `repo` is the config's `[[tool]]` rows in file order, each `{"name", "description", "command", "label"}` (`label` since s127, `""` when not given). Exit 1 with the `[[tool]]` refusal when the config is broken. See "Runner stages". |
| `answer ID TEXT` | Answer PO question `ID`. |
| `tell SOURCE` | Queue a message for the PO. `SOURCE` is a file, or `-` for stdin; the text never goes on a command line. Stored as `.team/run/liaison/messages/t<N>.md`; prints `queued t<N> for the PO: <path>`. Works in any run state (running, waiting, halted, stopped). Exit 1 on an empty text (`the message is empty`) or an unreadable file. See "Liaison messages". |
| `reply STORY SOURCE` | The liaison answers on story `STORY`'s dashboard thread. `SOURCE` is a file, or `-` for stdin (as `tell`). Appends `{"story", "text", "at"}` to `.team/run/liaison/replies.jsonl` and prints `replied lr<N> on <story>`. Works in any run state, with no runner. Exit 1 on an empty text (`the message is empty`), a text over 4000 characters (`the message is longer than 4000 characters`), an unknown story (`no story 's9'`) or an unreadable file; nothing is written. See "Story threads". |
| `opinion STORY KIND SOURCE` | The liaison records its opinion on story `STORY` (s85). `KIND` is `keep`, `move-up`, `move-down`, `fold`, `close`, `scope` or `ask`; `SOURCE` is a file, or `-` for stdin. Appends `{"story", "kind", "text", "at"}` to `.team/run/liaison/opinions.jsonl` and prints `recorded o<N>: <kind> on <story>`. Checked in order, first refusal wins and nothing is written (exit 1): an unknown story (`no story 's9'`; a done story is allowed), an unknown kind (`no opinion kind 'x'; use one of: keep, move-up, …`), an empty or over-long text (as `reply`). Works in any run state. See "Liaison opinions". |
| `reviewed SOURCE` | The liaison records that it reviewed the backlog, with a short summary from a file or `-` (stdin). Appends `{"text", "at"}` to `.team/run/liaison/reviews.jsonl` and prints `recorded backlog review v<N>`. Exit 1 on an empty or over-long text. See "Liaison opinions". |
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
`failed`, `stopped`, `reply`. A `reply` is the PO's answer on a story's
thread (see "Story threads"); only the `reply_story` tool writes it, and its
`stories` names that one story. A `question` blocks only the stories it lists. While a
question is open and nothing else can move, the runner keeps running and
waits for the answer. The runner itself posts an `update` at each sprint
end that pushed review branches (or built them without pushing; see
"Sprint boundaries"). A
`manual` acceptance environment's acceptance script arrives as a `question`;
the answer is the human's test result. A `document` environment posts
nothing. The runner itself posts `blocked`, `failed` or
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
`customer/<environment>/` (Customer Proxy sandboxes, one per acceptance
environment), `presentation/<story>/<environment>/`
(what the Integration Tester presents to the Customer Proxy, one dir per
acceptance environment the story's ACs name: see "Presentation"), `api-key` (default key location).

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

`tell` names its draft `.draft-<random token>`, so two posts from the
dashboard's threads at once never share a draft.

### Story threads

The human discusses a story with the PO or the liaison under its open
Backlog row (s84). A thread is not a store of its own: it is read from four
files, one per path. A text is stripped, must not be blank, and holds at
most 4000 characters. The story must be in `state.json` `stories` (a done
story is allowed). Every writer checks both.

| Path | Written by | File | Entry id |
|---|---|---|---|
| human → PO | `POST /api/thread` with `to: "product-owner"` | a `tell` file `liaison/messages/t<N>.md` whose first line is `<!-- thread story=<id> at=<time> -->`, then a blank line, then the text | `t<N>` |
| PO → human | the PO tool `reply_story(story, text)` | an `outbox.jsonl` message of kind `reply`, `stories: [<id>]` | `m<N>` |
| human → liaison | `POST /api/thread` with `to: "liaison"` | a line `{"story", "text", "at"}` in `liaison/inbox.jsonl` | `lp<N>` (line order) |
| liaison → human | `agile-team reply <story> <file\|->` | a line `{"story", "text", "at"}` in `liaison/replies.jsonl` | `lr<N>` (line order) |

A post to the PO is handed over like any `tell`, at the next router pass,
but its line names the story, and the pass's `stories` include it:

```text
The human wrote to you on s84's thread (t7): read .team/run/liaison/messages/t7.md. Answer there with reply_story; the reply shows under the story on the dashboard.
```

`reply_story` refuses an unknown story first, then an empty or over-long
text, and posts nothing then. Otherwise it answers
`{"status": "posted", "id": "m<N>"}`. `notify_user` with `kind: "reply"` is
refused (`use reply_story to answer on a story's thread`), so every `reply`
comes from `reply_story`. A `tell` file without the head belongs to no
thread. JSONL lines that are blank, torn or lack a str `story`, a str `text`
and a number `at` are skipped; only a last line can be torn, so earlier ids
never shift. The PO sees only the new post, not the thread before it.

### Liaison opinions

The liaison gives its opinion on stories, and the human reviews them in the
Backlog tab (s85). Like a thread, opinions are read from append-only files
in `liaison/`, each with one writer; nothing goes to `events.jsonl` or
`state.json`.

| File | Written by | Line | Id |
|---|---|---|---|
| `opinions.jsonl` | `agile-team opinion` | `{"story", "kind", "text", "at"}` | `o<N>` |
| `reviews.jsonl` | `agile-team reviewed` | `{"text", "at"}` | `v<N>` |
| `opinion-acts.jsonl` | `POST /api/opinion` | `{"opinion", "story", "act", "route", "ref", "at"}` | `a<N>` |

Ids count well-formed lines in line order; blank, torn or malformed lines
(a missing field, an unknown `kind` or `act`, a non-number `at`) are
skipped. The **latest** opinion on a story is its last line, whatever its
`at`. The last line of `reviews.jsonl` is the last review.

**Asking for a review.** `POST /api/review` appends a thread post to
`liaison/inbox.jsonl` with an empty `story`:

```text
Please review the backlog. Record an opinion on each story you would change with `agile-team opinion <story> <kind> -` (kinds: keep, move-up, move-down, fold, close, scope, ask), then a short summary with `agile-team reviewed -`.
```

So `watch` fires `liaison_message`, with that post under `posts`
(`"story": ""`). The snapshot's `opinions.asked_at` is the time of the
latest such post.

**Acting on an opinion.** The human dismisses or applies a latest,
non-`keep` opinion that has no act yet. The act is refused (409), in this
order: `no opinion 'o9'`, `o3 is no longer the latest opinion on s6;
reload`, `o3 is keep: there is nothing to dismiss or apply`, `o3 was
already applied` (or `dismissed`). An act is final: there is no undo, and a
new opinion on the story starts afresh. The server works out the route from
`state.json`, never from the page:

| Act | Route | What happens | `ref` |
|---|---|---|---|
| dismiss | `""` | nothing but the act line | `""` |
| apply `move-up` / `move-down` on a Backlog story | `reorder` | a reorder request (see "Reorder requests") to place 1 or the Backlog's last place, with the page's `version`; the router applies or refuses it between steps | `r<N>` |
| apply anything else (`fold`, `close`, `scope`, `ask`, or a move on a current-sprint story) | `product-owner` | a thread post to the PO on the story (see "Story threads"): `The human applied the liaison's opinion o3 on s6 from the dashboard: scope.`, a blank line, then the opinion's text | `t<N>` |

The PO treats an applied opinion as the human's request and answers with
`reply_story`. For a `close` the human still decides the cancel. An
applied move whose reorder is later refused still counts as applied; the
refusal shows in the snapshot's `reorders`.

### Watch

`watch` polls every 2 s. Each poll reads `outbox.jsonl`,
`liaison/inbox.jsonl` (leniently) and the shown status
(`status` and `status_reason`, with `interrupted` for a dead runner). A torn
outbox line counts as no poll. Triggers, in order:

| Trigger | Fires when |
|---|---|
| `message` | the outbox has entries after the ones already reported (all of them when the outbox got shorter); a PO `reply` fires it too |
| `liaison_message` | `liaison/inbox.jsonl` has thread posts to the liaison after the ones already reported (all of them when it got shorter) |
| `status` | the status is not plain `running` (`running` with no reason) and `(status, status_reason)` differs from the last one seen: halted, waiting on answers, budget, limit, interrupted, done, sprint end, idle |
| `health` | the live meter's health (see "Live meter and health") turned `red` since the last one seen |

When one fires, or at the first poll after `--timeout S` with nothing fired,
it prints one line and exits 0:

```json
{"triggers": ["message", "status"], "messages": [{"id": "m7", "kind": "blocked", "text": "…", "stories": [], "at": 1791800000.0}], "status": "blocked", "status_reason": "session limit, resets 9pm (Europe/Berlin)", "was": {"status": "running", "status_reason": null}}
```

The line also carries `"health": {"level", "reason"}` and `"posts"`: the
new thread posts to the liaison, each
`{"id": "lp3", "story", "author": "human", "to": "liaison", "text", "at"}`.
A timeout line has
`"triggers": ["heartbeat"]`, `"messages": []` and `"posts": []` (this watch
heartbeat is not `heartbeat.json`). `was` is
the status seen before. What was
reported is kept in `.team/run/liaison/watch.json`
(`{messages, status, status_reason, health, posts}`; `posts` is a count, and
a file from before s84 loads with 0), so nothing is lost between two
watches. The first watch in a repo (no `watch.json` yet) does not report the
history: it takes the outbox, posts, status and health as they stand as already
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
auth. It never serves files by path. Its writes: it queues a backlog
reorder request (s83), writes a post on a story's thread (s84), asks the
liaison for a backlog review, and dismisses or applies a liaison opinion
(s85). Each is accepted only from `127.0.0.1` or `::1` and
only with the token printed in the local URL
(`dashboard: http://localhost:<port>/?token=<t>`). The token is random at
each start unless `--token T` is given or the served repo's
`.agile-team.toml` sets `[dashboard] token` (presentation workspaces only;
the flag wins). It never appears in the
snapshot, the events or any log. The dashboard never writes `state.json`:
the runner applies the request between steps.

| Route | Returns |
|---|---|
| `GET /` | the dashboard page (`index.html`, packaged with the runner; vanilla JS, no build step). It loads `api/snapshot`, then follows `api/stream` and reconnects by itself. Its only outside resource is one pinned library from `cdn.jsdelivr.net`: `markdown-it@14.1.0` for every message body on the Activity and Questions tabs and in the live panel (raw HTML shown as text, http(s) links only, no images). If it can't load, the page shows plain text instead and the state row says `Markdown unavailable: showing plain text`. The Flow chart is the page's own HTML and needs nothing from outside. |
| `GET /fixtures/snapshot.json` | the packaged sample snapshot (`dashboard/fixtures/snapshot.json`) as JSON, no token, so `/?mock&at=end` replays it on a served dashboard (s112) |
| `GET /api/snapshot` | the snapshot as JSON |
| `GET /api/file?kind=K&id=I` | a story's file as `text/plain`. `K` is `story` (`.team/stories/`), `design` (`<docs>/design/`), `review` (`.team/reviews/`) or `acceptance` (`.team/acceptance/`). The file is `<folder>/<I>.md`, and `I` must be an opened story's id. Anything else is a 404. |
| `GET /api/misc?role=R&story=S&step=P&opened_at=T` | a step's or PO turn's `misc` calls (s101) as a JSON array: the `tools.jsonl` rows that the snapshot's `tools` gathering puts in that group's `misc`, re-gathered from the same tail under the current `[dashboard] collapse_under_s`, sorted by `at`, each as written (`[]` when none or when the tail has moved on). Each parameter is its first value or `""`; `story` and `step` `""` mean none. An empty `role`, or an `opened_at` that is not a finite number, is a 404. It is a read, so it needs no token. |
| `POST /api/reorder` | body `{"story", "position", "version"}`: `position` is the place in the Backlog group, and `version` is the snapshot's `run.order_version`. It needs the `X-Agile-Team-Token` header and a localhost peer, else 403. A bad body gets 400. Otherwise it writes `.team/run/reorders/r<N>.json` and answers 202 `{"id": "r<N>", "status": "queued"}`. The body may hold at most 4096 bytes. |
| `POST /api/thread` | body `{"story", "to", "text"}`: `to` is `product-owner` or `liaison`, `story` an opened story's id, and `text` 1 to 4000 characters once stripped. Checked in order: a localhost peer and the `X-Agile-Team-Token` header, else 403 (the body is not read); `Content-Length` from 1 to 32768, else 400; the body's shape, else 400; a known story, else 400. Otherwise it writes the post (see "Story threads") and answers 202 `{"id": "t<N>" or "lp<N>", "status": "posted"}`. |
| `POST /api/review` | body: any JSON object (its keys are ignored). Checked in order: a localhost peer and the token, else 403 (the body is not read); `Content-Length` from 1 to 4096 and a JSON object, else 400. Otherwise it posts the review request (see "Liaison opinions") and answers 202 `{"id": "lp<N>", "status": "asked"}`. |
| `POST /api/opinion` | body `{"opinion", "act", "version"}`: `opinion` an id `o<N>`, `act` `dismiss` or `apply`, `version` the snapshot's `run.order_version` (a string); extra keys are ignored. Checked in order: a localhost peer and the token, else 403 (the body is not read); `Content-Length` from 1 to 4096 and that shape, else 400; an act refusal, else 409 `{"status": "refused", "reason"}`. Otherwise it runs the route, records the act and answers 202 `{"id": "a<N>", "status": "dismissed" or "applied", "route", "ref"}` (see "Liaison opinions"). |
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
model, provider, with PO overrides applied, and from s104 `used`: true when
a step in the repo's pipeline routes to the role, where the generic
`developer` stands for the developers assigned to stories (or itself when
none is), or when the role has a `step-start` event), `stories` (in priority order;
state plus `opened_at`, `repeated`, the story file's `acceptance`,
`position`, `tier`, `hold`, from s53 `po_hold` (`{"kind", "reason",
"question"}` or `null`; see "PO story admin"), `wait`: `{"reason", "on",
"title"}` or `null`, and from s83 `disputes`, `developer`, `commits`, `files` (the
`/api/file` kinds that exist) and `label`: `cancelled`, `cancel requested`,
`held` or `""`;
from s86 `depends_on` (the state list), `waiting_on` (its ids that are not
done, in list order) and `dependency_warnings` (`s2 is above s5, which it
depends on` for each dependency the story is above in the queue); the last
two are `[]` for a done or cancelled story).
`reorders` lists the last 20 reorder requests with `status`
`pending`/`applied`/`refused` and `reason`. The **Backlog** tab lists
`run.order` in two groups, Current sprint (no handles) and Backlog (up,
down, top, drag). A click expands a row to show the story file, state,
file links, spend, recent events and open questions, then the story's
thread: each entry as `you → PO`, `PO → you`, `you → liaison` or
`liaison → you` with its time and Markdown text (`No messages yet.` when
there is none). With the token, a text box, a PO/liaison picker (PO by
default) and a send button follow; a draft and its cursor survive live
updates, and the entry shows with the next snapshot. Since s85 the tab
opens with the review bar (`Last review: <time>` and its summary, or `The
liaison has not reviewed the backlog yet.`; `Asked <time>; waiting for the
liaison.` while a request is newer than the last review; with the token,
an `Ask the liaison to review the backlog` button, disabled while waiting)
and an `only suggestions (N)` filter that keeps each row's full-group
place. A row whose latest opinion is not `keep` and has no act shows a
`liaison: <kind>` pill. Its expanded row shows the opinion's kind, time and
text above the thread and, once acted on, `dismissed`/`applied` with the
ref and the reorder's status; with the token, `dismiss` and `apply: …`
buttons (a reorder apply is disabled while a reorder is pending). Since
s86, in both groups, a row with dependencies shows `depends on s1, s5
(done)`, where ` (done)` marks each id not in `waiting_on`. Each
`dependency_warnings` text is a `⚠ <text>` warning pill. A `priority`
timeline entry with `warnings` appends ` · ⚠ <w1>; <w2>` to its meta and
takes the warning tone. The board keeps that order in every column and shows each
unfinished story's `#position`. A story that cannot move shows one pill,
`⏸ <wait.title>`. The first matching reason wins: `cancel requested` and
`PO hold` (s53; for these two the title is `<reason>: <PO's reason>`, e.g.
`⏸ PO hold: waits on s38`, so a PO-held story never reads `needs the
human`), then `questions`, `manager` (a repeated setback), `round cap`,
`needs the human` (blocked, or an open question names it) or `held` (any
other hold); for these the title is the reason alone. A done or cancelled
story has no `wait`. Below the pill is a `waits on: …` line with the open question
ids and texts, and the last step's summary or the repeated reason. Since
s53 the Backlog tab lists cancelled stories in a read-only **Cancelled**
group after Backlog, with their label pill and no move handles. The
timeline shows `escalation`, `fault`, `priority` and `story-admin` events
(`story-admin`: `<tool>: <PO hold kind or status after>`, the reason as its
body and the question id as its meta). The remaining
keys are `requirements` (from `<docs>/requirements/REQ-*.md`, with
`history` from `requirement-changed` events), `events` (`events.jsonl` plus
outbox and inbox entries as `message`/`answer` events, and every thread
entry as a `thread` event `{"id": "thread-<entry id>", "kind": "thread",
"story", "role": "product-owner" for the PO's reply else null, "data":
{"entry", "author", "to"}}` (`story` null for a review request), every
opinion as `{"id": "opinion-<oN>", "kind": "opinion", "role": null,
"story", "data": {"opinion", "kind"}}` and every act as `{"id":
"opinion-act-<aN>", "kind": "opinion-act", "role": null, "story", "data":
{"opinion", "act", "route", "ref"}}`, all in time order; an outbox `reply` is a
`thread` event only, never also a `message`), `opinions` (s85: `items`,
every opinion in line order, each `{"id", "story", "kind", "text", "at",
"latest", "route", "act"}`, where `route` is the route an apply would take
for a latest opinion with no act, else `""`, and `act` is `{"id", "act",
"route", "ref", "at"}` or null; `asked_at`, the last review request's time
or null; `review`, the last review `{"id", "text", "at"}` or null), `ledger`,
`steps` (s96: every agent step in start order, paired from `step-start` and
`step-end` by role and story, each `{"role", "story", "model", "sprint",
"at", "ended_at", "seconds", "status", "clock", "slept"}`; `at` is the
start; `seconds` is the awake time (s97): on macOS and Linux the step
events' `data.mono` span, on Windows the wall span less the heartbeat's
`data.slept` span; `clock` is `"awake"`, or `"wall"` for a step whose
events lack those readings (logged before s97, or straddling a reboot), timed
by wall clock and marked "may include sleep"; `slept` is the wall time
left out (`0.0` for a wall step; so far, for a running step); a running step
has `ended_at`, `seconds` and `status` null; a step closed after a kill has
`seconds`, `clock` and `slept` null; `model` falls back to the
role's configured model, then `"unknown"`; `sprint` is the sprint running
when it started), `messages`,
`answers`, `thread` (every thread entry in time order, each `{"id",
"story", "author", "to", "text", "at"}` with `author`/`to` one of
`human`, `product-owner`, `liaison`; the Activity tab shows it, filtered by
its story chip) and `upstream` (remote, branch, team branch, push permission, the
last end report, the pending boundary and the review stack: each sprint's
branch, base, PR number and URL, `mode` `none`/`draft`/`ready`/`closed`,
`check` `unchecked`/`pass`/`fail`; the Board tab shows it as the **Review
stack** card, and the Activity tab shows `boundary` events), `turns` (the
`turns.jsonl` lines of the last 10 minutes, at most 500), `heartbeat`
(`heartbeat.json` as written, or `null`) and `health` (`{"level", "reason",
"model_note"}`; see "Live meter and health"). The contract is
`runner/agile_team/dashboard/fixtures/snapshot.json`. The Tokens tab's role
and story tables show turns per step, the latest step's turns and context
per turn next to tokens and cost (see "Turns and context"). The Activity tab
shows each step-end's turns and each `po-session` renewal.

Watched and read files: `.team/run/{state.json, events.jsonl, ledger.jsonl,
outbox.jsonl, inbox.jsonl, heartbeat.json, turns.jsonl}` (only the last
256 KiB of `turns.jsonl`), `.team/run/liaison/{inbox.jsonl, replies.jsonl,
messages/t*.md}` (the threads), `.agile-team.toml`, `.team/stories/*.md` and
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
 "slept": 0.0, "chore": null,
 "step": {"role": "developer-cli", "story": "s29", "step": "implement", "started_at": 1791799500.0,
          "turn": 12, "model": "claude-sonnet-4-5-20250929", "configured_model": "sonnet",
          "last_turn_at": 1791800012.5, "quiet_since": 1791800012.5,
          "tool": {"name": "Bash", "started_at": 1791800013.0},
          "tokens": {"input": 30, "output": 5120, "cache_read": 912340, "cache_creation": 40100},
          "cost_usd": 0.4213},
 "calls": [{"role": "developer-cli", "story": "s29", "step": "implement", "opened_at": 1791799500.0,
            "tool": "Bash", "tool_use_id": "toolu_01…", "label": "Dev: run the unit tests",
            "detail": "uv run pytest -q tests/test_x.py", "at": 1791800013.0, "mono": 522993.0,
            "slept": 0.0, "status": "open"}]}
```

`beat` is `beating`, or `ended` once the runner has exited through Python
(done, halted, stopped, crashed). After a `kill -9` it stays `beating`
and goes stale. `at` is the last write (wall clock). `mono` is the
system's monotonic clock at the same moment. That clock stops while the
machine sleeps, so a reader can tell a sleep from a late beat. `slept`
(s97) is the sleep this runner process has counted so far: each beat gap
longer than two beats adds the gap less one beat. Windows' monotonic clock
counts through sleep, so this counter is how step times leave sleep out
there. Every `step-start` and `step-end` the runner writes carries
`data.mono` and `data.slept` read at that moment. Recovery's `killed`
step-end does not. `step` is the
innermost open query (a role step inside the PO's `run_role` call), else
`null`. `chore` is runner-side work such as `{"what": "settling
developer-cli on s29", "since": …}`, else `null`. Other chores are
`gate: implement on s29` while a gate runs, `sprint boundary: <stage>`,
`quality checks for s29`, `running named tests for <role> on s29`, and
`waiting for answers to m3` while the PO waits on the human. `quiet_since` is when
the query last had the floor back: its last turn, a tool's end, the end of
an inner query (a role step inside `run_role`), or the end of a chore.
`calls` (s101) lists the tool calls still open in **every** open query,
the outer one first (the PO's `po.run_role`), then the inner one (the
role's calls). Each row has the `tools.jsonl` keys up to `slept` (the
detail already masked) and `"status": "open"`. Once `beat` is `ended`,
`calls` is `[]`. The key is additive, so `version` stays 2.

**Expandable timeline rows (s101).** On a story's timeline, a step bar or
a PO-turn bar (or its row label, for all its bars) opens nested rows on
the same axis. A step bar takes the snapshot `tools` group with its role
and story whose `opened_at` falls in the step (never a `po-session`); a
PO-turn bar takes the PO group whose `opened_at` equals the `po-turn`
event's `data.opened_at`. Both add the heartbeat's open `calls` that
match. The rows are a `model` row (the bar's span less the union of its
calls; its total is `model_s` from the `step-end` or `po-turn` event,
else that measure), one lane per stacking level of calls (overlapping
calls take different lanes, touching ones share), and a `misc` box off
the axis when the group gathered any. A strip's look comes from its
status: `ok`, `error`, `timeout`, `unfinished` (hatched), `open` (ends
at now), or `waiting` for an ok or open `po.run_role`. Its name and
detail sit under it when they fit, else in its tooltip. Clicking the
misc box loads its calls once from `GET /api/misc`. A bar with no group
and no open calls shows one `no tool calls` row. In a replay, calls
after the cursor are dropped and a call still running at the cursor
shows as open; the misc list is the whole step's.

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

On the dashboard (since s112), the header's live panel takes the health
colour on its border. With a query open it reads `developer-cli · s29 ·
implement`, the awake time and the run (`first run`, `round N`, or
`↻ restarted` for a step that follows an interrupted one for the same role
and story), the newest open tool call, and up to 3 lines of the latest
message on the story. While the runner works between steps it shows the
open stage (the heartbeat's `stages`; each open row carries the stage's
`description` since s119, and that is the panel's second line) or chore.
With nothing running it reads `● Nothing running` and why: the
open question ids, else the health reason (for example the halt and its
reset time), else the run status. With no heartbeat (an old runner, or a
replay) an open `step-start` still shows as running. The state pill
(`live · stopped`) only names the connection and the run's status:
`stopped` is plain, because a graceful `agile-team stop` is neutral. The
red of `stop --now` and the other halts is on the panel. Hover over the
panel for the team's tokens per minute over the last 5 minutes, a
10-minute sparkline and the age of the last turn, then the step and turn,
the answering model (and `configured sonnet, answering opus` when they
differ), the step's tokens and estimated dollars, the current tool and how
long it has run, and the time of the last turn.

The Flow tab's chart is the page's own HTML, CSS and inline SVG (s118,
ADR-0052), drawn at real size: nothing scales it, and a window narrower
than the chart scrolls it sideways. The top row is You ↔ Liaison ↔ a boxed
Leadership group (the Product Owner and the manager, their boxes on one
row). Below, four boxed groups run left to right: Design (architect), Test
(devops, unit-tester), Dev (developer-api, -cli, -gui, developer) and Check
(quality-czar, code-reviewer, integration-tester, customer-proxy). Any
other role goes to the group of its pipeline step (snapshot `step_roles`),
or to Leadership. Groups are 236 px wide when there is room and shrink to
216 px; the arrows between them stretch with the window (at least 24 px),
each level with the first role box of the group it points into. One two-way path runs from Leadership down to each group.

The chart has a **Story / Sprint / Run** toggle, remembered per browser. It
defaults to Story: the active step's story, or another story picked in the
box beside it. Every number follows the scope. Each role box shows its
name; its model, ledger tokens and dollars, and awake time (finished steps,
sleep left out; the Product Owner's is its turns' model and tool time and
reads `—` in Story scope); `↩ N bounced`; a model/tool bar (dashed `no
model/tool timing yet` without data); and a tokens-per-minute sparkline of
its latest step (`rate` on `step-end` and `po-turn`), grey when idle. Only
used roles are drawn (`roles[].used`); the Product Owner always is. In
Story scope a role that has not touched the story is dimmed; in Sprint and
Run a role with no data is. Dimming recolours the box and never uses
opacity. A role with no data reads `idle`.

The running role's box and its group take the run colour: green on the
step's first run, violet on the first re-run, amber after that (earlier
`step-start`s of the same role, story and step whose run was not
interrupted). Its box shows the current tokens per minute with the
sparkline in that colour, and a live line: story, step, awake time, run
label and the latest tool call. Runner stages that prepare or gate a
role's step sit in small dashed boxes touching it, above when they run
before the step and below when after, on one centred line
(`label · ↻ runs · time`, s127); the checkout checks and during-step tools
are left out. The label is the stage's short label from the snapshot's
`stage_labels` (`stages.STAGES`, then each repo `[[tool]]` row's `label`
or name). The tooltip is `name — description` from `stage_descriptions`,
then `$ command` on a second line (the newest run's `detail`). The
Leadership group is as wide as its two role boxes and is centred over the
four groups. A role box's name and meta lines are centred. A running stage
is solid, outlined in its own run colour, and reads `▶ label · run label`
with its elapsed time. Under 2 points, an idle role's sparkline row reads
`last step · too short for a sparkline` when its step-end has a `rate`, and
`last step · no rate yet` when it has none (`rate` is tokens per minute over
10-second windows since s127). When it runs
pytest, the open stage row's `tests` (`passed`, `warned`, `skipped`,
`failed`, `total`, `points`, `fail_at`) gives the counts so far out of the
collected total. Pass is a passed test, Warn a test that recorded a
warning, Skip a skipped, xfailed or xpassed test, and Fail a failed or
erroring one. They are drawn as a bar, with a caption such as `273 Pass +
32 Warn + 4 Skip + 9 Fail / 506 Total` (zero categories left out), and a
`% complete` sparkline (reports received / total) that turns red at the
first failure. The counts come from the runner's pytest plugin
(`agile_team_tally`). Inside an open stage, `CommandShell` adds the plugin
to the command's `PYTHONPATH` and `PYTEST_PLUGINS` and names a scratch
file in `AGILE_TEAM_TALLY`. On the xdist controller (or the only process)
the plugin writes a JSON record there at most every 0.5 s, and the runner
reads it every 0.5 s. A new pytest session starts a new tally. If pytest
can't import the plugin, the command runs once more without it. An orange dot runs along the arrow when work moves into the next
group; a red dot runs down the PO path when a gate sends work back. A
redraw never cancels a dot; reduced motion lights the path instead. Times
read `6s`, `42.0m`, `1.4h`. **⚙ Show…** hides, separately and per
browser, tokens, cost, time, bounces, the bar, sparklines, runner tools,
tool counts and time, and the legend; the role name, model, the running
step and the running tool always show.

The Tokens tab's measure toggle is **Tokens / Dollars / Time** (one row
each in the page's `UNITS` table). Time draws "Time by" bars of summed step
time per role, story or model, in h and min, under the legend "Awake
time"; each tooltip gives the step count and the share of the total time,
and `N may include sleep` when the group has wall-clock steps. Only agent
steps count: the runner's
own stages (gates, syncs, presentation builds) are left to A6.

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

[toolchain.files]              # optional; the stop hook's lint check (s126). Unset keys come from the preset
fix = "uv run --directory {root} ruff check --fix --exit-zero --quiet {files} && uv run --directory {root} ruff format --quiet {files}"
lint_files = "uv run --directory {root} ruff check --quiet {files}"   # non-zero: the stop is refused
lintable = ["*.py"]            # which changed files are linted
# {root}: the [[toolchain.targeted]] root holding the files ("." without one); {files}: quoted, relative to it

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
stop_check_budget_s = 1800     # a step's total time in stop checks; after it the stop is allowed (s126)
steps = ["design", "tests", "implement", "quality", "review",
         "design-review", "e2e", "acceptance"]   # drop steps to skip them

[health]                       # optional; the live meter's thresholds in seconds (see Live meter and health)
beat_s = 20                    # heartbeat.json rewrite interval; must be below stale_s
stale_s = 90                   # heartbeat older than this: red (amber while a tool or chore runs, awake); also the sleep threshold
amber_tool_s = 180             # no turn this long while a tool runs: amber
amber_quiet_s = 300            # no turn this long, no tool: amber
red_quiet_s = 600              # no turn this long: red

[dashboard]                    # optional; presentation workspaces only, never a real team repo
token = "presentation"         # fixed write token when `dashboard` has no --token; unset: random each start

[upstream]                     # optional; these are the defaults (see Sprint boundaries)
remote = "origin"              # "" turns sync and pull requests off
branch = "main"                # merged in at sprint start; what the bottom PR targets
prefix = "team/sprint-"        # review branch names: <prefix><sprint>

[[environment]]                # one or more acceptance environments
name = "cli"
kind = "package"               # package | script | web | library | harness | manual | document
prepare = "uv venv {sandbox}/venv && uv pip install --python {sandbox}/venv {repo}"
bin = ["venv/bin"]             # prepended to the Proxy's PATH
e2e = ""                       # this environment's e2e suite, run with the full checks at sprint boundaries
url = ""                       # web only; its host and port fill {host} and {port}
probe = ""                     # web only: path joined to url that must answer 200 (e.g. "api/snapshot")
commands = []                  # harness only: the Proxy's Bash allowlist
# prepare placeholders: {repo}, {sandbox} (absolute paths), {host}, {port} (from url)

[[tool]]                       # optional, DevOps-owned (s99); a format only: nothing runs it yet
name = "deploy.preview"        # lowercase letters, digits, - _ + and dots; not a built-in name or namespace
description = "Deploy the branch to the preview site"
command = "make preview"
label = "preview deploy"       # optional (s127): the Flow chart's ≤ 24-character label; else the name

[roles.integration-tester]
enabled = false                # disable a role
[roles.developer]
model = "opus"                 # override any frontmatter field
[roles.developer-embedded]
extends = "developer"          # add a role without a file
[roles.quality-czar]
provider = "local"             # run on a [providers.*] endpoint (see Providers)
model = "qwen3-coder"          # that provider's model name

[providers.local]              # any name but "anthropic", which is built in
base_url = "http://localhost:11434"
kind = "anthropic"             # the only kind so far; see Providers
token_env = ""                 # env var holding its token; empty sends a placeholder
billing = "free"               # free (ledgered as 0) | reported (Claude-priced)
```

### Acceptance environments

An acceptance environment is the setup the Customer Proxy uses to try a
story: an `[[environment]]` row in `.agile-team.toml`.

**Environments are the repo's; kinds are the skill's** (s93). A repo
configures as many environments as it needs, each with its own `name`,
`prepare`, `url`, `commands` and so on. Each environment names one `kind`
from the skill's fixed set (`sandbox.ENVIRONMENT_KINDS`, see "Acceptance
environment kinds"). The kind decides the Proxy's tools and sandbox, so a
repo can't add one: the set is the security boundary.

Each acceptance criterion names its environment in the story file (s94; see
"Story files"). The name must equal a configured `[[environment]]` `name`
exactly (no prose, no case folding); `open_story` refuses any other name and
lists the valid ones. A story's environments are the distinct names of its
ACs, in config order. Each is presented and tried on its own (s95, see
"Acceptance per environment").

### Acceptance per environment

Acceptance is a **round** of Customer Proxy steps, one per environment the
story's ACs name, one after another in config order (s95, ADR-0051).

- **Which environment.** The round's verdicts so far are `StoryState.tried`
  (one per environment). A Proxy step tries the first environment in config
  order with no verdict yet. Its sandbox is prepared from that environment
  alone, with that environment's presentation copied in, and its prompt
  gains `## Criteria for this step: acceptance environment <name>`, listing
  only that environment's ACs with their ids.
- **The report.** One report, `.team/acceptance/<id>.md`, with one
  `## Environment: <name>` section per environment. Each step rewrites its
  own section and keeps the others. A step whose handoff comes back without
  its section bounces to `acceptance` with a round (`the report … has no
  section `## Environment: <name>`; …`) and records nothing.
- **Failed ACs.** On any failure the Proxy hands off `changes_requested`
  with `"failed_acs": ["AC2", …]` and `next_role`. `failed_acs` must be a
  list of ids and needs `changes_requested`.
- **Between environments** the gate's verdict is `next`: the story stays at
  acceptance, no round is counted, the PO is not woken, and the router runs
  the next Proxy step. Its brief has no "Previous step" line. Every
  environment runs, even after one fails.
- **One verdict.** After the last environment: every environment passed →
  `pass`. Otherwise one `bounce` (one round) with
  `acceptance failed in <n> of <total> environments:` and one line per
  failed environment, `- <name>: <ids or "no AC named">: <summary>`, to the
  earliest pipeline step the failed steps' `next_role`s name (else
  `implement`).
- **A new round** starts whenever the story moves into acceptance (after
  e2e, rework, a return or an `advance` ruling): `tried` is cleared, so
  every environment runs again. A `blocked` or `failed` Proxy handoff holds
  the story and records nothing; after `continue_story` the same environment
  runs.
- **Events and snapshot.** A Proxy step's `gate` event adds `environment`,
  `mark` (`pass`/`fail`) and `failed_acs`. The snapshot's story row adds
  `environments: [{name, verdict}]` (`verdict` `pass`, `fail` or `""`);
  the Board and Backlog show one pill per environment.

**The old section name** (s93). Before s93 the section had another name.
A file that still uses it loads exactly as `[[environment]]`; `config check`
prints `warning: [[<old>]] is the old name of [[environment]]; rename the
section` and still exits 0 when nothing else is wrong. A file with both
sections fails to load: `[[environment]] and [[<old>]] are both set; move
every [[<old>]] into [[environment]]`. `init --reconfigure` rewrites an old
file as `[[environment]]`, and a DevOps edit that only renames the section is
kept. Since s94, `state.json` keeps no environment for a story: a story's
`environment` key, or its old-name key, is dropped on load, and the next save
writes neither. A runner from before s93 can't read state saved after it.

### Repo tools

`[[tool]]` rows (s99) name a repo's own tools: `name`, `description` and
`command`, each a non-empty string after strip, and an optional `label`
(s127: the Flow chart's short label; blank or missing means the name).
Loading refuses the whole
file (`config check`, `start`, `tools` exit 1) when any row breaks a rule,
listing every problem `; `-joined, in rule order, then repeats:

| Rule | Message |
|---|---|
| name matches `[a-z0-9][a-z0-9_+-]*(\.[a-z0-9][a-z0-9_+-]*)*` | `[[tool]] 'Deploy' name must be lowercase letters, digits, -, _, + and dots` |
| not a built-in stage name, and not in a built-in namespace (`env`, `presentation`, `quality`, `checkout`, `gate`, `boundary`, `runner-tool`, `po`) | `[[tool]] 'gate.mine' clashes with a built-in name; pick another` |
| description not blank | `[[tool]] 'x' needs a description` |
| command not blank | `[[tool]] 'x' needs a command` |
| label at most 24 characters after strip | `[[tool]] 'x' label must be at most 24 characters` |
| name not repeated | `[[tool]] name 'x' is repeated` |
| label (or the name, without one) not repeated, and not a built-in stage's label | `[[tool]] label 'x' is repeated` |

DevOps owns `[[tool]]` as it owns `[toolchain]` and `[[environment]]`: a role's
config edit touching only those sections is kept, any other is quarantined.
In s99 the rows are a format only: the runner runs no `[[tool]]` command, and
an agent's Bash call is never matched to one by its text.

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

**ADRs belong to the Architect (s114).** At design, the Architect writes
`.team/adr/NNNN-<slug>.md` (context, decision, consequences) for each
decision it makes, numbered after the highest one there, and amends the
existing ADR when a decision changes. Its built-in write scope is
`["{docs}", ".team/adr/**"]`; a repo that overrides `[roles.architect]
write` must list `.team/adr/**` itself. There is no Scribe and no per-role
brief file: every role reads the story, design, ADRs and code first-hand.

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
global addendum → repo addendum → `.team/CLAUDE.md` → file scope. Nothing
else is added: a `.team/briefs/` directory, if one is left over, is never
read (s114). Each step's own brief is the message the runner or the PO sends.

**Retired roles (s114).** The Scribe is gone. A `[roles.scribe]` section in
`.agile-team.toml`, or a global or repo `scribe.md` with frontmatter or with
text outside comments, stops every command that loads it with:

```
the Scribe was retired in s114: the architect writes ADRs in .team/adr/ and roles get no briefs; remove [roles.scribe] from .agile-team.toml
the Scribe was retired in s114: the architect writes ADRs in .team/adr/ and roles get no briefs; delete <path>
```

A scaffolded `scribe.md` stub (comments only) is ignored, so delete it at
leisure.

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

Which roles suit a local model: Code Quality Czar; Unit and
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
`tests` with its code in (see "Back at tests with the code in"). A role on
a gate fix step may add `"asserts": "<AC or design rule>"` when its fix
changes what a test asserts (see "Gate fix steps"); a non-string `asserts`
is a malformed handoff. The Customer Proxy adds `"failed_acs": ["AC2", …]`
with status `changes_requested` when criteria fail (s95, see "Acceptance per
environment"); a non-list, an empty id, or ids with another status is a
malformed handoff. The Manager adds `"ruling"` (`rescope`,
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
for a `web` environment, a service that starts from it and answers its probe)
→ acceptance (customer-proxy).

A failed gate or `changes_requested` moves the story back and adds a round
(a test dispute is the exception: see "Test disputes"; a failure in a file
another role owns is routed to that role without a round: see "Gate fix
steps"; the same setback twice in a row escalates instead: see "Repeated
setbacks"). At
`round_cap` the runner refuses every role but the Manager on that story.
`blocked` and `failed` do not count a round. When `e2e` is enabled,
`run_role(customer-proxy)` on a story with no complete presentation does not
start the Proxy. The runner moves the story back to `e2e` **without** a round
(gate event `verdict: "return"`) and reports `{"status": "returned", …}`. The
same happens when a `web` environment's service does not come up for the Proxy
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

### Stop checks (s126)

Every role step (and gate fix step) has an SDK `Stop` hook beside its
`PreToolUse` guard. When the agent tries to end its step, the runner checks
the work first, inside the same conversation:

| Role | Its stop checks, in order |
|---|---|
| every role | `handoff`: the handoff block parses (for example, no "asserts must be a string"); `lint`: the toolchain's fixers run on the step's changed, in-scope, lintable files (python: `ruff check --fix`, `ruff format`), then the file linter on them |
| developer-* (at `implement`) | `suite`: the implement gate itself, the full suite with coverage |
| unit-tester (at `tests`) | `red`: the tests gate itself (new tests fail; dispute and rework rules as at the gate) |
| integration-tester (at `e2e`, with `acceptance` enabled) | `presentation`: every environment's presentation is complete (`PRESENTATION.md` exists and is not empty) |

- Checks run only on a `done` handoff. Any other status (`changes_requested`
  with or without a `dispute`, `blocked`, `failed`) ends the step at once, with
  no checks, and is routed as before. A role may escalate on its first turn.
- Only failures the role can fix are refused: files in its write scope, and
  for the suite, the tests the gate would leave at this step. A failure only in
  another role's file lets the stop through, and the gate routes it as a gate
  fix.
- A refusal is the failures, shortest first (failing tests as their ids, the
  coverage rows only when coverage failed). It ends with: "fix these, or hand
  off `changes_requested` with a `dispute` naming the test and why".
- After 3 refusals in a step, or once `[gates] stop_check_budget_s` is spent,
  the stop is allowed and the gate decides as before. A check whose command
  timed out does not refuse.
- The lint fixes are committed with the step. After a passing `suite` stop,
  the implement gate reuses that run when the content is unchanged (its reason
  ends "(the stop hook's run on this tree)").
- Each refused check writes a `stop-check` event (`check`, `stage`, `attempt`,
  `of`, `seconds`, `text`). The checks are runner stages `stop.handoff`,
  `stop.lint`, `stop.suite`, `stop.red` and `stop.presentation`, and their
  open row and event carry `attempt: {n, of}`. On the Flow chart they are the
  role's after tool boxes: `label · ↻ runs · time · n refused`, and
  `▶ label · attempt n of 3` while running.

### Runner stages (s99)

The work the runner does itself (gates, quality checks, checkout checks,
environment preparation, presentation lay-out and trial, boundary stages,
runner tools) is a table of named stages, `stages.STAGES`. Run
`agile-team tools` for the list; this page does not repeat it. Each row has
a `name` (`<namespace>.<stage>`, e.g. `gate.tests+coverage`), a `label`
(s127: what it runs in at most 24 characters, unique, e.g.
`pytest + coverage`; the Flow chart shows it), a `description`, `when` and
`attach`:

- `when`: `before` (runs before the step it attaches to, or before a
  sprint), `after` (after the step, or closing a sprint), or `during` (a
  runner tool working inside an agent step at the agent's request).
- `attach`: `step`, `story` (the PO's `pass_tests` green check) or
  `boundary`.

The code that decides to do the work opens the stage by name; nothing infers
a stage from command text, and an unlisted name fails. The places that run
commands (the gate shell, git, the `gh` runner, the sandbox's prepare and
service start) only note each command and its exit code into the stage that
is open. A command run with no stage open (a git query between steps) is
recorded nowhere.

Each stage run, whether it returns or raises, writes one `runner-stage` event
to `events.jsonl`, however many commands it ran:

```json
{"kind": "runner-stage", "role": "runner", "story": "s99",
 "data": {"stage": "gate.tests+coverage", "when": "after", "attach": "step",
          "step": "implement", "detail": "uv run pytest --cov -q", "code": 0,
          "raised": null, "started_at": 1760313600.0, "started_mono": 5321.4,
          "started_slept": 0.0, "seconds": 41.253},
 "at": 1760313641.3, "id": "e812"}
```

- `story` and `data.step`: the step the runner is running when the stage
  runs (set for the whole step, from its request), or the story of a
  `pass_tests` check; both `null` elsewhere (router tick, PO turn, boundary).
  `when` and `attach` are the table row's.
- `detail`: the first command that exited non-zero, else the last command
  noted; masked like a tool call's detail (secrets `***`, whitespace
  collapsed, at most 80 characters); `""` when none ran.
- `code`: that command's exit code; with no command, `0` when the stage
  returned and `null` when it raised. A service that never answered is code
  `1`; a missing binary is `127`; a command killed at its limit is `124`.
- `raised`: the exception's class name when the stage raised (it still
  propagates), else `null`.
- `started_at`, `started_mono`, `started_slept`: the wall clock, monotonic
  clock and heartbeat sleep counter at the start; `seconds` is the awake time
  (POSIX: monotonic span; Windows: wall less counted sleep), 3 decimals.
- A runner tool writes both its `tests-run` event and a `runner-stage` event.
  A failed write of the line never stops the run. A killed runner writes no
  event for the stage it was in.
- The Timeline tab does not draw `runner-stage` events yet.

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
`bounce`, `return`, `hold` or `route` (s92; it stays at its step, so the
backstop does not count it), including a gated role's malformed handoff
(which now logs a `gate` event like any bounce). Passes, test disputes and
`next` (between acceptance environments, s95) are not setbacks. For each setback the runner records, on the story's
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

### Gate fix steps (s92)

When the **implement** gate fails in a file another role owns, the runner
sends that item to the owner instead of bouncing the developer. No other
gate routes.

- **Owners.** The owner of a file is the pipeline role whose write globs
  (the same globs the guard enforces) match it: the step's own role first,
  then the first role in pipeline order. `developer` means the story's
  named developer. Nothing else says who owns a file.
- **Items.** The gate reads failing tests from the coverage run's summary
  (pytest `FAILED`/`ERROR` lines, jest `FAIL` lines) and lint findings
  from each configured `lint` and `static` command that fails (ruff,
  flake8, mypy, eslint `path:line:` lines, ruff's `-->` lines,
  `Would reformat:`). Findings for the same path and source make one item,
  with at most 40 output lines. Its printed path is matched against
  `git ls-files` (the exact path, else every tracked path ending
  `/<path>`). If all matches have one owner, that role owns the item.
  Otherwise the item stays with the step's role. A timed-out run is not
  routed.
- **Kept at implement.** A failing test in a unit-test file stays with the
  developer (the unit-tester's red tests are the developer's to make
  green). A lint finding counts only in a file the story touched (`files`,
  every path a step committed on the story). Lint never fails the gate by
  itself: a lint item the developer owns is left to the quality step.
- **Verdict.** With no foreign items, the gate verdict is unchanged. With
  foreign items it is **`route`**: the story stays at `implement`, counts
  no round, and its `fixes` queue holds one fix step per owner, in
  pipeline order. The reason is `routed to <role> (<files>); …; the story
  comes back to this step after their fix steps`. If the developer also
  has its own failing test (or the failure is a coverage shortfall with no
  test item), the verdict stays `bounce` with a round, and the reason adds
  `also routed to <role> (<files>); their fix steps run first`. The gate
  event carries `fixes` (`[{role, files}]`). Every gate result replaces
  the queue. A ruling, a fault or `pass_tests` empties it.
- **Dispute on a foreign test.** A developer's dispute on a test another
  role owns (e.g. an e2e test) opens no dispute. It is a `route` to the
  test's owner, and the fix brief cites the dispute's rule and reason. A
  dispute on a unit test works as in "Test disputes".
- **Fix step.** The router runs the head of the queue first, as a step of
  kind `gate-fix` for that role, with the role's own scope and none of its
  set-ups (no presentation lay-out), but with git confinement. Its brief
  starts `Gate fix on story sN: the implement gate failed on files you
  own…` and lists only that role's items and their output lines. A
  `run_role` for a gate fix is refused unless the role is the head fix's.
- **Settling a fix step.** `done` pops the head and runs no gate; after the
  last fix step the developer runs again, with `Other roles fix items in
  their files first, then this step runs again: <reason>` in its brief.
  `changes_requested` bounces the story to `implement` with a round
  (`<role> says the failure is not theirs to fix: <summary>`). `blocked`
  or `failed` holds the story and hands over (`stopped`); a malformed
  handoff is settled as `failed`. A bounce or hold empties the queue.
- **Repeats.** The same `route` twice in a row escalates to the Manager
  (see "Repeated setbacks").
- **Assertions (`asserts`).** Each settled fix step adds a record to the
  story's `fixed` (role, files, commit, `asserts`, whether the commit's
  diff changed assertion lines) and logs a `gate-fix` event
  (`{status, files, commit, asserts, assertions_changed, left}`, `left`
  the roles still queued). The code-reviewer's brief lists each record:
  `Gate fix by <role> (commit <sha>) on <files>: <note>`. A fix that
  changed assertion lines without naming a rule is flagged there, not
  refused; the reviewer judges it.

## Presentation

The Integration Tester presents each story to the Customer Proxy; the Proxy
never builds or repairs an environment (a broken one is `changes_requested`
to `integration-tester`).

- **One presentation per acceptance environment** (s95). Before each
  integration-tester step the runner creates, for every environment the
  story's ACs name, `.team/run/presentation/<story>/<environment>/` if it is
  missing and, for every environment kind but `manual`, `workspace/` in it
  as a git repo (`git init`, only when `workspace/.git` is missing), with
  that environment's seeds. It never wipes them (s65): the presentations
  survive a bounce from acceptance back to e2e, and only the tester
  replaces what is in them. The tester's prompt gains
  `## Presentations to build`, one line per environment:
  `- <name> (<kind>): .team/run/presentation/<story>/<name>/ (<AC ids>)`.
  Each guide covers only that environment's ACs. A story from before s95
  with one flat presentation goes back to e2e once, without a round.
- **Git stays in the workspace** (s65). The integration-tester (step `e2e`)
  and the Customer Proxy (step `acceptance`) are *confined*, per the
  `dispatch.GIT_CONFINED` table. Their workspace is the story's
  presentation dir `.team/run/presentation/<story>/` for the tester (so git
  reaches every environment's `workspace/`; s95), and the Proxy's copy
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
- For a `document` environment (s93) nothing runs: the tester copies the
  files the story changed (prompts, docs, designs) into `workspace/` under
  their repo paths, and the guide says for each AC which file and section
  shows it.
- Complete = in every environment's dir, `PRESENTATION.md` is not blank
  and, except for `manual`, `workspace/` holds something besides `.git` and
  the seed files: the demo or evidence files themselves. Otherwise the e2e
  gate bounces (one round) with one line per incomplete environment (s95,
  s91), each
  `story sN has no presentation for acceptance environment '<name>': <gap>`,
  where `<gap>` is the first of:
  `<dir>/PRESENTATION.md is missing or empty; write the customer's guide there`,
  `<dir>/workspace is missing; put the demo or evidence files the customer tries there`,
  `<dir>/workspace is empty; …`, or
  `<dir>/workspace holds only .git; add the demo or evidence files themselves, for example <dir>/workspace/DEMO.md`
  (seed files present are listed after `.git`).
- **Up and answering** (s26). Each kind's row in `presentation.PRESENTATIONS`
  says whether its check is `files` or `service`; only `web` is `service`.
  For a service, once the files are complete, the e2e gate runs a trial
  for each `web` environment in config order, one at a time, and the first
  that fails decides; a `manual` or other files-only environment never
  starts anything. Each trial
  prepares the sandbox exactly as for the Proxy (presentation copied in),
  starts the environment's `prepare` in the background, and probes
  `url` + `probe` every 0.25 s for up to 30 s. It passes (`presentation
  ready; <url> answered`) only on HTTP 200 (and, for a JSON response, a
  body that parses), then stops the service. A start that exits or never
  answers bounces to `e2e` with a round:
  `story sN presentation is not up: acceptance environment '<name>' did not start: the start command exited with code <rc> before <url> answered. Last output: …`
  (or `… did not answer <url> within 30s. …`), quoting the last 20 lines of
  its output. A port that another process holds puts the gate on **hold**
  (no round, the PO gets a `gate_hold` hand-over):
  `acceptance environment '<name>' cannot start: <host>:<port> is already in use by a process the runner did not start; stop it or change the environment's url`.
- For the Proxy step the runner copies the step's environment's dir (only
  that one) to `<sandbox>/presentation/`
  (symlinks kept as links) **before** the environment's `prepare` runs, so a
  `web` prepare can serve `{sandbox}/presentation/workspace`. A `web`
  service is started and probed the same way before the Proxy starts. The
  Proxy's prompt quotes `PRESENTATION.md` and gives the copy's absolute
  path.
- A service is never reused. Its process group id is in
  `.team/run/customer/<environment>.pid` and its output is in `<environment>.log`
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
  Then the stop waits up to 5 s for the environment's port to refuse
  connections. It never waits more than 20 s, and it never signals a leader
  that had already exited before the stop. If the port is still in use at the
  deadline, the trial puts the gate on **hold**:
  `story sN presentation did not stop: acceptance environment '<name>' did not let go of <host>:<port>: it was still in use 5s after the service was stopped; keep the service in its start command's process group`.
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
3. the next step of the movable story that comes first in the **priority
   ranking** (see "Story priority"). A movable story is in the current sprint,
   `active` and not held, no open question blocks it, and every story in its
   `depends_on` is done (s86, at every step, not only the first; see "Story
   dependencies"). A story that is not
   movable keeps its place in the order and is skipped until it is released.
   Step 2 also takes the escalated story that comes first in the ranking.
   When that story has gate fix steps queued, its next step is the head
   fix step (s92; see "Gate fix steps").

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
| `gate_hold` | the gate put a `done` step on hold for an environment reason (e.g. a `web` environment's port is in use by another process), or a story file that went bad before a Proxy step (s94, "Story files"); `continue_story` once it is fixed |
| `bad_handoff` | the `manager` gave no valid handoff |
| `questions` | the handoff has `open_questions` |
| `quarantine` | the step's out-of-scope changes were quarantined |
| `round_cap` | the story reached the round cap (not an `escalate` verdict) |
| `unroutable` | a bounce names a `next_role` that owns no pipeline step |
| `ruling_not_applied` | the Manager ruled but the ruling could not apply (see "Rulings") |
| `runner_fault` | the Manager put a setback on the runner; the story is blocked and the human was told |
| `off_pipeline_fault` | the Manager put a setback on a role with no pipeline step; brief it, then `continue_story` |
| `fault_not_applied` | the Manager's `fault` was not applied (missing, unknown role, no story or a done story); the reason is in the line |
| `sync_conflict` | rebasing the team branch onto upstream at sprint end (the `rebase` stage) conflicts (the stopping commit and its files, grouped by directory with a count; the rebase was aborted and the branch is unchanged) |
| `push_permission` | the review branches are built and checked, and the human has not yet said whether the team may push |
| `push_rejected` | a review branch push was refused (its remote branch moved), at the `push` or `restack` stage; the stage stays and `continue_boundary` reruns it |
| `boundary_error` | a boundary stage raised an error (traceback in `crash.log`) |
| `boundary_escalated` | the same boundary failure repeated after a fix and the Manager reviewed it |
| `ci_green` | the review PR's CI checks all passed; the line says it is **ready to merge**, and the PO tells the human. This is the only text that calls a PR ready; see the CI rule under **Ready.** |
| `ci_failed` | the review PR's CI failed; the line names each failing check (workflow / job), its link and its failing test lines. The PO opens a bug story at once, records it with `record_ci_bug`, tells the human the PR is **NOT** ready, and lists the story first in the next sprint. Only when the lines show the failed job never ran our code may the PO ask for a re-run and `continue_boundary` instead; see the CI rule under **Ready.** |
| `ci_pending` | the CI checks were still running at `[gates] ci_timeout_s`; the line names them. The PR is NOT ready; `continue_boundary` waits again; see the CI rule under **Ready.** |

The runner also hands over `human_message` (the inbox has answers the PO has
not seen, listed by id with the question, or `tell` messages it has not
been handed, each as a path to read; see "Liaison messages"), `sprint_end` (every story
in the sprint is done and the sprint's end boundary has finished; a
`Review: …` line says what was pushed) and `stalled` (nothing can move; the
reason for each story is listed, or the held boundary). A story's reason is
its hold first (`held (…)`), then its undone dependencies in list order
(`s2 at design: waiting on s1`), then its status. Gate bounces, `changes_requested` to a pipeline role, a
gated role's malformed handoff and `returned` do **not** hand over. The
runner passes their reasons on in the next standard brief. An `escalate`
verdict does not hand over either: the runner runs the Manager on the
story.

- A story named in a hand-over is **held** (`hold` in `status`): the router
  skips it until the PO calls `continue_story(story, note)` or runs a step on
  it with `run_role`. A done story never moves again; `continue_story`
  clears its hold too (for example after `ruling_not_applied`). No step runs
  after done: the Architect records a story's decisions as ADRs while it
  designs (s114).
- PO tools added: `continue_story(story, note)` releases a held story (done
  or not) and adds `note` to its next brief. It refuses a `blocked` story,
  with or without a hold, because releasing it would leave the sprint
  stalled (s45). Run the manager on that story with a ruling or a fault
  instead. `set_developer(story, role)` picks the
  developer for that story; it refuses an unknown role or one that is not a
  developer. `pass_tests(story, reason)` (s30) moves a story stuck at
  `tests` on when the suite is green (see "Test disputes").
  `reply_story(story, text)` (s84) answers the human on a story's thread
  (see "Story threads"). `hold_story`, `release_story` and `request_cancel`
  (s53) hold, release and ask to cancel a story; see "PO story admin".
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
  `null`), `interrupted` (saved work from an interrupted step, offered to
  the next step; see "Interrupted steps"), `depends_on` (the validated
  copy of the story file's list, s86; see "Story dependencies"), `files`
  (every path a step committed on the story), `fixes` (the queued gate fix
  steps: role, items, cited rule) and `fixed` (the settled ones, s92; see
  "Gate fix steps"); run-level `order` (the PO's
  story order; see "Story priority"), `delivered` (answer ids the
  PO has seen), `goal` (the current sprint's goal), `boundary` and
  `upstream` (see "Sprint boundaries"). Older files load with these empty. On the first run after
  the upgrade, every answer already in the inbox counts as seen. An older
  file's `scribe_due` list, and any PO model override for `scribe`, are
  dropped on load and gone at the next save (s114).

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

- `open_story` puts a story in the backlog. The PO writes the story file
  first. `open_story` refuses an existing id, then a story file with problems
  (see "Story files"), and changes nothing when it refuses. It has no
  `environment` argument. Its `depends_on` argument (s86) is checked next; see
  "Story dependencies".
- `start_sprint(goal, stories)` is the only way into a sprint. It opens sprint
  `N+1` with exactly the listed stories. Unfinished stories it does not list
  go back to the backlog. Done stories never move; they keep the sprint they
  finished in. It refuses an empty list or unknown ids (`unknown stories: s7;
  open them with open_story first`) and changes nothing when it refuses.
  Once those checks pass, it reloads every open story's `depends_on` from
  its file and is refused if the files are bad (see "Story dependencies").
- The `sprint-start` event carries `{"sprint", "goal", "stories"}`, plus
  `"reason"` when one was given.
- `run_role` on a backlog story is refused: `story sN is in the backlog; add
  it to a sprint`. The status refusals (done, blocked, round cap) come first.
  `manager` and story-less steps are not affected.
- A story is in at most one sprint. To carry it over, list it in the next
  `start_sprint`, which queues the Manager again.
- `add_to_sprint(stories, reason)` (s122) adds open stories to the running
  sprint. The sprint keeps its number, goal and review branch. No boundary
  runs, and no Manager turn or PO renewal is queued. The listed ids go first in
  the order, in the order given, as `prioritise` places them. It never pulls,
  so started stories still come first, and the change is logged as a
  `priority` event (`change: "sprint"`) with the reason. It emits one
  `sprint-add` event `{"sprint", "stories", "reason"}`. It is refused, with
  nothing changed, in this order: a pending boundary; no open sprint (none
  started, or the end boundary has closed it); an empty list or unknown, done
  or cancelled ids; a story already in the sprint (`already in sprint N:
  …`); a `depends_on` that is neither done nor in the sprint after the add
  (`depends_on not done and not in the sprint: s5 on s3; …`); a blank
  reason. Its stories show on the Board and in the sprint's review PR like
  the ones the sprint started with.
- While the current sprint has unfinished stories, `start_sprint` needs a
  `reason` (`sprint N still has unfinished stories (…); use add_to_sprint to
  add work, or give a reason for starting a new sprint`). The reason is added
  to the `sprint-start` event as `"reason"`.
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

## PO story admin: hold, release, cancel (s53)

Three PO tools, each taking `story` and `reason`, park, release and ask
to cancel a story. A **PO hold** is its own field on the story,
`po_hold: {"kind", "reason", "question"}` (`kind` is `PO hold` or `cancel
requested`; `question` is the cancel question's id, else `null`). It is
not the hand-over `hold`: `continue_story` clears `hold` but never
`po_hold`. Old `state.json` without the key loads `po_hold: null`.

- `hold_story(story, reason)` sets a `PO hold` with the stripped reason.
  It posts no question. Holding a held story again replaces the reason.
  The router skips a PO-held story (story steps and Manager steps), but its rank, tier, `order` and `pulled` entries stay as they
  are, so it keeps its board position. Use it instead of an `ask_user`
  nobody should answer.
- `release_story(story, reason)` clears `po_hold` and `hold`, sets the
  status to `active` and puts the reason in the next step's brief (as
  `pass_tests` does). The step is unchanged. It works on a PO-held story
  or a `blocked` story with no open question.
- `request_cancel(story, reason)` posts one question naming the story:
  `Cancel story sN ("<title>")? The PO asks because: <reason> Answer
  "cancel" to cancel it or "keep" to keep it.` It sets a `cancel requested`
  hold with that question's id. The status is unchanged.

**Only the human's answer cancels.** Each answered cancel request is
settled at the start of every router tick (right after reorders apply), in
`wait_for_answers` after it polls, and before each of the three tools
checks anything. The answer is stripped of spaces and `.!"'` and read case
blind:

| Answer | Effect |
|---|---|
| `cancel` | status `cancelled`; the id leaves `order`, `pulled` and `human_order`; `sprint`, `po_hold` and `hold` become `null`. The story file, its commits, `code_commits` and events are kept |
| `keep` | `po_hold` becomes `null`; the story carries on with its status unchanged |
| anything else | a `PO hold` with reason `the answer to mN was neither "cancel" nor "keep": <answer>`; the PO releases it or asks again (the question is used up) |

The answer still reaches the PO as a normal `human_message`. No tool can
set `cancelled`. A cancelled story is **finished**, like a done one: it
leaves the queue, the plan and the sprint, `start_sprint` skips it,
`prioritise`/`move_story` refuse it (`cancelled stories can't be ordered:
sN`), `run_role` refuses it (`was cancelled by the human`), and so do
rulings and faults. That holds after a resume. Known limits: a story that
`depends_on` a cancelled story keeps waiting (edit its frontmatter), and
the timeline folds only `done` stories.

**Refusals**, in order, the first wins; a refusal changes, saves and emits
nothing:

| Tool | Refused when (text) |
|---|---|
| all | unknown story (`unknown story 'sN'; open it with open_story`); blank reason (`a reason is required`); done or cancelled (`story sN is done; there is nothing to hold`, with `release` or `cancel`) |
| `hold_story` | a cancel request is pending (`story sN already waits on the human's answer to mN about cancelling it; answer mN instead`) |
| `release_story` | an open question names the story (`story sN has an open question; answer m3, m7 instead`); the story waits on the Manager (`… run the manager on it`); no PO hold and not blocked (`… nothing to release (continue_story releases a hand-over hold)`) |
| `request_cancel` | a cancel request is pending (as for `hold_story`); the story has commits (or `code_commits`) and the reason contains neither `code` nor `commit` (`story sN has commits (N); say in the reason what happens to its code (kept, reverted by a new story, …)`) |

A success returns `{"status": "held" | "released" | "cancel requested",
"story", "step", "story_status", "question"}`, saves the state once and
writes one `story-admin` event. From a tool: role `product-owner`, data
`{"tool", "reason", "question", "before", "after"}`. From a settled
answer: role `null`, data `{"tool": "answer", "reason", "question",
"answer", "decision", "before", "after"}` (`decision` is `cancel`, `keep`
or `unclear`). `before` and `after` are `{"status", "step", "sprint",
"hold", "po_hold"}`. The story's `label` is `cancelled`, then `cancel
requested`, then `held` (any PO hold or held tier), else `""`.

## Story files

A story's file `.team/stories/<id>.md` is the only record of its acceptance
criteria and their acceptance environments (s94). It starts with YAML
frontmatter:

```yaml
---
id: s120
title: "Export the board as CSV"
depends_on: [s83]          # optional (see "Story dependencies")
acceptance:
  - id: AC1
    text: "agile-team export --csv prints one row per story."
    environment: cli
  - id: AC2
    text: "The Backlog tab has an Export button that downloads the same CSV."
    environment: dashboard
---
```

Other top-level keys and other keys inside an AC are ignored. The body after
the frontmatter is free text (user story, notes).

**Checks, in order.** Checks 1–3 stop the read. Checks 4–6 are story-level and
all are reported; a failed 6 stops before the items. Then every problem of
every item is reported, in file order.

| # | Check | Problem text |
|---|---|---|
| 1 | the file exists and is readable | `no story file; write it before open_story` |
| 2 | it starts with frontmatter | `no YAML frontmatter; start the file with --- and the keys id, title and acceptance` |
| 3 | the frontmatter parses and is a mapping | `frontmatter does not parse: <error>` |
| 4 | `id` equals the file's story id | `id is 's12', not 's120'` |
| 5 | `title` is a non-empty string | `title must be a non-empty string` |
| 6 | `acceptance` is a non-empty list | `acceptance must be a non-empty list of {id, text, environment}` |
| 7a | the item is a mapping | `must be a mapping with id, text and environment` |
| 7b | its `id` is a non-empty string | `id is missing or empty` |
| 7c | its `id` is not used by an earlier item | `id is used by an earlier AC` |
| 7d | its `text` is non-empty | `text is missing or empty` |
| 7e | its `environment` is a non-empty string | `environment is missing; use one of: cli, dashboard, review` |
| 7f | it names a configured `[[environment]]` | `environment 'web' is not a configured [[environment]]; use one of: cli, dashboard, review` |
| 7g | (no `[[environment]]` configured) | `environment 'cli' cannot be checked: .agile-team.toml configures no [[environment]]; ask the human to add one` |

An item without a usable id reports only 7a or 7b. **The refusal** is one line
per problem, joined by newlines: `{file}: {where}{problem}`, where `{file}` is
repo-relative (`.team/stories/s120.md`) and `{where}` is `AC <id>: `, or
`item <n>: ` (1-based) for an item with no usable id, or empty for a
story-level problem. One read lists everything to fix.

**When the runner reads it.**

| When | On problems |
|---|---|
| `open_story`, after the duplicate-id check and before `depends_on` | the tool returns the refusal; the story is not opened |
| before every Customer Proxy step on the story (after the PO's turn, before the unpresented check) | the step does not run and nothing is billed; the gate holds the story with `the story file must be fixed before acceptance:` + the refusal + `Edit the file; no state change is needed`, which the PO gets as a `gate_hold` hand-over |

A clean file is used as it is, so an edit since `open_story` takes effect at
the next Proxy step. **Fixing an environment is an edit to the file**: no tool
and no state change. A held story goes on with `continue_story`, and the next
Proxy request reads the file again. The hold counts as a setback like any gate
hold, so the same unfixed hold repeated can escalate.

**State and snapshot.** `state.json` keeps no environment for a story. The
snapshot's story `environment` (a string) is the story's environments joined
by `", "` in config order (`"cli, dashboard"`), or `""` when the file has
problems.

**Every environment is tried** (s95). A story whose ACs name two environments
is presented and tried in both; see "Acceptance per environment".

## Story dependencies

A story that needs others done first lists them (s86) in its file's YAML
frontmatter as a block list. A comment can give the reason:

```yaml
depends_on:
  - s31  # hooks
  - s36
```

A missing key means `[]`, and a duplicate id is dropped (the first one is
kept). The PO writes the list. Never write "Depends on sN" in a story's
prose. `state.json` keeps a validated copy per story (`depends_on`). The
router, the `priority` events and the snapshot read only that copy.

**Load points.** The copy is reloaded from the files only at these points:

| When | What loads | On a refusal |
|---|---|---|
| `agile-team start` (every mode), before the PO or router runs | every story that is not done and has a file | the command fails with `story files: <refusal>; fix depends_on in .team/stories` and the run does not start |
| `start_sprint`, after its other refusals pass, before the sprint opens | the same | the tool returns the refusal and the sprint does not begin |
| `open_story` | the new story only, from its `depends_on` argument | the tool returns the refusal and the story is not opened |

For the loaded stories, the file's list wins. A story with no file keeps the
list it had in state, and a done story is never reloaded. A refusal changes
no story's list and saves nothing. A file edited mid-sprint is not read
until the next start or `start_sprint`.

**Validation.** The loaded lists replace those stories' lists in the graph
of every story in state, and the whole graph is checked. The first
refusal wins:

| # | Check | Refusal |
|---|---|---|
| a | the frontmatter does not parse, or `depends_on` is not a list of strings (`depends_on: s1`, `depends_on: null` and a bare `depends_on:` all count) | `depends_on must be a list of story ids: s3, s9` |
| b | a story lists itself | `a story cannot depend on itself: s4` |
| c | a listed id is not a story in state (done stories are known, and a done dependency is satisfied) | `depends_on names unknown stories: s2 on s77, s5 on s78; open them with open_story first` |
| d | the graph has a cycle | `depends_on has a cycle: s1 -> s2 -> s3 -> s1` |

Ids are in natural order (`s9` before `s10`). The cycle is the first one
found by a depth-first walk from each id in natural order, following each
list in its own order. A story file that is not valid UTF-8 is not refused:
reading it raises an error.

`open_story(…, depends_on=[…])` checks, after the duplicate-id and story file
checks: the argument is a list of strings (a missing or empty argument means
`[]`); if the story's file already exists, its frontmatter is good and its
list is the same, in the same order (`s7's file has depends_on [s1, s2], not
[s2]; pass the same list, or fix the file`); then checks b–d, with the new id
counted as known. The `story-opened` event's data gains `"depends_on"`.

**Routing.** A story whose dependencies are not all done is not movable
(see "Routing"). `run_role` by the PO is not checked. A started story whose
list gains an undone dependency stops too. A dependency outside the sprint,
or on a cancelled story, waits until the PO changes the sprint or the file.

**Moves are never refused for dependencies.** Every `priority` event (from
the PO's tools, `start_sprint` or a dashboard reorder) has `warnings`: one
`s2 is above s5, which it depends on` for each story the change newly put
above one of its dependencies in the queue, in queue order. When there are
none, it is `[]`.

## Story priority

Started stories are finished before new ones are started (s51). A story is
**started** when it has commits in the tree: the runner recorded its first
commit (`commit` in `state.json`). A step that committed nothing does not
start a story. Every unfinished story is in one **group**:

| Group (`tier`) | Stories |
|---|---|
| `in progress` | started (or pulled, below) and not held |
| `held` | started (or pulled) and held: a `hold`, `blocked` or `needs_manager` (a PO hold, s53, does not count, so a PO-held story keeps its group) |
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
- `add_to_sprint(stories, reason)` puts the added stories first, in the
  order listed, like `prioritise`. It never pulls (`change: "sprint"`, the
  PO's reason).

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
"from", "to"}], "reason": "...", "pulled": [...], "warnings": [...]}`.
`order` is the queue after the change. `moves` lists only the stories whose
position changed. `pulled` lists the stories this change pulled ahead.
`warnings` (s86) lists the dependency inversions the change caused (see
"Story dependencies"). `story_status` returns
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

1. **sync**: fetch, record the team branch, and count how far
   `<remote>/<branch>` moved past it (`git rev-list --count
   HEAD..<remote>/<branch>`). It logs `pass` with `behind` and the note
   `the team branch is current with <remote>/<branch>` or `<remote>/<branch>
   moved N commits since the last sprint-end rebase; nothing changes until
   the next sprint end`. It **changes nothing** (s108): no rebase, reset,
   merge or checkout, no hash rewritten, no stack entry dropped, pushed or
   retargeted, and no `gh` call. A moved main, or a PR merged mid-sprint,
   waits for the next sprint end (or a pull the human makes by hand).
2. **check**: the full checks on the team branch (skipped when HEAD is the
   sha that last passed them). The start boundary then finishes; review,
   push, rebase, restack and ci run only at a sprint end.

**End** (opened when every sprint story is done, before the `sprint_end`
hand-over). The stages run in this order:

1. **sync**: fetch, record the team branch, and add this sprint's entry:
   branch `<prefix><N>`, range `start..end` (start = the previous entry's
   end, or `git merge-base HEAD <remote>/<branch>` for the first one).
2. **check**: the full checks on the team branch.
3. **review**: in the scratch worktree `.team/run/review/`, the sprint's
   own entry's commits (`start..end`, no merges, only those whose patch is
   not in main) are cherry-picked onto the branch below (the latest main
   for the bottom). This uses `rerere` and skips picks that come out empty.
   The branch is then set. An entry with nothing left is in main and drops
   out. The bottom and the newest branch get the full checks. Parent
   entries keep their heads; after a refused restack (below) every entry is
   rebuilt from main.
4. **push** (needs `gh` and permission): the sprint's own review branch is
   pushed with `--force-with-lease` against the sha the runner last pushed.
   No PR is created or edited here. An empty stack, no `gh` or no
   permission moves on (a `local` event with the reason).
5. **rebase**: fetch, then rebase the team branch onto `<remote>/<branch>`
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
   quoted in reviews and stories are not rewritten. After `rebased` or
   `current`, `boundary.sync_from` is cleared. The rebased team branch is
   checked at the next start's **check**.
6. **restack**: bring every review PR up to date, bottom up.
   - **Merged parents.** When the boundary delivers (`gh` and permission),
     the runner looks up the leading stack entries, bottom first, stopping
     at the first that is not merged: an entry counts as merged when its
     branch's PR has the same number and is `MERGED`. Each is dropped
     (`merged` event) after a fresh fetch.
   - **Fast rebase, all or nothing.** In the review worktree every
     remaining entry is rebased, bottom first and the sprint's own entry
     last: the first onto main (from the old head of the last dropped entry,
     or from its merge-base with main), each other one onto the new head of
     the entry below. Each rebase must stop cleanly and keep its tree
     (`new^{tree}` equals the old head's). No branch ref moves until all
     pass. The tree stays the same exactly when main gained only merged
     stack PRs.
   - **Apply.** Bottom first, an entry with no commits left is dropped
     (`merged` event; its content is in main, e.g. a squash or local
     merge). Each other entry's branch is set to its new head (`checked`
     follows it when it was the old head). A `restacked` event names the
     branches whose head moved. Then each entry is pushed with
     `--force-with-lease` against the sha last pushed, and its PR is
     created or updated: **every PR is ready**, the bottom based on `main`
     and each other one on the branch below, so a PR whose parent was
     dropped is retargeted here. A closed PR is left alone. The runner posts
     an `update` to the human with the PRs. That update never calls a PR
     ready. Without `gh` or permission, nothing is pushed, the human gets
     the local report, and the boundary finishes.
   - **Refused** (a rebase stopped, or a tree changed because main gained
     other commits): a `rebuild` event with the reason, `restack` is set,
     and the boundary goes back to **review**, which rebuilds every entry
     from the rebased team branch and checks the ends. Push and rebase then
     run again (the team branch is `current`), and restack runs on the
     rebuilt branches. Nothing changed is pushed unchecked.
   - A refused push at **push** or **restack** holds `push_rejected` and
     the stage stays; nothing after it is pushed, and `continue_boundary`
     reruns it (heads already moved rebase as no-ops).
7. **ci** (s81): for each ready PR in the stack (every PR, s108) the runner runs
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
   `checks`, `results`). The verdict is green only when every watched PR
   is green; one PR with no checks makes it **none**. An empty stack
   (every sprint is in main) finishes with that note and no watch. No
   merge is followed at this stage: a PR merged during the wait is handled
   at the next sprint end. Verdicts:
   - **green** (every check passed or was skipped, at least one passed):
     the boundary finishes. The PO gets `ci_green` ("ready to merge") and
     tells the human.
   - **red** (any check failed or was cancelled, even with others still
     pending): the boundary is held `ci_failed`. The PO gets the failing
     checks with job names and test lines, opens a bug story at once,
     calls `record_ci_bug(story)` and tells the human the PR is NOT ready.
     `continue_boundary` waits for the checks again, for when the human
     re-ran them. Only green or a recorded bug story finishes the
     boundary. A re-run is only for a job that never ran our code; see
     the CI rule under **Ready.**
   - **pending** (the deadline passed): held `ci_pending`, naming the
     running checks. The PR is not ready; `continue_boundary` waits again.
   - **none** (no checks reported, only skipped ones, or no open PR):
     the boundary finishes. The human is told that no CI result exists, and
     the PR is not called ready.

   The CI stage blocks the router while it waits, as a runner chore
   (`sprint boundary: ci`), so health stays green. If the run is stopped
   during the wait, resume waits again. The sprint-end hand-over then says
   `Review: …` with the CI text.

**Full checks**: the `[toolchain]` `lint`, `static`, `test` and `coverage`
commands (coverage must reach the gate or the baseline), then each
acceptance environment's `e2e` command. Every configured check runs, and the failed ones
are quoted (`<name> failed (<why>): <command>` plus the last 30 lines).

**Failures.** A failed check or a rebuild conflict becomes a **DevOps fix
step**, whose brief quotes the output. Failed checks on the team branch or
a review branch are fixed on the team branch. For that step DevOps may also
write source, tests and e2e tests, and the runner commits it and checks or
rebuilds again. A conflict is resolved in the review worktree, in exactly
the conflicting files, and recorded with `git rerere`, so later rebuilds
reuse it. A fix step that hands over (blocked, questions…) holds the
boundary `fix_handover`. Its triggers go to the PO like any step's, and
`continue_boundary` reruns the stage. A fix that raises no trigger leaves
the boundary unheld, and the stage reruns. A stored `boundary.hold` that is
not a known hold is dropped when `state.json` loads, so `watch`, `status`
and a resume still work. The dropped value is kept in `load_faults` until
`start` reports it as one `fault` event (`"fault": "state"`, naming the
field and the value). Each failure is a setback keyed `<edge>><stage> <normalised
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

**CI rule.** A sprint is done only when a green CI run is actually present
on GitHub. A re-run counts only when it is green, and only when the failed
job never ran our code (it was cancelled with no steps run, or no runner
was available). If a failure could be flakiness in our code, it is a bug
story, and the sprint is not done. The PO role file states it too (s110):
on `ci_failed` the PO reads the failing lines first and asks for a re-run
only when they show `no runner was assigned` or a cancel whose steps never
started; otherwise it opens the bug story and `record_ci_bug`s it. The
runner does not check this rule: `continue_boundary` at a `ci_failed` hold
is not refused, and a re-run that turns green finishes the boundary green.

`state.json` `upstream`: `team_branch`, `push` (`unasked`/`yes`/`no`),
`stack` (per entry: `sprint`, `branch`, `start`, `end`, `title`, `stories`,
`head`, `checked`, `check`, `pushed`, `pr`, `url`, `base`, `mode`, `ci`,
`commits`: the PR's commit count against its base, set at each push),
`last_end`, `checked` (the last team sha that passed), `closed` (the last
sprint whose end boundary finished), `report` and `ci_bug` (the bug story
for a failed CI, until a sprint lists it first).

CI: every PR in the stack is ready (s108; `mode` `draft` survives only in
an old `state.json`), so every PR runs CI and every one is watched. Once
`ci_green` says the stack is ready, merge the bottom PR with **Rebase and
merge**; the next sprint end drops it and brings the PR above it up to date
on main. GitHub refuses **Rebase and merge** for a PR of more than 100
commits, so the push, green and none reports add one line per such PR:
`PR #<n> (<branch>) has <count> commits, more than the 100 GitHub allows for
"Rebase and merge". When it is the bottom of the stack, merge it by
fast-forward: git fetch <remote> && git push <remote>
<remote>/<branch>:<target>`.

Boundary outcomes of s108: `restacked` (good; `branches` moved), `rebuild`
(warning; the refused restack's reason), `merged` (a parent PR merged or an
emptied entry dropped). `pushed` is still read from old `events.jsonl`
lines but no longer logged. Stage names in `runner-stage` events:
`boundary.sync`, `boundary.check`, `boundary.review`, `boundary.push`,
`boundary.rebase`, `boundary.restack`, `boundary.ci-wait`.

## Enforcement

- Stop hook (s126): a `done` handoff ends the step only after the role's stop
  checks pass, or after 3 refusals, or once the stop-check budget is spent.
  See "Stop checks (s126)".
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
- A change to `.agile-team.toml` outside `[toolchain]`, `[[environment]]`
  (or its old name) and `[[tool]]` is quarantined, so no role can widen its own scope for the next run.
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
  source or test glob does. An acceptance environment that serves locally (a kind whose start
  is `background`, today `web`) also gets `sandbox.network.allowLocalBinding:
  true`, so the Proxy's sandboxed `curl` reaches the service on 127.0.0.1;
  other kinds get no `network` key (s58). Needs bubblewrap (Linux) or Seatbelt
  (macOS). On macOS, an e2e test runs the bundled claude CLI with these
  settings. A sandboxed `curl` gets 200 from a live local service, and it
  exits 7 without the `network` key. Linux is not verified end to end; the
  test is skipped there.

## Acceptance environment kinds

The kinds are the skill's, fixed in `sandbox.ENVIRONMENT_KINDS`; a repo's
`[[environment]]` rows pick one each (see "Acceptance environments").

| kind | prepare | Proxy tools |
|---|---|---|
| `package` | build and install into `{sandbox}` | Bash, Read/Grep/Glob, Write; cwd = sandbox |
| `script` | copy scripts and samples into `{sandbox}` | same as package |
| `web` | start the server in the background (it can serve `{sandbox}/presentation/workspace`); the step waits until `url` + `probe` answers 200; stopped after the step | Playwright MCP, Bash limited to `curl`, Read, Write |
| `library` | build the package; Proxy works in `{sandbox}/consumer` | Bash, Read/Grep/Glob, Write/Edit |
| `harness` | anything DevOps defines | Bash limited to `commands`, Read, Write |
| `manual` | nothing | Read, Write; its acceptance script goes to the human as a question |
| `document` (s93) | nothing; for ACs with nothing to run (prompt, docs or design changes). Its presentation is a guide plus the changed files (`files` check, no service); no `url`, `commands` or seed | Read/Grep/Glob over its copy of the presentation, Write (the report only), no Bash; nothing is posted to the human |

When the story has a presentation, every kind gets its copy in
`{sandbox}/presentation/` before `prepare` runs. Every kind except `manual` has a `workspace/` in it.
