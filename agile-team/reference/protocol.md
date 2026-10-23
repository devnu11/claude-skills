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
| `requirements check` | Parse and check every `<docs>/requirements/REQ-*.md` (s1). Print one JSON object: `problems` (one `{file}: {problem}` line each: a broken file, a `covers` ref to an unknown story or AC, a duplicate id), `coverage` (every story file that reads clean, in id order: each AC id → the active requirements covering it, `[]` when none) and `unreadable` (other story files → their problems). Exit 1 when `problems` is non-empty, else 0. Untraced ACs are not problems. See "Requirements". |
| `requirements log` | Print the requirement change history as one JSON list, read from the `Requirement-Changed` git trailers of the commits that touched `<docs>/requirements/` (s2): `[{"id", "reason", "sha", "date"}]`, oldest commit first, `date` the author date in ISO 8601. `[]` when there are none. Exit 0; a git error exits 1. See "Requirements". |
| `roles list` | JSON: each role's layers (built-in, global, repo: `replace`, `addendum` or `stub`) and its resolved model, provider, effort and write scope. |
| `roles scaffold [--global]` | Write a commented stub for `_shared` and every enabled role that has no file yet, in `.team/roles/` (default) or the global dir. Never overwrites. |
| `start --task T \| --task-file F [--cadence C] [--onboard] [--resume]` | Preflight, then run the team in the foreground (the liaison backgrounds it): the runner drives the pipeline and calls the PO for judgement (see "Routing"). `--task-file` reads the task from a file, or stdin for `-`; giving both is refused. With `--resume`, the task is optional and reaches the PO as "New from the human", and the run keeps its stored cadence unless `--cadence` is given. Exit codes: see "Run status and stops". |
| `status` | JSON: run `status` and `status_reason` (why the runner stopped, what a waiting run waits on, or `null`), current `sprint`, stories with their pipeline step, `sprint` (`null` = backlog) and routing fields (`hold`, `developer`, `previous`; see "Routing"), open questions, spend, the pending sprint `boundary` (or `null`), `upstream` (the sprint's PR; see "Sprint boundaries"), `checkout` (the branch and HEAD the runner expects, or `null`; see "Checkout guard"), `queued_messages` (ids of `tell` messages the PO has not been handed yet, e.g. `["t3"]`), `queued_shares` (ids of `share` requests the runner has not applied yet), `shares` (each settled share id → `applied <commit>`, `unchanged` or `refused: <why>`), `queued_stories` (ids of `story` requests the runner has not settled yet, e.g. `["q2"]`) and `story_requests` (each settled story request id → `opened <id> <sha12>; <placed>`, `amended <id> <sha12>` or `refused: <why>`; see "Stories from the liaison"), `queued_picks` (ids of pick requests the runner has not received yet, e.g. `["p1"]`), `pending_picks` (ids of pick requests waiting on the PO's `accept_pick` or `deny_pick`) and `picks` (each received pick id → `{status, sprint, shas, why, revert}`, `status` one of `pending`, `accepted`, `denied`, `applied`, `refused`, `conflict`, `failed`, `reverted`; see "Picks (mid-sprint)"). |
| `tools` | JSON `{"built_in": [...], "repo": [...]}` (s99): `built_in` is the runner's stage table in order, each `{"name", "label", "description", "when", "attach"}`; `repo` is the config's `[[tool]]` rows in file order, each `{"name", "description", "command", "label"}` (`label` since s127, `""` when not given). Exit 1 with the `[[tool]]` refusal when the config is broken. See "Runner stages". |
| `answer ID TEXT` or `answer ID --file F` | Answer PO question `ID`, with `TEXT` or the text of file `F` (`-` reads stdin); exactly one of the two. |
| `tell SOURCE` | Queue a message for the PO. `SOURCE` is a file, or `-` for stdin; the text never goes on a command line. Stored as `.team/run/liaison/messages/t<N>.md`; prints `queued t<N> for the PO: <path>`. Works in any run state (running, waiting, halted, stopped). Exit 1 on an empty text (`the message is empty`) or an unreadable file. See "Liaison messages". |
| `share SOURCE --story ID` | The liaison shares a file (a mock, a spec) with the team for story `ID` (s120). Queues `.team/run/liaison/shares/f<N>.json` (the name, the bytes and their SHA-256) and prints `queued f<N>: <docs>/design/<ID>-<name> (sha256 <12 hex>); the runner commits it between steps`. Writes nothing else. Works in any run state, and a stopped run applies it on the next `start`. Checked in order, first refusal wins and nothing is written (exit 1): a bad id or no `.team/stories/<ID>.md` (`no story 's9'…`), a name that is not letters, digits, `.`, `_`, `-` (≤ 100, no stdin), an unreadable file, an empty file, a file over 5 MiB. See "Shared files". |
| `pick SPEC --reason TEXT [--force]` | Ask for a pick onto the team branch mid-sprint (s141). `SPEC` is one commit (a sha or ref) or a range `A..B`, already in the local repo: the runner never fetches. The command queues `.team/run/picks/p<N>.json` (the full shas and subjects, oldest first, the reason, and the kind) and prints `queued p<N>: <count> commit(s) for the PO to accept or deny: <sha12> "<subject>"; …`. The PO decides with `accept_pick` or `deny_pick`. With `--force` (the human only) the command needs an interactive terminal: it prints the commits, their subjects and the team branch, and asks you to type the first commit's sha12. A forced pick skips the PO and prints `queued p<N> (forced): …`. Every check runs, and on any refusal every reason is printed and nothing is queued (exit 1): a blank reason, a spec that is not a commit or `A..B`, a commit not in the local repo, an empty range, a merge or root commit, or a commit already on the team branch or whose change is. `--force` is also refused with no TTY or a wrong sha. It never changes the tree or a branch, works in any run state, and a stopped run handles the queue on the next `start`. See "Picks (mid-sprint)". |
| `story new FILE --approved-by human\|none [--sprint current\|next\|backlog] [--after ID] [--plan PATH]` | The liaison writes a story (s135). `FILE` is a Markdown draft: frontmatter `title`, `acceptance: [{id, text, environment}]`, optional `depends_on` and other keys (kept as written), no `id` or `shared`, and the user story as the body. Every check runs and every problem is printed, one line each (exit 1, nothing queued). A clean draft is queued as `.team/run/liaison/stories/q<N>.json` and the command prints `queued q<N>: new story "<title>" (<approved>); the runner gives it an id and commits it between steps`. `--sprint` defaults to `backlog`; `--plan` needs `--approved-by human`. Never writes `.team/stories/` or calls git; works in any run state. See "Stories from the liaison". |
| `story amend ID FILE --approved-by human\|none [--plan PATH]` | The liaison replaces open story `ID`'s ACs (s135). The draft is checked as for `new`, and its `title` and `depends_on` must equal the story's (only the ACs change) and its ACs must differ. Queues `q<N>.json` and prints `queued q<N>: new ACs for <ID> (<approved>); the runner commits them between steps and sends <ID> back to design; the draft's body is not used`. `--sprint` and `--after` are refused. See "Stories from the liaison". |
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
no key file exists, the key file is inside the repo and not gitignored, or a
key file is not mode 600 (a `key_file` outside the repo, absolute or `~/…`,
needs no gitignore); with `auth = "login"`, `ANTHROPIC_API_KEY` is set in the environment; a toolchain
command's executable is missing; `config check` fails.

## Relay files (`.team/run/`, always gitignored)

`outbox.jsonl`, one JSON object per line, written by the PO:

```json
{"id": "m3", "kind": "question", "text": "…", "stories": ["s2"], "at": 1730000000.0}
```

`kind` is one of `question`, `update`, `sprint-end`, `blocked`, `done`,
`failed`, `stopped`, `reply`, `story-request`. A `reply` is the PO's answer on a story's
thread (see "Story threads"); only the `reply_story` tool writes it, and its
`stories` names that one story. A `story-request` is the PO asking the
liaison to write a story; only the `request_story` tool writes it (see
"Stories from the liaison"). A `question` blocks only the stories it lists. While a
question is open and nothing else can move, the runner keeps running and
waits for the answer. The runner itself posts an `update` at each sprint
end push, red CI and finish (or when it checked the branch without
pushing; see "Sprint boundaries"). A
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
stale one is ignored and the next `start` overwrites it), `stop`,
`repin.json` (a self re-pin in progress, see "Self re-pin"), `runner-pin/`,
`runner-pin.commit`, `runner-pin.prev/`, `runner-pin.prev.commit` and
`runner-pin.failed/` (self-hosting only), `crash.log` (append-only tracebacks of every error the
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
| `running` | runner | The run is going (steps, lands and PO turns). Every `start` sets it, which clears any stop below. Since s159 a run that waits on the human stays `running`, with `status_reason` saying why (see "Waiting and limits"). |
| `sprint-end`, `done` | PO (`notify_user`) | The sprint or the whole task finished. |
| `blocked` | runner | Spend reached `team.budget_usd`. Since s159 nothing else sets it: `notify_user(kind="blocked")`, the stuck Sprint Backlog cap and the until-blocker next-sprint cap post their note and leave the run `running`, waiting (see "Waiting and limits"). |
| `limit` | runner | A session or usage limit was hit (s159). `status_reason` holds the reset text. |
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
| 75 | a session or usage limit, in the PO or in a role step; the run exits once no step is running (s159) | `limit` (the liaison note kind stays `blocked`) | ``run `agile-team start --resume` after the reset`` |
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

**Story worktrees** (s159). With story branches on, the main checkout moves
only by a landing's fast-forward and by the runner's story-admin commits
(intake, share, revert record, the PO's settle); both record the checkout.
Each story's worktree has its own record (`branch`, `worktree_head`), checked
before every step on that story. Drift there halts nothing: the step does not
start, `drift` lists the changed files (`git status --porcelain`), the story
holds, and the PO gets `worktree_drift` naming the worktree and the files.
Only that story waits. `agile-team accept-checkout --story <id>` keeps the
worktree as it is. It is allowed while the runner runs: it only queues
`.team/run/checkouts/c<N>.json`, and between steps the runner records the
worktree's HEAD, clears `drift` and the hold, and logs a `checkout` event
(`{action: "accepted", story}`). `accept-checkout` without `--story` is
unchanged and still refuses while the runner runs.

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

**Story steps keep their worktree** (s159). The saving above is for
storyless steps only (the run's `in_flight`). A step on a story runs in the
story's worktree and is recorded in the story's own `in_flight` (role,
story, brief and the session id, taken from the SDK's first message). When
it is cut off (a crash, `stop --now`, a usage limit), nothing is committed
or reverted: the worktree keeps the edits. `start --resume` logs the step's
`step-end` (`{status: "stopped", interrupted: <cause>}`) unless it has one,
keeps the session for that role (see "Kept sessions"), sets the story's
`interrupted` so the next brief says `<role>'s step was cut off (<cause>);
its uncommitted edits are still in this worktree`, and clears `in_flight`.
It then removes every worktree whose story has nothing in flight, the land
and replay worktrees unless a boundary replay is pinned, and runs `git
worktree prune`. A removed worktree is rebuilt from its branch at the
story's next step.

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
current sprint, `order_version`: a 12-hex digest of both, `runner_pin`: the
pinned runner's full sha or `""`, shown in the header as `pin <sha7>`), `pipeline`
(enabled steps), `roles` (name,
model, provider, with PO overrides applied, and from s104 `used`: true when
a step in the repo's pipeline routes to the role, where the generic
`developer` stands for the developers assigned to stories (or itself when
none is), or when the role has a `step-start` event), `stories` (in priority order;
state plus `opened_at`, `repeated`, the story file's `acceptance`,
`position`, `tier`, `hold`, from s53 `po_hold` (`{"kind", "reason",
"question"}` or `null`; see "PO story admin"), `wait`: `{"reason", "on",
"title"}` or `null`, from s159 `branch` (the story branch, `""` before
one), `landed` (the landing merge's sha once the story is done, else
`null`) and `story_ci` (`{"sha", "verdict", "source", "checks"}` of the latest
story-PR or landing CI, or `null`), which the Board card shows, and from s83 `disputes`, `developer`, `commits`, `files` (the
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
`⏸ <wait.reason>`, with `wait.title` as its tooltip (s150). The first
matching reason wins: `cancel requested`, `revert requested` and `PO hold`
(s53; for these the title is `<reason>: <PO's reason>`, e.g. `PO hold:
waits on s38`, so a PO-held story never reads `needs the human`), then
`questions`, `manager` (a repeated setback), `round cap`, `needs the human`
(blocked, or an open question names it) or `held` (any other hold); for
these the title is the reason alone. A done or cancelled story has no
`wait`. The card's `waits on: …` line holds the open question ids and
texts, and the PO's reason, the last step's summary or the repeated reason;
it is cut at 140 characters with its full text as its tooltip, and it is
the one place the detail shows. No pill on a story card wraps: a label too
long for the card is cut with an ellipsis and its full text is the pill's
tooltip. Since
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
last end report, the pending boundary and the stack, which holds the
sprint's PR (s151): its branch, base, PR number and URL, `mode`
`none`/`draft`/`ready`/`closed`, `as_is` and its CI card; the Board tab
shows it as the **Sprint PR** card, and the Activity tab shows `boundary` events), `turns` (the
`turns.jsonl` lines of the last 10 minutes, at most 500), `heartbeat`
(`heartbeat.json` as written, or `null`) and `health` (`{"level", "reason",
"model_note"}`; see "Live meter and health"). The contract is
`runner/agile_team/dashboard/fixtures/snapshot.json`. It is generated, so
never edit it by hand: edit its source,
`runner/scripts/dashboard_fixture/<key>.json` (one file per top-level key),
then rebuild it with `runner/scripts/make_dashboard_fixture.py`. A test fails
when the committed fixture differs from a fresh rebuild. The Tokens tab's role
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
| red | the run is halted (`blocked`, `failed`, `stopped` by `stop --now` or another SIGTERM, `checkout-changed`): `halted: <reason>`. A `limit` stop (s159) is red too |
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
sleep left out; the Product Owner's is its turns' model and tool time,
with a `waiting on roles …` line under it); `↩ N bounced`; a model/tool bar (dashed `no
model/tool timing yet` without data); and a tokens-per-minute sparkline of
its latest step (`rate` on `step-end` and `po-turn`), grey when idle. Only
used roles are drawn (`roles[].used`); the Product Owner always is. In
Story scope a role that has not touched the story is dimmed; in Sprint and
Run a role with no data is. Dimming recolours the box and never uses
opacity. A role with no data reads `idle`.

**The PO in Story scope (s113).** Each `po-turn` event's `data.stories`
lists the stories the turn's PO tool calls named (a `story` or `stories`
argument), once each, `[]` for none; the event's
`story` stays `null`. In Story scope the PO's time, waiting, bar and
sparkline come from the turns that named the focus story. A turn that named
several counts in each, and the waiting line then ends `· shared turns`.
With no such turn (or only events from before s113) the time reads `—`. The
PO's tokens and dollars read `—` in Story scope (its ledger rows have no
story).

The running role's box and its group take the run colour: green on the
step's first run, violet on the first re-run, amber after that (earlier
`step-start`s of the same role, story and step whose run was not
interrupted). Its box shows the current tokens per minute with the
sparkline in that colour, and a live line: story, step, awake time, run
label and the latest tool call. Its tokens, dollars and awake time include
the running step when the step is in scope (s137, ADR-0068). The tokens and
dollars come from `heartbeat.step` until the ledger has a row of the same
role and story written since the step started. The awake time comes from the
open `steps` row until `step-end` closes it. So the step is counted once. Runner stages that prepare or gate a
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
key_file = ".team/run/api-key" # repo-relative, absolute or ~/…; falls back to ~/secrets/anthropic-api-key
auth = "api-key"               # or "login": run on the human's Claude Code login
cadence = "sprint"             # default; the liaison asks at every start
budget_usd = 20.0              # ceiling: the run halts when spend reaches it
manager_every_pct = 25         # Manager checkpoint every N% of budget
max_open_stories = 5           # s159: at most this many stories have a worktree (integer >= 1)
step_reserve_usd = 1.00        # s159: the least budget held back per running step (>= 0, < budget_usd)

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
# The templates run under sh from the repo root, so "$PWD" is the repo root even
# when a command changes directory itself. This repo (s157, ADR-0081) adds
# house-rules: lint_files ends with `&& uv run --frozen --quiet --directory {root}
# --project "$PWD/house-rules/runner" house-rules check {files}`, and fix ends with
# `; git restore --source=HEAD --staged --worktree -- .house-rules-baseline.json
# && uv run --frozen --quiet --project house-rules/runner house-rules baseline`,
# so a step's commit holds the committed baseline shrunk by what it fixed and
# never a new entry. `static` ends with `house-rules check` over the whole repo,
# so gates, the quality step and both boundary checks run it.

[toolchain.report]             # optional; JUnit reports (s125). Unset keys come from the preset
option = "--junitxml={file} -o junit_family=xunit1"   # {file}: the report path; empty turns reporting off
# `deselect` and `ignore` still load (presets set them) but nothing uses them since s159.
# In `test` and `coverage`, put `{report:<root>}` where each pytest's options go,
# one per link of a `&&` chain (<root>: the repo-relative dir pytest runs in).
# A command with none gets ` {report}` (root "") at its end. This repo uses
# `… pytest -n auto -q {report:agile-team/runner} && … pytest -q {report:unattended/runner}`.

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
steps = ["design", "ops-review", "tests", "implement", "quality", "review",
         "design-review", "e2e", "acceptance"]   # drop steps to skip them; ops-review always runs, after design (s115)

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
branch = "main"                # the sprint is replayed onto it; what the sprint's PR targets
prefix = "team/sprint-"        # sprint branch names: <prefix><sprint>
story_prefix = "team/story-"   # s159: story branch names: <story_prefix><id>; must differ from
                               # prefix, and neither may start with the other

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
# `config check` warns about a harness with no prepare: its sandbox holds only the
# presentation, so its commands have no product to run (#56)

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
exactly (no prose, no case folding); `agile-team story new` and `story amend`
refuse any other name and list the valid ones. A story's environments are the distinct names of its
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
- A file whose name starts with `_` is a **base**, never a role: it is only
  reached through `extends`. `_shared` is the base of every role.
  `_leadership` (extends `_shared`) is the base of the Product Owner and the
  Manager; the liaison reads it too (SKILL.md). Write the human's decisions
  for the whole leadership team once, in `.team/roles/_leadership.md`.
- Addenda apply along the whole `extends` chain, each right after its own
  role's body. So a repo addendum to a base reaches every role built on it.

`roles scaffold` writes the stubs; `roles list` shows what each layer does.
Global files can live in a dotfiles repo; the runner only reads them.

System prompt order: `_shared` (+ `_shared` addenda) → for each role in the
chain, root first: its body, then its global and repo addenda → repo
instructions (`.claude/CLAUDE.md`) → `.team/CLAUDE.md` → file scope. Nothing else is added: a `.team/briefs/`
directory, if one is left over, is never read (s114). Each step's own brief is
the message the runner or the PO sends.

**Repo instructions (s142).** Every role, the PO included, gets the repo's
own `.claude/CLAUDE.md` under `## Repo instructions`, right before the
`## Repo charter`. So a rule the human writes there once reaches the whole
team, and the charter holds only what is about the team. The runner reads the
file's text itself:

- An `@path` import (at the start of a line or after a space, outside
  backtick code) is resolved relative to the file that holds it. When it
  resolves to a file inside the repo, its text, with its own imports handled
  the same way, replaces the import. Each file is inlined at most once per
  prompt. A repeat or a cycle becomes
  `(left out: @<path> is already included above)`.
- A `~` path, or a path that resolves outside the repo, becomes
  `(left out: @<path> points outside the repo)`. `~` is never expanded. A
  token that is not a file (`@someone`) stays as it is.
- Files are read as UTF-8 on every platform. An in-repo import that cannot be
  read as text (not valid UTF-8, for example `@docs/logo.png`) becomes
  `(left out: @<path> is not UTF-8 text)`, and the rest of the file still
  loads (s144). Each import of such a file gets the note. A root
  `.claude/CLAUDE.md` that is not UTF-8 still fails the step.
- A missing file adds no section. Only `.claude/CLAUDE.md` is read. A root
  `CLAUDE.md`, `CLAUDE.local.md` and `.claude/rules/` are not.
- Only the text is loaded. Role sessions keep `setting_sources=[]`, so
  `.claude/settings.json`, its hooks and its permissions never reach a role.
  The home `~/.claude/CLAUDE.md` is never read. To share a home rule with the
  team, put it in the repo file.

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
"Routing"). When it changes or retires a requirement it adds
`"requirement_changes": {"REQ-003": "<why>"}` (a map of strings, or the
handoff is malformed; see "Requirements"). `friction` is
optional: what slowed the step down or would make it cheaper. It is logged on
the step-end event for the Manager. A developer at `implement` may add
`"dispute": {"test": "<test id, file path first>", "rule": "<design rule
id>", "reason": "…"}` with status `changes_requested` when a test contradicts
the design (see "Test disputes"). A dispute without `test` and `rule`, or
with another status, is a malformed handoff. A `tests` key, which s46 used for
`changed`/`confirmed` claims, is ignored since s159. A role on
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
- `state.json` keeps `po_cost: {"session", "reported", "reconciled"}` with the raw
  figure, so `start --resume` keeps the baseline. An older `state.json`
  takes its baseline from the last PO ledger entry.
- The provider's `billing` applies to the own cost. A query with no result
  ledgers `0` and leaves `po_cost` as it was.
- A PO query that is never ledgered (an error result) is still in the
  next query's running total, so that query's difference pays for it.
- **Cut-off spend (s10, ADR-0078).** Every `start` checks for queries cut
  off before their ledger row (a crash, a kill), unless a runner is alive.
  For each role and story, the `turns.jsonl` lines after its latest ledger
  row become one ledger row. That row holds the sum of their estimated
  `cost_usd` (`null` counts 0) and tokens, `turns` (distinct `message_id`s)
  and the last line's model, stamped with the start time. Torn or bad lines
  are skipped. A row is written once, because the next start finds those
  turns covered. The start prints `agile-team start: ledgered $<cost> for
  <role[ on story]>, cut off by the last run (estimated from turns.jsonl)`.
  A reconciled PO cost is added to `po_cost.reconciled`. The next query
  resuming that session takes `min(reconciled, own)` off its own cost,
  because the session's running total may already include it. A new
  baseline starts with `reconciled` at 0. A reconciled row fires no budget
  checkpoint.

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

The halt is like a limit stop, but with status `blocked` (a limit sets
`limit` since s159), `status_reason`
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

The runner itself runs in its own venv (`uv run --project <runner>`), which a
role must not inherit: its Bash would then find the runner's `python` and
`pytest` instead of the project's. When `VIRTUAL_ENV` is set, every query
gets `VIRTUAL_ENV=""` and a `PATH` without that venv's `bin` (or `Scripts`)
directory (#55).

### The PO stays in its lane

The PO may read only `.team/**` and the docs directory, so it cannot read
source or tests. Diagnosis goes to the architect, reviewer or devops.

## Pipeline and gates

design (architect; gate on `done`: every AC of a story designed from s1 on is
covered by an active requirement, see "Requirements"; a reverted story's
design has its After revert section) → ops-review (devops; always runs, see "Ops review") →
tests (unit-tester; no command gate since s159: new tests may already
pass, and they must pass at implement and at `land`; an open dispute has
its own gate, see "Test disputes") →
implement (developer-*; gate: tests pass and coverage ≥ threshold, or ≥
`.team/baseline.json` coverage when old debt keeps the total lower; the gate
runs the suite **once**, through the `coverage` command only: a zero exit
with a high enough total passes, and a non-zero exit never passes. It
bounces as a coverage shortfall when the output shows a total below the
requirement and no failing test, and as `tests fail` otherwise; a shortfall
reads `coverage X% is below Y%`, then a line naming the `coverage` command,
that the total covers everything it measures and not only the story's files,
and where `Y` comes from: `[gates] coverage` alone, or the lower of it and
the `.team/baseline.json` baseline) → quality
→ review → design-review → e2e (integration-tester; gate when `acceptance`
is enabled: a `done` handoff passes only with a complete presentation and,
for a `web` environment, a service that starts from it and answers its probe)
→ acceptance (customer-proxy) → land (the runner itself, s159; no role
runs it and `run_role` on a story at `land` is refused: the story merges
into the sprint branch and is done only when land passes; see "Story
branches and landing").

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

### Ops review

`ops-review` (s115, ADR-0059) is a built-in step: the runner puts it right
after `design` (or first, when `design` is not enabled) whether or not
`[gates] steps` lists it, and it cannot be configured away. Stories already
past `design` when it arrives are not sent back. It is a checkpoint: a story
reaches it only by passing design. No bounce, Manager fault, acceptance
failure or revert sends a story to it, so a `changes_requested` naming
devops from a later step is still `unroutable` (the PO briefs devops).

DevOps's brief has an `## Ops review` section: the story's ACs with their
acceptance environments, the `[toolchain]` commands, the `[[environment]]`
names and kinds, the `[[tool]]` names and the `ci` globs. For each AC it
answers: can this be checked automatically with what the repo has today?
It hands off one `tooling` row per AC:

```json
"tooling": [
  {"ac": "AC1", "verdict": "automatic", "how": "tests/test_x.py::test_y"},
  {"ac": "AC2", "verdict": "added", "how": "the e2e-web CI job"},
  {"ac": "AC3", "verdict": "missing", "needs": "a browser harness", "story": "s130"}
]
```

`automatic` and `added` need `how`; `missing` needs `needs`; an `added` row
needs `changed_files` (DevOps adds what is missing in its own files, CI and
the `[toolchain]`, `[[environment]]` and `[[tool]]` config, in the same
step). A malformed list is a handoff error. The ops gate:

| Handoff | Result |
|---|---|
| `done`, a row per AC, every `missing` row names an existing story | pass to `tests`; before the story moves, the runner writes the rows into the story file under `## Tooling` (one `chore(<id>): record the tooling review in the story file` commit). If that commit fails, the runner puts the story file back, and the pass becomes a gate hold at `ops-review` (no round). The reason names the git error; fix it, then `continue_story` |
| `done`, an AC without a row, an unknown or repeated AC, or a story id with no story file | bounce back to `ops-review` (a round) |
| `done`, a `missing` row with no story | gate hold: the PO asks the liaison for a story for each need (`request_story`), then, once the runner has opened them, `continue_story` with a note naming them; DevOps runs again and fills in the ids |
| `changes_requested` | bounce to `design` with DevOps's summary as the reason, whatever `next_role` says: the design assumes tooling that can't exist |

The `## Tooling` section reads `- AC1: automatic today: …`,
`- AC2: added now: …`, `- AC3: missing: … (story s130)`. A later pass
replaces it. Later steps and the Customer Proxy read it in the story file;
`step-end` events carry the rows as `tooling`.

### Runner results and runner tools

Only the runner runs the full suite and coverage (s69). Roles get the
results in their briefs instead:

- The tests gate's `test` run and the implement gate's `coverage` run are
  kept per story, whatever the verdict, in `.team/run/results/<story>/<name>.json`
  (exit code, the last 60 output lines, the HEAD they ran at, where they ran,
  and, from the run's JUnit report, each failing or erroring test with its
  first error lines; s154). A brief lists the first ten of those tests under
  the run's output, and a gate that does not pass shows the same list on its
  dashboard entry.
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
| architect | `requirements`: every changed or retired requirement file in the step has a reason in the handoff's `requirement_changes` (s2; the refusal says `explain change to REQ-003: add "requirement_changes": …`) |

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
  `stop.lint`, `stop.suite`, `stop.presentation` and
  `stop.requirements`, and their
  open row and event carry `attempt: {n, of}`. On the Flow chart they are the
  role's after tool boxes: `label · ↻ runs · time · n refused`, and
  `▶ label · attempt n of 3` while running.

### Test reports (s125)

- **Reports.** Every gate and full-check run of `test` or `coverage` writes
  JUnit XML (`[toolchain.report] option`, one file per `{report:<root>}`
  placeholder). Full checks write under `.team/run/reports/`, the landing
  checks under `.team/run/reports-landing/`, and each story's gates under
  `.team/run/reports-story/<id>/`, all in the main checkout's run directory.
  Failing tests are read from the report. The text is still kept for the
  briefs. Named runs (`run_tests`) write no report. A stack with no `option`
  (node, rust presets) keeps the exit-code gates.
- **Ids.** A test id is a repo-relative pytest node id
  (`agile-team/runner/tests/test_x.py::TestY::test_z[a]`).
- s125's pending tests (`.team/pending-tests.json`, the `pending-tests`
  command, the red tests gate) were removed by s159.
- Agents never mark a test `skip` or `xfail`.

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

Each such command also runs with `COVERAGE_FILE=<its tree>/.team/run/.coverage`,
so coverage.py writes its data file under the run dir, which no step's audit
looks at, instead of leaving a `.coverage` at the root for the next step's
audit to quarantine.

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
- The guard's error is a pytest outcome (like `pytest.fail`), so a hit inside
  one of pytest's own fixtures fails that test only; the tests after it in
  the worker are unaffected (s154). A unit test that requests `tmp_path`,
  `tmp_path_factory`, `tmpdir` or `tmpdir_factory` is refused at setup,
  before any fixture runs, with the same advice.
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
HEAD`). The Manager sees these facts for a repeated setback (see
"Repeated setbacks"). The tests step has no red-tests gate since s159, so a story
back at `tests` with its code in goes on with a `done` handoff whether the
suite is red or green; the `changed`/`confirmed` claims are gone. An open
dispute's own gate (below) still applies. A `state.json` written before s46
loads `code_commits` as `[]`, and one written before s24 loads
`implemented` as 1 for stories past `implement` and as 0 for the rest.

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
   `confirmed`.
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
  `Would reformat:`). A `path:line:` line whose message starts with `warn`
  or `warning` is advice and never an item (s157). Findings for the same path and source make one item,
  with at most 40 output lines. Its printed path is matched against
  `git ls-files` (the exact path, else every tracked path ending
  `/<path>`). If all matches have one owner, that role owns the item.
  Otherwise the item stays with the step's role. A timed-out run is not
  routed.
- **Kept at implement.** A failing test in a unit-test file stays with the
  developer (the unit-tester's tests are the developer's to make
  pass). A lint finding counts only in a file the story touched (`files`,
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
  `- <name> (<kind>): <dir>/ (<AC ids>); its guide: <dir>/PRESENTATION.md`,
  where `<dir>` is `.team/run/presentation/<story>/<name>`
  (an absolute path into the main checkout's run dir when the step runs
  in a story worktree). Each guide covers only that environment's ACs. A story from before s95
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
  `GIT_DIR`, `GIT_WORK_TREE`, `GIT_DISCOVERY_ACROSS_FILESYSTEM`,
  `GIT_SEQUENCE_EDITOR`, `GIT_EDITOR` or
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
  where `<gap>` names every gap of that environment, joined by `; ` (#57):
  the guide's,
  `<dir>/PRESENTATION.md is missing or empty; write the customer's guide there`,
  then the workspace's, one of
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

`start` runs the **scheduler** (s159; see "Parallel steps"). It runs the
steps the router offers, one task per story and several stories at once,
and hands the PO its queued hand-overs one **PO turn** at a time. A PO turn
resumes the PO's session with one prompt (the kickoff, the resume note or
the hand-overs) and lasts until the PO ends its turn. Before story branches
are switched on (see "Switching over"), it runs one step at a time, as
before. The router offers work in this order:

0. the pending sprint **boundary** (sync, full checks, push, CI, replay;
   see "Sprint boundaries"), one stage per step, or its DevOps fix
   step, once no story step and no land is running. A held boundary is
   skipped. While a boundary is due, no new story step starts;
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
| `gate_hold` | the gate put a `done` step on hold for an environment reason (e.g. a `web` environment's port is in use by another process), or a story file that went bad before a Proxy step (s94, "Story files"); `continue_story` once it is fixed. The PO can't fix a story file: the liaison does, with `story amend` (see "Story files") |
| `bad_handoff` | the `manager` gave no valid handoff |
| `questions` | the handoff has `open_questions` |
| `quarantine` | the step's out-of-scope changes were quarantined |
| `round_cap` | the story reached the round cap (not an `escalate` verdict) |
| `unroutable` | a bounce names a `next_role` that owns no pipeline step |
| `ruling_not_applied` | the Manager ruled but the ruling could not apply (see "Rulings") |
| `runner_fault` | the Manager put a setback on the runner; the story is blocked and the human was told |
| `off_pipeline_fault` | the Manager put a setback on a role with no pipeline step; brief it, then `continue_story` |
| `fault_not_applied` | the Manager's `fault` was not applied (missing, unknown role, no story or a done story); the reason is in the line |
| `rebase_conflict` | the sprint-end replay conflicted and DevOps could not settle it in the scratch replay, or its result was refused, or the full checks failed there (the stopped story and commit and its files, grouped by directory with a count; the reason; DevOps's notes; the scratch branch; the sprint branch is unchanged). `continue_boundary(note)` starts a fresh DevOps attempt (s151 AC6, s159) |
| `sync_conflict` | legacy (before s151 AC6): a saved boundary held on a sprint-end rebase conflict. `continue_boundary` reruns the rebase; a conflict now goes to DevOps |
| `push_permission` | the runner is about to make its first push of any kind (a story branch, a landing or the sprint branch), and the human has not yet said whether the team may push. Raised once (`permission_asked`); until the answer, steps commit and nothing is pushed (s159) |
| `push_rejected` | a push was refused: its remote branch moved, or the runner's own check found it is not a fast-forward of the recorded head (`NOT_FAST_FORWARD`), at the `push` or `push-replayed` stage; the stage stays and `continue_boundary` reruns it. The runner never retries a refused push with another expected sha |
| `story_ci_red` | CI failed on a story's own draft PR (s159). The hand-over lists each failing check, its failing step and its failing lines (s172). Nothing is held; the story lands only on green landing CI. The PO briefs its developer if it needs a fix; the developer's next brief carries the same lines |
| `worktree_drift` | a story's worktree changed outside the team (s159); the line names the worktree and the files. Only that story waits. The PO tells the human; `agile-team accept-checkout --story <id>` keeps the worktree as it is |
| `land_bounced` | a landing stopped on a merge conflict (s159); the line names the files and the role (DevOps for files only DevOps or no role owns, else the story's developer) that rebases the story onto the sprint head. Then land runs again |
| `overlap` | a design's `## Files` overlap another open sprint story's work (s163, per story); the story waits at `design`. The line names the files each changes and the overlap. The runner lifts it once the others have landed, left the sprint or been cancelled; `release_story` with a reason lifts it early, and `continue_story` is refused |
| `boundary_error` | a boundary stage raised an error (traceback in `crash.log`) |
| `boundary_escalated` | the same boundary failure repeated after a fix and the Manager reviewed it |
| `ci_green` | the review PR's CI checks all passed; the line says it is **ready to merge**, and the PO tells the human. This is the only text that calls a PR ready; see the CI rule under **Ready.** |
| `ci_failed` | the review PR's CI failed where our code ran; the line names each failing check (workflow / job), its failing step, its link and its failing test lines. `continue_boundary` is refused here (s111). The PO asks the liaison for a bug story at once (`request_story`; or picks an open story that fixes it), records it with `record_ci_bug` once the runner has opened it, tells the human the PR is **NOT** ready, and lists the story first in the next sprint; see the CI rule under **Ready.** |
| `ci_infra` | a CI job ran no step, and still ran none after the runner's one re-run. The PR is NOT ready. The PO tells the human; `continue_boundary` reads the checks again once they re-ran it, or `record_ci_bug` records a story that changes the CI job; see the CI rule under **Ready.** |
| `main_broken` | a check failed where our code ran, and the same job and step fail on `[upstream] branch`'s head. The PO asks the liaison for a bug story for main (`request_story`) and records it with `record_ci_bug` once the runner has opened it: the sprint ends as "ended, CI blocked by main" (NOT done, PR unmerged) and the next sprint starts with that story first; see the CI rule under **Ready.** |
| `ci_pending` | the CI checks were still running at `[gates] ci_timeout_s`; the line names them. The PR is NOT ready; `continue_boundary` waits again; see the CI rule under **Ready.** |
| `known_failures` | the sprint start's full checks failed (s152); nothing is held and the sprint goes on. The line names the count, the ids, the team branch's sha and the failing output. Unless an open story already covers them, the PO asks the liaison for a story with `request_story`; the liaison writes it and places it at the top of this sprint or later |
| `pick-request` | the human or the liaison asked for a pick (s141). The line names each commit with its subject and whether it is on `<remote>/<branch>` or not yet, the reason and who asked. The PO answers with `accept_pick(request)` or `deny_pick(request, reason)`. Until it does, the request stays pending; see "Picks (mid-sprint)". |
| `pick-forced` | the human forced a pick and the runner applied it: the commits, the reason and the new sha12s. The PO plans around it; it can't be reverted. |
| `pick-settled` | any other pick outcome: an accepted or own pick applied (with the new sha12s), or not picked (refused, or failed, nothing changed), or a conflict naming the files (the whole pick aborted, nothing changed). |

`ci_infra` and `ci_pending` are raised by a landing's CI wait too (s159): the
land holds, and `continue_story` lets it wait again.

**Scopes** (s159, ADR-0085). Every trigger is `story` or `run` scoped, in one
table (`handover.SCOPES`) that the runner checks before any command runs; a
trigger missing from it is an error. A `story` hand-over queues for the PO and
holds only its story. A `run` hand-over queues and also stops new steps from
starting until the PO turn that receives it ends. The `run` triggers are
`error`, `boundary_error`, `boundary_escalated`, `sync_conflict`,
`rebase_conflict`, `push_rejected`, `ci_failed`, `main_broken`, `ci_green`,
`sprint_end`, `next_sprint`, `stalled` and `sprint_backlog_stuck`. Every
other trigger is `story` scoped, including `ci_infra`, `ci_pending`,
`push_permission`, `known_failures` and `human_message`.

The runner also hands over `human_message` (the inbox has answers the PO has
not seen, listed by id with the question, or `tell` messages it has not
been handed, each as a path to read; see "Liaison messages"),
`sprint_backlog_stuck` (s156: nothing in the Sprint Backlog can move, no
boundary is pending and no question is open; see "Backlog and sprints"),
`sprint_end` (every story
in the sprint is done, cancelled or reverted and the sprint's end boundary has finished; a
`Review: …` line says what was pushed) and `stalled` (nothing can move because a
boundary is held, which it names, or the sprint has no stories). A story's reason is
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
  question ids it waits on (`waiting on answers: s40 waits on m42`). Neither
  `stalled` nor `sprint_backlog_stuck` is handed over while a question is open:
  the question is already the report to the human (s156).
- The run ends when a stop is requested, the run halts (`done`, `blocked`
  on the budget, `checkout-changed`, `limit`), or the PO sets `sprint-end`
  (sprint cadence) or `done`. Since s159 a quiet pass no longer ends it, and
  `notify_user(kind="blocked")` no longer sets `blocked`: it posts its note
  and the run stays `running`, waiting, with the note's first line as
  `status_reason` (see "Waiting and limits"). A self re-pin also ends the
  loop, but the run goes on in the new process (see "Self re-pin"). A stuck
  Sprint Backlog is never quiet: after 3 `sprint_backlog_stuck` hand-overs
  the runner posts the stuck note and waits on the human (see "Backlog and
  sprints").
- Under `until-blocker` (s128, s156), a sprint end never ends the run while the
  Product Backlog has ready stories. A sprint end with ready Product Backlog
  stories hands over `next_sprint` (the ready list and "start the next sprint
  now"). It is not quiet, so a PO turn that starts nothing gets it again. After
  3 such hand-overs with no `start_sprint`, the runner posts "The PO did not
  start a sprint after 3 next-sprint hand-overs; …" and waits on the human
  (before s159 it set `blocked`). A
  stuck Sprint Backlog is reported, not refilled, under both cadences (see
  "Backlog and sprints"). `notify_user` `done` and `blocked` are refused while
  a Sprint Backlog story can move (`cadence until-blocker: Sprint Backlog
  stories can still move (…)`), never because Product Backlog stories are
  ready. A PR waiting for review or merge never holds the next sprint.
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
committed to, or `null` when it is in the Product Backlog.

- The liaison writes every story (`agile-team story new`), and the runner
  opens it between steps: it gives it an id, commits its file and places it
  in the running sprint, first for the next sprint, or in the Product Backlog, as
  the liaison asked (see "Stories from the liaison"). The PO never writes a
  story file and has no tool to open one (s135).
- `start_sprint(goal, stories)` is the only way into a sprint. It opens sprint
  `N+1` with exactly the listed stories. Unfinished stories it does not list
  go back to the Product Backlog. Done stories never move; they keep the sprint they
  finished in. It refuses an empty list or unknown ids (`unknown stories: s7;
  ask the liaison for them with request_story`) and changes nothing when it refuses.
  Once those checks pass, it reloads every open story's `depends_on` from
  its file and is refused if the files are bad (see "Story dependencies").
- The `sprint-start` event carries `{"sprint", "goal", "stories"}`, plus
  `"reason"` when one was given.
- `run_role` on a Product Backlog story is refused: `story sN is in the
  Product Backlog; add it to a sprint` (s156). The status refusals (done, blocked, round cap) come first.
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
- **A sprint ends only when it is finished (s124).** It is finished when it
  has stories and every one is done, cancelled (the human's call) or reverted
  (`revert_story`, see "Reverting a story"). Cancelled and reverted stories
  leave the sprint. The end boundary opens, and `sprint_end` is handed over,
  only then. `notify_user` with kind `sprint-end` is refused while any sprint
  story is unfinished: `sprint N can't end: s3 at implement, s5 at design
  unfinished. Finish them, revert_story(story, reason), or ask the human to
  cancel them (request_cancel)`. Nothing is posted and the status stays.
- **A stuck Sprint Backlog is reported, not refilled (s156; replaces s124's
  ready backlog offer).** When the Sprint Backlog has unfinished stories,
  none can move, no boundary is pending and no question is open, the runner
  hands over `sprint_backlog_stuck`. Its lines are `Nothing in the Sprint
  Backlog of sprint N can move. Each story and why:`, one `sN at <step>:
  <why>` line per unfinished story, then the actions the PO may take on them
  (`continue_story`, `release_story`, `run_role`, `pass_tests`,
  `revert_story`, `request_cancel`, `request_story`, `ask_user`). It names
  those stories and lists no Product Backlog story. It works the same under
  both cadences and is never quiet, so a PO turn that changes nothing gets it
  again. `stuck_asks` in `state.json` counts these hand-overs. A step, a PO
  call to one of those tools (except `ask_user`) that is not refused, a
  `start_sprint` or an `add_to_sprint` resets the count to 0. When the count
  is 3, the runner hands over nothing. It keeps the run `running` and
  waiting (s159; before, it set `blocked`), with `status_reason`
  `Sprint N: the Sprint Backlog is stuck after 3 hand-overs with no PO action
  on its stories: <each story line>; …`, and posts the same text to the
  liaison as a `blocked` note, once. `add_to_sprint` still works as a deliberate PO
  action, but the runner never suggests it for a stuck sprint. An old
  `state.json` holding `offered` loads, and the field is dropped.
- `state.json` from before backlogs existed loads every story into the
  Product Backlog. Step, rounds, status and commit are kept. On resume, the runner
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
  or a `blocked` story with no open question. On a story held as `overlap`
  (s163, see "Files and the overlap hold") it lifts that hold instead: the
  story goes past `design`, the reason is recorded in `overlap-lifted`, and
  it returns `{"status": "released", "story", "step"}`.
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
| all | unknown story (`unknown story 'sN'; ask the liaison for it with request_story`); blank reason (`a reason is required`); done or cancelled (`story sN is done; there is nothing to hold`, with `release` or `cancel`) |
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

### Reverting a story (s124)

`revert_story(story, reason)` is the PO's call. It takes a story's work out of
the team branch, so the sprint can end or the story can start again. With
story branches on (s159), an unlanded story only drops its branch, and a
landed story's merge is reverted through a landing; see "Leaving and
reverting" under "Story branches and landing". The checks, the reset and
the records below stay the same.

**Refusals**, in order (a refusal changes, saves, posts and emits nothing):
the checkout moved (a `halted` report, as for `pass_tests`); a boundary is
pending; an unknown story; a blank reason; a done or cancelled story (`story
sN is done; there is nothing to revert`); a pending cancel or revert
question (`story sN already waits on the human's answer to mN about
reverting it; answer mN instead`, and the cancel text for a cancel); no
recorded commit (`story sN has no commits to revert`); a started, unfinished
story lists it in `depends_on` (`started stories depend on sN: …; revert
them first, or keep sN`); its first commit is not on the checked-out branch;
a git conflict with later commits (`reverting story sN stopped: conflicts
in …; nothing was reverted`, after `git revert --abort`). While a revert
question waits, `hold_story` and `request_cancel` are refused with the same
text.

**The revert.** The runner first commits the PO's open edits (as before a
`run_role`). The story's commits are its first recorded commit and each later
commit whose subject is `fixup! <that subject>`. They are reverted, newest
first, in **one** commit: `revert(sN): <title>`, body `Reverts <shas>.` and
`Reason: <reason>`. Then the runner:

- appends to `.team/stories/sN.md`, under a `## Reverted` heading added
  before the first entry, `- <UTC date>, sprint <N>: <reason> Reverted
  commits: <shas>. Revert commit: <sha>.` (12-character shas). It commits this
  separately as `chore(sN): record the revert in the story file`;
- resets the story: back in the Product Backlog (`sprint: null`) at the step before
  `tests` (or its current step when that comes earlier), with commit, code
  commits, rounds, holds, dispute and fix records cleared. It keeps its id,
  title, `depends_on`, developer choices and `reverted` history, keeps its
  place in `order`, and leaves `pulled`;
- emits one `story-reverted` event: `{"sprint", "reason", "commits",
  "revert", "record", "count", "from_step", "step", "roles", "question"}`;
- tells the human: one `update` note naming the story, reason, commits,
  revert commit and step.

**Where the team sees it.** The Board card and Backlog row show `reverted
(n×)`. The sprint's review PR has a `Reverted:` block with one line per revert
made in that sprint. Each role that worked on the story (its `step-end`
events) gets a `## Reverted` section in its next brief on the story, once
(`revert_owed` in `state.json`). Every brief for the story's `design` step
adds: `Your design must say what changes this time, under a "## After
revert N" heading; the design gate checks for it`. A `done` at `design`
without that heading in `<docs>/design/sN.md` bounces back to design.

**A second revert asks the human.** For a story reverted before,
`revert_story` reverts nothing. It posts `Revert story sN ("<title>") again?
It was reverted N× already (last: <reason>). The PO asks because: <reason>
Answer "revert" to revert it or "keep" to keep it.` and sets a `revert
requested` PO hold (Board `⏸ revert requested`, the reason on its `waits on:` line). It returns `{"status":
"revert requested", "story", "step", "question"}`. The answer is settled where
cancel answers are. `revert` reverts as above (on failure, a `PO hold`
saying why). `keep` clears the hold. Anything else is a `PO hold` (`the answer
to mN was neither "revert" nor "keep": …`). Each request and answer writes a
`story-admin` event, as in s53.

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
| 1 | the file exists and is readable | `no story file` |
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
| `story new` and `story amend` (the draft: no `id` check, and `id` or `shared` in it is a problem) | the command prints the refusal and queues nothing |
| the runner's intake, before it commits a queued draft (the draft, then the file with its `id:` line) | the request is refused (see "Stories from the liaison") |
| before every Customer Proxy step on the story (after the PO's turn, before the unpresented check) | the step does not run and nothing is billed; the gate holds the story with `the story file must be fixed before acceptance:` + the refusal + `Only the runner writes story files. If the config lost the environment, route the fix to devops and continue_story once it is in; if the ACs are wrong, ask the human with ask_user, and the liaison sends new ACs with story amend`, which the PO gets as a `gate_hold` hand-over |

**Only the runner writes story files** (s135). The guard refuses every
role's Write, Edit or NotebookEdit under `.team/stories/` (`product-owner
may not write .team/stories/s1.md; only the runner writes it`), a step's
Bash change there is quarantined, and no role layer can grant it. A file
reaches git only as the runner's `docs(<id>): …` commit (see "Stories from
the liaison"), a `share` or a runner record (`## Tooling`, `## Reverted`).
**Fixing an environment** is one of two things. If the config lost the
environment, DevOps or the human fixes `.agile-team.toml`, and the PO then
calls `continue_story`; the next Proxy request reads the file again. If the
ACs are wrong, the PO asks the human, and the liaison sends corrected ACs
with `story amend`. That sends the story back to design and clears the hold.
The hold text names these two fixes and never tells a role to edit the
file (s138). A `suite_runs` value the gate can't use is held the same way:
`… only the runner writes story files: ask the human with ask_user for a
valid suite_runs`. The hold counts as a setback like any gate
hold, so the same unfixed hold repeated can escalate.

**State and snapshot.** `state.json` keeps no environment for a story. The
snapshot's story `environment` (a string) is the story's environments joined
by `", "` in config order (`"cli, dashboard"`), or `""` when the file has
problems.

**Every environment is tried** (s95). A story whose ACs name two environments
is presented and tried in both; see "Acceptance per environment".

### Shared files (s120)

The liaison shares a mock or spec with `agile-team share <file> --story <id>`
(see "CLI"). The command only queues `.team/run/liaison/shares/f<N>.json`.
Each router tick, right after the dashboard reorders and never while a sprint
boundary is open, the runner applies pending shares in number order:

1. it copies the bytes to `<docs>/design/<id>-<name>`;
2. it writes or replaces the entry in the story file's frontmatter (the
   runner is its only writer):
   ```yaml
   shared:
     - path: "agile-team/docs/design/s118-mock.html"
       sha256: "<64 lowercase hex>"
   ```
3. it commits exactly those two paths as `chore(<id>): share <name> (f<N>)`,
   records the new HEAD for the checkout guard, emits a `share` event
   (`request`, `path`, `sha256`, `commit`, `outcome`) and queues a `tell`
   note to the PO.

Re-sharing identical bytes is `unchanged`: no commit. If the story file is
gone, or its frontmatter can't be rewritten without touching other keys,
the share is `refused: <why>`. Each outcome shows under `status`'s
`shares`.

**Bad request files (s133).** The runner checks each request file when it
loads it: a JSON object whose `story`, `name`, `sha256` and `data` are
strings and whose `at` is a number, with `data` valid base64 that matches
`sha256`. A file that fails is settled once as
`refused: bad request file f<N>.json: <problem>`. It emits one `share` event
(story `null`, outcome `refused`), writes nothing and is never retried.

**Where a shared path may point (s133).** Before a listed path is used, it
is resolved (`.`, `..`, symlinks, absolute paths; a path that cannot name a
file, such as one with a NUL byte, resolves to nowhere). It counts only when it
already is its own resolved form and sits directly in `<docs>/design/`.
Otherwise it is a `shared:` problem
(`path <p> resolves to <where>; a shared file must sit directly in <docs>/design/`).
A problem holds the story at acceptance, and the path never reaches the
Proxy's scope or sandbox, a brief or the hash check.

**Who reads them.** Every role reads `<docs>/design/`. The Customer Proxy
gets read access to exactly its story's shared paths, in its scope and its OS
sandbox. The architect's and the Proxy's briefs have a `## Shared files`
section listing each path with its hash. A story with shared files passes the
design gate only when `<docs>/design/<id>.md` names every shared path.

**Acceptance checks the hash.** Before the per-environment verdict, the
`acceptance` gate hashes each shared file (SHA-256 of the raw bytes). A
changed or missing file bounces the story to `design`, with one line per
file (`<path>: sha256 <found> (shared <recorded>)` or
`<path>: missing (shared <recorded>)`). A malformed `shared:` list holds the
story with the story-file hold text. Only a new `share` changes a recorded
hash.

### Stories from the liaison (s135)

The liaison writes every story, and the runner commits it. No role writes a
story file, and the PO schedules stories and asks for new ones (ADR-0070).

**The commands.** `agile-team story new <file.md> --approved-by human|none
[--sprint current|next|backlog] [--after <id>] [--plan <path>]` and
`agile-team story amend <id> <file.md> --approved-by human|none
[--plan <path>]` (see "CLI"). The draft is UTF-8 Markdown:

```markdown
---
title: "Export the board as CSV"
depends_on: [s83]          # optional
acceptance:
  - id: AC1
    text: "agile-team export --csv prints one row per story."
    environment: cli
---
As the human, I want the board as CSV, so I can share it.
```

`id` and `shared` are refused, because the runner writes them. Any other key
(`suite_runs`, …) is kept as written. Every check runs, and the command
prints every problem, one line each:

- the file can't be read (`cannot read <file>: <reason>`);
- the "Story files" checks, except the `id` check;
- `<file>: <key> is written by the runner; remove it`, for `id` and `shared`;
- a bad `depends_on` (see "Story dependencies");
- a blank body (`<file>: the body must hold the user story`);
- `--after` naming no story, or a done or cancelled one;
- `--plan` with `--approved-by none`, or naming no file;
- for `amend`: an unknown or finished story, `--sprint` or `--after` given, a
  story file with no readable frontmatter, a changed `title` or
  `depends_on`, or ACs equal to the story's (`nothing to amend`).

A problem exits 1 and queues nothing. A clean draft is queued as
`.team/run/liaison/stories/q<N>.json` (`action`, `story`, `approved_by`,
`plan`, `sprint`, `after`, `file`, `text`, `at`), with the same numbered
queue as `tell` and `share`. The command never writes `.team/stories/` and
never calls git. It works in any run state; a stopped run settles the
request at its next `start`. `status` lists `queued_stories` and each
outcome under `story_requests`.

**Onboarding at a safe point.** Each router tick, right after the shares,
the runner settles each queued request in number order, between steps. It
waits while a sprint boundary is open, except at the CI holds (`ci_failed`,
`ci_infra`, `main_broken`), where the PO needs the bug story for
`record_ci_bug`. For `new`, the runner:

1. runs the draft checks again, against the current config and state;
2. gives the story the next id (`s<highest + 1>` over the stories in state
   and the story files);
3. writes `.team/stories/<id>.md`, the draft with `id: <id>` added as the
   first frontmatter line, and commits that file alone;
4. records the commit in the story's `file_commits`: a sprint-start rebase
   remaps it, a revert keeps it (the story keeps its file), the review branch
   of the sprint it was committed in carries it, and the Backlog tab lists
   it first among the story's commits. It is not the story's `commit`, so it
   doesn't make the story "started";
5. places the story: `current` adds it to the running sprint like
   `add_to_sprint` (role `liaison`), or puts it in the backlog when the add
   is refused, saying why; `next` puts it in the backlog after the current
   sprint's stories; `backlog` puts it at the end of the order. `--after
   <id>` puts it right after that story instead (dropped, with a note, if
   that story has finished since);
6. tells the PO, as a queued `tell`: `Runner note: the liaison's story q<N>
   is now <id> "<title>" (<approved>; commit <sha12>), placed <placed>. Read
   <file>, then schedule it.`, and posts an `update` to the liaison:
   `Runner: story q<N> is <id>, commit <sha12>, placed <placed>.`

**Authorship.** The commit says who wrote the story and how much the human
was involved:

```text
docs(<id>): created story to <title>

Human-involvement: <involvement>
Liaison-request: q<N>
```

| `--approved-by` | Author | `Human-involvement:` |
|---|---|---|
| `human` | the repo's git user (no `--author`) | ``approved plan `<plan>` `` with `--plan`, else `approved by the human` |
| `none` | `Claude (agile-team liaison) <noreply@anthropic.com>` | `none: written and submitted by the liaison` |

An amend's subject is `docs(<id>): amended story to <title>`, with the same
body and author. The usual `Co-Authored-By` trailer is added to both.

**Amend.** The runner runs the checks again. It replaces only the story
file's `acceptance:` block (other keys and the body stay) and commits that
file alone, appending the commit to `file_commits`. It then sends the story
back to `design`: rounds, holds and tried environments are cleared, the
story's ACs must be traced again, and the PO's hold or an open question
stays. The PO is told `Runner note: the liaison amended <id>'s ACs (q<N>;
<approved>; commit <sha12>). It is back at <step> from <from_step>. Old:
<ids>. New: <ids>. Read <file>.`, and the liaison gets an `update`.

**Refusal.** A request that fails a check at onboarding, a commit that fails
(the file is put back) or a request file that is not valid JSON of the
queued shape is settled once as `refused: <reason>`, and never retried. The
liaison gets `Runner: story q<N> was refused: <reason>`, and the PO is not
told.

**Events** (role `liaison`, except `story-request`):

| Event | Story | Data |
|---|---|---|
| `story-opened` | the new id | `title`, `step`, `depends_on`, `request`, `commit`, `approved_by`, `sprint`, `after` (what was asked) |
| `story-amended` | the story | `request`, `commit`, `approved_by`, `from_step`, `step`, `old` and `new` (the ACs as `{id, text, environment}`) |
| `story-refused` | the amended story, or `null` | `request`, `action`, `reason` |
| `sprint-add` | — | as for `add_to_sprint`, for `--sprint current` |
| `story-request` (role `product-owner`) | the story the PO named, or `null` | `message`, `summary`, `step`, `files` |

**The PO asks with `request_story(summary, evidence)`.** It is for a bug the
team couldn't fix in its own turns: a red CI run, a broken main, a runner
fault, a check that `ops-review` says is missing. `evidence` is `{story,
step, output, files}`: where it showed (empty outside any story), the
failing output (required; the last 6000 characters are kept), and the files
involved. It posts a `story-request` outbox entry, which `watch` reports as
a `message`:

```text
The PO asks for a story: <summary>
Story: <story> at <step>          (or "Story: none")
Files: <a, b>                     (or "Files: none")
Failing output:
<output>
```

It blocks nothing and returns `{"status": "requested", "message": "m<N>",
…}`. The liaison writes the story (with the human, or alone with
`--approved-by none`) and sends it with `story new`. The runner opens it and
tells the PO its id. For any other missing story, the PO asks the human with
`ask_user`, and the liaison writes it the same way.

## Requirements

The product's requirements are files, `<docs>/requirements/REQ-NNN.md` (s1,
ADR-0060). The architect writes them at design: a new file, or a new
`covers` entry on an existing one. It retires a requirement
(`status: retired`) rather than deleting it.

```markdown
---
id: REQ-001
title: Requirements are structured files
status: active            # active | retired
covers: ["s1/AC1", "s1/AC7"]
---

The requirement in plain words.
```

**Checks, per file, in order.** 1, 3 and 4 stop the file's read; a bad
`covers` skips the item checks; everything else is reported. Each problem is
`{file}: {problem}` with a repo-relative file.

| # | Check | Problem text |
|---|---|---|
| 1 | the file reads | `cannot be read` |
| 2 | its name is `REQ-` and three or more digits, `.md` | `the file name must be REQ-NNN.md (REQ- and three or more digits)` |
| 3 | it starts with frontmatter | `no YAML frontmatter; start the file with --- and the keys id, title, status and covers` |
| 4 | the frontmatter parses to a mapping | `frontmatter does not parse: <error>` |
| 5 | `id` is the file name | `id is 'REQ-1', not 'REQ-001' (the file name)` |
| 6 | `title` is a non-empty string | `title must be a non-empty string` |
| 7 | `status` is `active` or `retired` | `status is 'draft'; use active or retired` |
| 8 | `covers` is a list (may be empty) | `covers must be a list of "sN/ACk" strings` |
| 9 | each item is `sN/<ac id>`; the AC id starts with a letter, then letters, digits, `_`, `-` or `.` (`s141/AC1.1`) | `covers item 2: 's1-AC1' is not "sN/ACk"` |
| 10 | no item is listed twice | `covers item 3: 's1/AC1' is listed twice` |
| 11 | the body is not blank | `the body is empty; state the requirement in plain words` |
| 12 | no other file claims the id | `id 'REQ-001' is also used by <other files>` |
| 13 | each ref's story has a story file | `covers item 1: 's9/AC1': no story file for s9` |
| 14 | that story file reads clean | `covers item 1: 's9/AC1': the story file of s9 has problems (<first problem>)` |
| 15 | the story has that AC | `covers item 1: 's9/AC7': s9 has no AC AC7; its ACs are AC1, AC2` |

**Coverage.** An AC is covered by every requirement that has no problem, is
`active` and lists it. Retired or broken requirements cover nothing. One AC
may have several requirements, and one requirement may cover many stories.

**The design gate.** Every story opened from s1 on is `trace: checked` in
`state.json`. A story saved before s1 loads as `checked` only if it sits at
`design` and has never been through a design step; otherwise it is `exempt`
and never traced. Nothing changes the value; a revert keeps it. On a `done`
handoff at `design`, a checked story bounces back to `design` (a round) with
every reason listed under one head line
(`s7's ACs must be traced to active requirements in <dir>/ before design passes:`):
each problem of a requirement file whose text mentions `s7/`, the story file's
own problems, and each AC with no covering requirement
(`s7/AC2 is covered by no active requirement; …`). A reverted story's missing
After revert section is listed in the same bounce. A broken file that doesn't
mention the story does not block it; `requirements check` reports it. Since
s163 every `done` design, traced or not, also needs a `## Files` section
naming the files the story changes; without it the design bounces, with
the gate's other reasons (see "Files and the overlap hold").

**Briefs.** On a checked story, the architect's brief has a
`## Requirements` section: each AC with its covering requirements (or
`untraced`), the active requirements with what they cover, and the next free
id. The code reviewer's and the Customer Proxy's briefs have the coverage
part; they cite the AC and requirement ids in their findings.

**Dashboard.** The Requirements tab lists the files (it reads them
leniently, so a broken file still shows). An exempt story's untraced AC reads
`designed before s1` and is not a gap. Each requirement's history on the tab
comes from its `requirement-changed` events (below).

### Requirement changes (s2, ADR-0083)

**Classified from the diff.** When a step ends, the runner takes the
`REQ-*.md` files in the requirements folder that the step changed in its
write scope. In practice that means the architect's. `git diff
--name-status --no-renames HEAD` (untracked files count as added) sorts
them:

| Change | When |
|---|---|
| `added` | the file is new |
| `retired` | the file was removed, or its `status` became `retired` |
| `changed` | any other edit, including retired → active |

**Reasons.** The handoff gives one reason per changed or retired
requirement: `"requirement_changes": {"REQ-003": "why"}`. Whitespace is
collapsed to one line. An added requirement needs no reason, and one without
a reason gets `new requirement`. The architect's `requirements` stop check
refuses its `done` stop while a reason is missing. If the step still ends
without one (another status, a malformed handoff, the stop allowed after 3
refusals), each unexplained edit is **held back**. It is committed alone and
reverted (`chore(team): architect's unexplained requirement edits, held
back`), the same way the quarantine works. The step then counts as a bad
handoff and bounces with a round:
`explain change to REQ-003 (your edits are held back in <sha>; make them again and give each reason in the handoff's requirement_changes)`.
Added and explained changes still land. A reason for a file the step didn't
touch is ignored. In a story rebase step, edits to the conflicting files the
rebase lists are the conflict's resolution, not requirement changes: they
need no reason and are never held back (any other requirement file is).

**Trailers.** The step commit ends with one trailer block: a
`Requirement-Changed: REQ-003: <why>` line per landed change, in id order,
then `Co-Authored-By`. Git is the only record. `agile-team requirements log`
prints it back (see "CLI").

**Event.** Each landed change writes `requirement-changed` with the step's
`role` and `story`, and data `{id, change, reason, sha}` (`change` is
`added`, `changed` or `retired`; `sha` is the step commit). A held-back edit
writes none.

**Auto-accept.** For each changed or retired requirement, the runner takes
the stories its `covers` names, before or after the change, except the
step's own story:

- an open story past the design step goes back to design, with no round
  counted and its loop state cleared, the same reset a story amend gets. Its
  next brief has the note `Back to design: <story>'s step changed
  requirements this story traces (<sha12>): REQ-003 changed: <why>. …`;
- a done story is listed in `affected_done_stories`;
- a story at design or before, or a cancelled one, is left alone.

**Report.** The step's report (`run_role`) gains `requirement_changes`
(`[{id, change, reason}]`), `redesigned_stories`, `affected_done_stories`
and `held_back`, each only when it is non-empty. A report with
`affected_done_stories` hands over to the PO (`affected_done`). The PO then
asks the liaison with `request_story` for a follow-up story that checks
those stories against the changed requirements.

## Story dependencies

A story that needs others done first lists them (s86) in its file's YAML
frontmatter as a block list. A comment can give the reason:

```yaml
depends_on:
  - s31  # hooks
  - s36
```

A missing key means `[]`, and a duplicate id is dropped (the first one is
kept). The liaison writes the list in the draft (`story new`). Never write "Depends on sN" in a story's
prose. `state.json` keeps a validated copy per story (`depends_on`). The
router, the `priority` events and the snapshot read only that copy.

**Load points.** The copy is reloaded from the files only at these points:

| When | What loads | On a refusal |
|---|---|---|
| `agile-team start` (every mode), before the PO or router runs | every story that is not done and has a file | the command fails with `story files: <refusal>; story amend cannot change depends_on, so the human fixes it: edit depends_on in the story's file in .team/stories, git commit it, then agile-team start again (agile-team accept-checkout first if start halts on the moved checkout)` and the run does not start |
| `start_sprint`, after its other refusals pass, before the sprint opens | the same | the tool returns the refusal and the sprint does not begin |
| `story new`, and the runner's intake before it commits the draft | the draft only | the command, or the intake, refuses the draft (see below) |

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
| c | a listed id is not a story in state (done stories are known, and a done dependency is satisfied) | `depends_on names unknown stories: s2 on s77, s5 on s78; only opened stories can be listed` |
| d | the graph has a cycle | `depends_on has a cycle: s1 -> s2 -> s3 -> s1` |

Ids are in natural order (`s9` before `s10`). The cycle is the first one
found by a depth-first walk from each id in natural order, following each
list in its own order. A story file that is not valid UTF-8 is not refused:
reading it raises an error.

A draft's `depends_on` (s135) is checked by `story new` and again by the
intake: it must be a list of strings (`<file>: depends_on must be a list of
story ids`), and every id must be a story in state (`<file>: depends_on
names unknown stories: s7`). A new story can't close a cycle, because no
story lists it yet. The `story-opened` event's data has `"depends_on"`.
`story amend` refuses a changed list (only the ACs change), so a wrong list,
or a `start` refused for a bad list, is the human's
to fix: with the run stopped, they edit and commit the file, then
`accept-checkout` if the next start halts on the moved checkout.

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
`unknown stories: s7; ask the liaison for them with request_story`, `done stories have
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

## Story branches and landing (s159)

ADR-0084 (branches, landing, replay, pushes), ADR-0085 (parallel steps),
ADR-0086 (kept sessions), ADR-0087 (waiting runs, `limit`). These rules
apply once story branches are switched on (see "Switching over"). Words:

| Word | Meaning |
|---|---|
| sprint branch | the team branch in the main checkout (`upstream.team_branch`); its remote copy is `<prefix><N>` |
| story branch | `<story_prefix><id>`, or `<story_prefix><id>-r<k>` after k replays |
| landing branch | `<story_prefix><id>-land`: pushed for one CI run, then deleted |
| worktree | `.team/run/worktrees/<id>/`, a `git worktree` on the story branch |
| land worktree | `.team/run/land/`, detached at the sprint head, made for each landing or revert |
| replay worktree | `.team/run/replay/`, detached at the target, for a boundary replay |

All of them are under `.team/run/`, which onboarding gitignores.

**Branch and worktree.** When a story's first step starts, the runner runs
`git branch <story_prefix><id> <sprint head>` and `git worktree add
.team/run/worktrees/<id> <branch>`, records `branch`, `base_sha` and
`worktree_head`, and logs `story-branch` (`action: "created"`). A story
that has a branch but no worktree (moved out of a sprint, or pruned) gets
its worktree back from the branch (`rebuilt`); no new branch is made. Every
step on the story runs in its worktree: its write scope, Stop hook,
commands, stop checks, gates and story-file reads. The run files
(`state.json`, events, ledger, relay, heartbeat) stay in the main
checkout's `.team/run/`, and so do the story's presentation
(`.team/run/presentation/<id>/`) and the Proxy's sandbox
(`.team/run/customer/<environment>/`). A step in a worktree is briefed
with their absolute paths, its presentation gaps name the same paths, and
its write scope reaches the main checkout's `.team/run/` within the role's
globs and nothing else in that checkout. The Proxy's brief names the
worktree as the repo holding the story file and
`.team/acceptance/<id>.md`, where the acceptance gate reads the report.
Storyless steps (the storyless architect, DevOps
and unit-tester, the boundary fix steps) run in the main checkout.

**Pushes and story PRs.** Once the team may push, the runner pushes the
story branch after every step that committed, against the recorded
`pushed` (see "Safety" under "Sprint boundaries"). A story with no PR gets a
draft PR from its branch to the sprint's branch (`<id>: <title>`). Every 60 s
at most, the runner reads each open story's PR checks on its pushed head;
a settled result that changed is saved as the story's `ci` and logged as
`story-ci` (`sha`, `verdict`, `source: "pr"`, `checks`). Each failing
Actions check is described with its failing step and its failing log lines
as soon as it is read, even while other checks are pending; nothing is
recorded until all have settled. The job and log are fetched once per commit
and check for the life of the run, and the verdict still comes from the
checks' buckets. `checks` lists each check that did not pass as
`- <label>: fail at step <step> <link>` with its lines indented below, as
for sprint CI (s172). A red result hands over `story_ci_red` with those
lines and holds nothing: only the landing CI decides. While the story's
latest PR CI is red, each developer step on it gets the same lines in a
`## Story CI` brief section. A
story not yet due is skipped before `gh` is asked anything. Whether `gh`
works (`gh --version`, then `gh auth status`, which costs an API request)
is checked once and a success is trusted for 10 minutes; a failure is
checked again on the next call. A failure whose output shows a rate limit
or a network error reads `gh could not check its login (rate limited or
offline): <line>`, not `gh is not logged in`.

**Land.** `land` is the last pipeline step, after `acceptance`, and the
runner runs it itself. A story is `done` only when its land passes, and
only then do stories that `depends_on` it start. Stories land one at a time,
in the landing order (see "Landing order" below); the others at `land` wait
(`waits to land after <id>`). A land before the first push waits for the
push permission. One land attempt:

1. `git worktree add --detach .team/run/land <sprint head>`, then
   `git merge --no-ff --no-edit -m "merge(<id>): <title>" <story branch>`.
   The first parent is the sprint head, and the story's commits keep their
   hashes. The runner makes no other merge commits, except a replay's
   copies of these.
2. **The story file.** When the merge touches `.team/stories/<id>.md`, the
   runner writes it as `git merge-file -p <story branch copy> <base copy>
   <sprint head copy>`: the story branch's copy wins and the sprint side's
   story-admin edits since the fork are re-applied. If they clash, the
   merge is dropped and the land holds (`gate_hold`): the PO has the
   liaison settle it with `story amend`, then calls `continue_story`.
3. **Any other conflict**: the merge is dropped and the story bounces at
   `land` (a round; `land_bounced`). A story rebase step goes to DevOps when
   every conflicting path is owned only by DevOps or by no role (CI, lock
   files, `.gitignore`, the toolchain config), else to the story's
   developer. When it is adopted, land runs again.
4. **Full checks** on the merge, in the land worktree. Red bounces the story
   to `implement` with the failures; the sprint branch never moved. In
   local mode (no remote, no `gh`, or the human's `no`) green fast-forwards
   at once and the land passes with `ci: "none"`.
5. **Landing CI.** The runner pushes the merge as a new branch
   `<story_prefix><id>-land`, records `landed` (`merge`, `pushed`), and
   polls the checks on that sha under `[gates] ci_timeout_s`, in the
   background, so other stories go on. Red or `main` bounces to
   `implement` with the check lines and clears `landed`. `infra` gets one
   re-run per job, then holds `ci_infra`. Still pending at the deadline
   holds `ci_pending`, never green. Each final verdict is logged as
   `story-ci` with `source: "landing"`. The landing branch is deleted in
   every case.
6. **Green.** Under the main checkout's lock, the runner first checks that
   the merge's first parent is still the sprint head. If it isn't (a
   story-admin commit, a settle or a storyless step moved it during the CI
   wait), the landing gives up its merge (below) and starts again, with no
   push. Otherwise it pushes the sprint branch to the merge (a fast-forward
   of its recorded `pushed`), sets `pushed` to the merge, fast-forwards the
   main checkout and records the checkout. A failed fast-forward halts as
   checkout drift, and `pushed` still names what the remote has. After the
   lock, the sprint's first landing opens the sprint's PR as a draft, the
   story's own PR is closed with `Landed on <branch> as <merge>.`, and the
   runner logs `story-landed` (`merge`, `parents`, `sprint_branch`,
   `pushed`, `ci`). The story is done. The story PR's base is the sprint
   branch, so the sprint push usually makes GitHub mark it merged. Then gh
   refuses the close and posts no note, and the runner reads the PR's state:
   a merged PR counts as closed (s166). This holds wherever the runner
   closes a PR (a superseded story or sprint PR too); any other failure to
   close is reported. In local mode the fast-forward takes
   the same lock and the same first-parent check.

**Giving up a merge.** A landing gives up its merge when the sprint head
moved under it, or when its sprint push was refused. It clears the story's
`landed` (a revert has none), deletes the landing branch under its lease (a
branch already gone is fine), and logs `landing-dropped` (`merge`, `why`:
`sprint head moved` or `sprint push refused`, `sprint_head`). It then merges
afresh onto the current sprint head and runs its checks and CI again. After
5 fresh starts in one turn the land holds (`the sprint branch kept moving`).
A landing never pushes a merge made on an older sprint head.

**A refused sprint push** is never retried as is. The landing gives up its
merge, fetches the remote head `R` and:

- when `R` descends from the runner's `pushed` (someone pushed a fix, or
  another landing moved it): if the main checkout already has `R`, only
  `pushed` becomes `R`; else the main checkout fast-forwards to `R`, the
  checkout is recorded, and `head` and `pushed` both become `R`. Either way
  the land merges afresh;
- otherwise, or when the fast-forward fails, the run halts as checkout drift
  (`the sprint branch <branch> on <remote> is at <sha>, which does not
  descend from the runner's <sha>; nothing was pushed`).

Known limit: the runner can't tell a lease refusal from another push failure
(branch protection, auth, the network). Such a refusal with an unmoved
remote re-lands up to the 5 fresh starts, then holds with `the sprint branch
kept moving` (ADR-0084).

**Resuming.** A run stopped after the landing push, or a held landing CI
that `continue_story` releases, resumes the CI wait on that sha with no new
merge or push, but only while the merge's first parent is still the sprint
head. Otherwise the landing gives up its merge and merges afresh at once.
Each attempt is the runner stage `story.land`; its detail holds the checks
summary and the CI verdict.

**The lock.** A landing's merge, checks, landing push and CI wait run in
`.team/run/land` and worker threads, without the main checkout's lock. While
it waits for CI, tells, answers, story requests, `accept-checkout --story`,
storyless steps and PO turns carry on. The lock is taken only for the
first-parent check, the sprint push and the move of the main checkout, on a
first landing and a resumed one alike.

**Landing order** (ADR-0088). The one landing now (`landing` in
`state.json`) finishes first, also after a restart. Behind it, the stories
waiting to land (at `land`, not held, with no queued story rebase), and the
queued landing reverts, go in this order:

1. the stories the PO placed with `order_landings(stories, reason)`, in its
   order;
2. every other one smallest first: fewest lines added plus deleted in `git
   diff --shortstat <base_sha>..<branch>` (for a revert, of the landed
   merge), ties by story id in number order (`s9` before `s10`). The team of
   a larger story has more context to resolve a merge conflict.

`order_landings` replaces the PO's placement (duplicates dropped). It is
refused, with nothing changed, for an empty list (`list the ids of the
stories waiting to land`), for the one landing now (`<id> is landing now;
order only the stories waiting behind it`), for a story that isn't waiting
(`<id> is not waiting to land; waiting: <ids>`), and for an order that
departs from smallest first with a blank reason (`this order departs from
smallest first (<ids>); give a reason`). An accepted call logs
`landing-order` (`order`, `placed`, `smallest`, `sizes`, `reason`) and
returns `{"status": "ordered", "order", "sizes"}`. A story whose landing
passes, holds, bounces or waits leaves the queue and loses its placement;
when it is ready again it rejoins smallest first. A revert and a land never
run at once, and a revert starts only on its turn and never while a
boundary is due.

**Files and the overlap hold** (ADR-0088). Every design has a `## Files`
section: one repo-relative path or `fnmatch` glob per line, until the next
heading (a leading `- ` or `* `, backticks and trailing notes are dropped).
The design gate bounces a `done` design without it (`<file> has no ## Files
section: list the files this story changes under it, one path or glob per
line`). When a story passes `design` with story branches on, the runner
compares its Files list with each other open sprint story past `design`:
that story's Files list (read from its branch) plus the files its branch
changed since its base (`git diff --name-only`). `.team/**`, the
architecture index and the design and requirement folders don't count. Two
entries overlap when either matches the other as a glob. On any overlap
the story stays at `design`, held as `overlap` (a per-story hand-over that
names the stories, the files each changes and the overlap), and
`overlap_with` records the others. On a tick after every one of them has
landed, left the sprint or been cancelled, the runner lifts the hold: it
drops the story's worktree (the branch stays, so the next step replays it
onto the current sprint head), moves the story past `design` and logs
`overlap-lifted` (`with`, `by: "runner"`, `reason`). `release_story(story,
reason)` lifts it early, with the reason required (`by: "po"`).
`continue_story` on an overlap hold is refused (`story <id> is held as
overlap with <ids>; it goes on when they land, or release_story lifts it
with a reason`). Known limits: globs are matched against each other, not
against the tree, and a held design keeps its worktree, so it counts toward
`max_open_stories`.

**Story rebases.** A landing conflict (with a round) or a carried story's
replay conflict (without one) records the story's `rebase` (`onto`, `base`,
`old`, `branch`, `files`, `role`). Before the step the runner runs, in the
worktree, `git checkout -B <story_prefix><id>-r<k>` (a leftover branch of
that name is reset to the old tip) and `git rebase --onto <onto> <base>`,
which stops at the conflict. A worktree already on that branch, or stopped
part-way through rebasing it, is left as it is and the step resumes it. The step may write only the
conflicting files, and its git is confined to the story's worktree (as a
DevOps rebase fix's is to its scratch worktree), so its `git add` and `git
rebase --continue` run there. That worktree shares the team repo's remotes,
refs and config, so its git is local only: the read-only list plus `add`,
`rm`, `mv`, `restore`, `checkout`, `switch`, `rebase`, `commit`, `stash`,
`reset`, `cherry-pick`, `apply`, `merge-file`, `mergetool`, `rerere` and a
few plumbing reads. `push`, `fetch`, `pull`, `remote`, `ls-remote`,
`config`, `worktree`, `submodule` and anything else are refused by rule
`git-local-only`, and so are `rebase --exec`/`-x` and `--interactive`/`-i`
(they run shell or an editor) and `checkout`/`switch
--ignore-other-worktrees`, abbreviations and short clusters (`-rx`)
included. Its brief says: resolve, `git add`, `git rebase
--continue`; never merge, squash, reorder or drop. After `done`, the runner
checks that no operation is in progress, the tree is clean, HEAD is on the
new branch and descends from `onto`, and the commits match the old
branch's by subject and in order. Then the story adopts the branch (remap,
`branch`, `base_sha`, `replays`, worktree head), pushes it with a new draft
PR and closes the old one. Otherwise the step bounces to the same role (a
round). A step that ends any other way (blocked, failed, no valid handoff)
or leaves the rebase in progress holds the story (`the story rebase onto
<onto> did not finish (<why>); nothing was committed or pushed, ...`): the
runner commits, quarantines and holds back nothing, keeps the recorded
worktree head, and leaves the worktree and the rebase as they stopped.
Released, the story re-runs the step: its stopped rebase is not counted as
worktree drift, and the role carries on from the conflict. A
story whose rebase is pending is never pushed, so its old branch and lease
stay as they were.

**Leaving and reverting.** A story that leaves the sprint (`start_sprint`
without it) or is cancelled loses its worktree but keeps its branch, and
its PR stays a draft; nothing of it reaches the sprint branch. The runner
never deletes a story branch. A cancel stops a running step at its next
tool call (a safe point; the step's commit and gate are skipped). The move
and cancel limits apply only to landed stories; a story at `land` can't be
moved or cancelled until its land ends (`story <id> is landing; it can't
leave the sprint until land ends`). `revert_story` on an unlanded story
removes its worktree and drops its `branch`, `base_sha`, `pushed`, `pr` and
sessions (the remote branch and PR stay), with no revert commit. On a
landed story it reverts the landing merge in the land worktree (`git revert
--no-edit -m 1 <merge>`) and lands the revert like a story: full checks, the
landing branch, CI, then the sprint-branch push and fast-forward. A
conflict, red checks or red CI refuse the revert, leave the sprint branch
untouched, and name the later landed stories whose merges touch the same
files. A started story that depends on it refuses it as before.

`state.json` per story (s159, all defaulted on load): `branch`,
`base_sha`, `replays`, `pushed`, `pr`, `landed` (`merge`, `pushed`, `pr`),
`worktree_head` (`""` = no worktree), `drift`, `in_flight`, `sessions`,
`ci` (`sha`, `verdict`, `source`), `land_reran`, `rebase` and (s163)
`overlap_with`. Run level: `story_branches`, `landing_order` and `landing`
(s163; an older file's `land_queue` is ignored), `permission_asked` and
`checkout_requests`. Events: `story-branch` (`action`: `created`,
`rebuilt`, `replayed`, `removed`, `dropped`; `branch`, `base_sha`,
`replays`), `story-landed` and `story-ci`; `step-end` gains `resumed` and
`cache_write`, and `checkout` gains `story`. s163 adds `landing-order`,
`landing-dropped`, `overlap-lifted` and `stack-dropped`, and the gate's
hold event carries `overlap` on an overlap hold.

### Parallel steps

The scheduler (ADR-0085) runs one task per story at a time (a role step, a
land, a revert landing or a story rebase), many stories at once. Each tick
it writes the queued run-file changes, stops starting work if a stop, halt,
re-pin or usage limit is due, applies the request queues (reorders, shares,
intake, clerk, reverts, checkout requests) for stories with no running
task, while nothing holds the main checkout's lock and no boundary stage
runs, lifts the overlap holds that are due, checks the main checkout, starts
a due boundary stage once nothing but the Manager is running, starts the
work the router offers within the caps, and starts a PO turn when
hand-overs are queued.

Between ticks the scheduler writes its own queued lines, then waits up to
5 s. A task that ends, or a write queued by another task (a step, a PO
turn, a boundary stage, a story CI poll) or a worker thread, ends the wait
at once. The scheduler's own writes, such as the `checkout.guard` stage
event of every tick, never end it, so an idle run ticks once per 5 s
(s164).

- **Caps.** A story with no worktree starts only while fewer than
  `[team] max_open_stories` stories have one (`waits for a free worktree`).
  Before any step the runner reserves budget for every running step: per
  `(role, model)`, `max(mean + 3σ, step_reserve_usd)` over at least 5 fresh
  finished steps, else `step_reserve_usd`. It starts nothing while spend
  plus the reserves reaches `budget_usd` (`waits for budget headroom`). A
  landing or a boundary stage, which the runner runs itself, neither waits
  for budget nor holds a reserve while it runs (s166). No running step is
  stopped for cost; the budget halt still applies.
- **The Manager** review runs beside the story tasks and blocks none of
  them; it takes the main checkout's lock only around its settle.
- **The main checkout** is used by one thing at a time, under one lock: a
  storyless step for its whole run (started by the router or by the PO's
  `run_role`; one rule decides for both), a landing's sprint push and
  fast-forward (not its CI wait), a boundary's sync and replay, a follow's
  fast-forward, and the PO's settle and the story-admin commits.
- **One writer.** Only the scheduler writes `state.json`, `events.jsonl`
  and `ledger.jsonl`. Steps and PO tool calls hand it their changes; git and
  commands run in worker threads that never touch the run state. The live
  meter writes its own files, one heartbeat entry per running step
  (`steps`, oldest first; `step` is the newest).
- **PO turns.** Hand-overs queue per story as they arrive. A PO turn takes
  every queued one in one prompt (kinds, lines and stories joined, in
  arrival order); later ones wait for the next turn. A hand-over leaves the
  queue only when its turn finished. Each turn starts with a snapshot of
  every story (step, status, hold, PO hold, rounds, landed). A tool call
  naming a story that moved since then is refused (`story <id> moved since
  your turn began; it is now <state>. Check it and retry`); the PO's own
  changes refresh its snapshot.
- **A due boundary** starts nothing new. The PO keeps getting turns, and
  the stage runs once only the Manager review, or nothing, is running. Each
  stage runs as a task: its checks, CI wait, git and `gh` calls run in
  worker threads, so PO turns, story-CI polls and the writer go on during
  it. Only the sync and the replay hold the main checkout's lock. The
  request queues wait until the stage ends. A sprint branch held on its CI
  is followed (a fix pushed to it) by its own task, at most once per beat.
- **Stop.** `stop` lets every running task finish and starts none. `stop
  --now` cancels them all; each story step is kept as interrupted (see
  "Interrupted steps") and the run halts `sigterm`.

Before story branches are switched on, the scheduler starts one step at a
time (`story branches are off: one step at a time`), the Manager does not
run beside other steps, and a story with no branch passes `land` at once.

### Kept sessions

Each role's session on a story is kept (`sessions[role]`: `session`,
`model`, `effort`, `provider`, `reported`) and resumed by the role's next
step on that story when the model, effort and provider are the same;
otherwise the step starts fresh (ADR-0086). A kept session ends:

- for all roles, when the story is done, cancelled or reverted, or a bounce
  or return sends it to an earlier step;
- for one role on every story, when an `override` (an `upgrade_model`
  ruling) changes that role's model;
- for one role on one story, when a resumed query fails on the context
  limit; that step reports `error` and the next starts fresh. A session that
  only grows past the limit is compacted by the SDK.

A resumed step's ledger entry is the session's cost delta, marked
`resumed`; reconciled estimates are marked `estimated`. The reserve uses
only fresh, measured steps. The dashboard's Time chart splits each role's
bar into fresh and resumed parts.

### Waiting and limits

- **Waiting on the human** (ADR-0087). A run with nothing to do but wait (an
  open question, a stuck Sprint Backlog, a cap, `notify_user(kind="blocked")`)
  stays `running`, with `status_reason` saying why, and polls every 5 s; an
  answer or a `tell` reaches the PO within one tick. Only `done`,
  `checkout-changed`, `blocked` (the budget), `limit` and `sprint-end` under
  the sprint cadence end it, plus `notify_user(kind="done")` and a stop.
  While it waits, the heartbeat (and `$UNATTENDED_HEARTBEAT` when set)
  carries `"waiting": <reason>`.
- **Usage limit.** A step that hits a limit fails on its own and is kept as
  interrupted; no new step starts; a land already waiting on CI finishes
  its wait. Once nothing runs, the run halts `limit` with the reset text in
  `status_reason` and exits 75. A PO turn cut off by the limit keeps its
  session, and its hand-overs stay queued.
- **Hold and cancel** take effect at a safe point: a PO hold on a story with
  a running step only stops its next start; a cancel stops the step at its
  next tool call.

### Switching over

`state.json` `story_branches` starts `false`. The first `start_sprint`
after the upgrade switches it on, and refuses (`story branches can't start
yet:` and one line per reason) while any of these holds: a listed story is
past `design`; `.team/pending-tests.json` names a story with tests; the
review stack still has an entry; `git cherry <target> HEAD` lists a `+`
line (a team commit the target lacks, even as a rebased copy). After the
switch the check never runs again. A Product
Backlog story already past design keeps its step and gets its branch from
the sprint head when it next starts.

**Stack entries main already has** (s163). Every `start_sprint`, after its
sprint, dependency and leaving checks and before the switch check, fetches
and drops each review-stack entry whose head the target already has:
`merge-base --is-ancestor <head> <target>` (`why: "contained"`), or `git
cherry <target> <head>` with no `+` line (`why: "patch-equivalent"`). Each
drop logs `stack-dropped` (`sprint`, `branch`, `head`, `pr`, `why`). An
entry with no head, or whose check fails, stays; with no upstream or a
failed fetch nothing is dropped. So a sprint that main took by rebase never
needs a hand edit of the state.

## Sprint boundaries: sync, full checks, the sprint's PR

At each sprint's start and end the runner runs a **boundary**: code steps,
not prompts, that no role can skip. It is saved as `state.json` `boundary`
(`edge` `start`/`end`, `sprint`, `stage`, `hold`, `failure`, `streak`,
`rounds`, `escalated`, `note`, `sync_from`) until it finishes. A saved
boundary from before s151 at `review` or `restack` loads at `push`; a
`review_check` or `review_conflict` failure and the old `restack` key are
dropped. Each stage logs
a `boundary` event (`edge`, `sprint`, `stage`, `outcome`, plus `note`,
`reason`, `sha`, `files`, `branch`, `branches`, `checks`, `hold`, `key`,
`count`, `history`, `ci`, `prs`, `results`, `story` where they apply). While a boundary is pending, no story
in the current sprint moves: `run_role` of a gated role on one is refused
with `sprint N <edge> boundary is at <stage>…; the sprint's stories move
once it passes`.

**Skipped.** With `[upstream] remote = ""`, no such remote, a failed
`git fetch` or no `<remote>/<branch>`, the whole boundary is skipped with
one `skipped` event and a note. This is not an error. (At a sprint end whose
fetch failed, the sprint's entry is still recorded.)

**Start** (opened by `start_sprint`, before any role runs, including the
Manager):

The start's stages are `sync, check, push-replayed, open`; the end's are
`sync, check, push, ci, replay, push-replayed, ci-replayed` (s159,
ADR-0084). A saved boundary at an old stage loads at its new one: `rebase`
at `replay`, `push-rebased` at `push-replayed`, `ci-rebased` at
`ci-replayed`. The old `sync_from` key loads as the replay's `old_head`.

1. **sync** (s152, s159): fetch and record the sprint branch. A branch
   already on the target (`git rev-list --count HEAD..<remote>/<branch>` is
   0, and no replay is pinned) is left alone: the stage logs `current` with
   `behind: 0` and the note `the team branch is current with
   <remote>/<branch>`. Otherwise it **replays** the sprint branch onto the
   target (see "Replay" below), from the last end's first-parent line
   (`upstream.last_end`) or, when that is empty, from the merge base, and
   remaps every recorded hash. A pinned replay always resumes and remaps,
   so a crash in the middle is finished on resume. A **conflict** is
   aborted, the sprint branch is unchanged, and nothing is held: the stage
   logs `conflict` (`files`, `commit`, `subject`, `note`), the liaison gets
   an `update` (`Sprint N start: rebasing <team> onto <target> stopped at
   <commit> "<subject>" with conflicts in: <files>. …`), and the boundary
   goes on to **check**. A start conflict never goes to DevOps. Git
   stopping for another reason, or a path only one side touched, holds
   `error` as at the end. Within a sprint the sprint branch is never
   replayed; a change the team needs sooner comes in as a pick (see "Picks
   (mid-sprint)" below).
2. **check**: the full checks on the sprint branch (skipped when HEAD is the
   sha that last passed them). A failure
   at the start **holds nothing** (s152): no DevOps fix step, no setback,
   no escalation, and `upstream.checked` is not set. The failing tests are
   the sprint's **known failures**: for each failed check, the JUnit ids of
   its failed cases (`tests/test_x.py::test_y`), or the check's name
   (`lint`, `coverage`, `e2e:<env>`) when it has none. The boundary
   finishes with one `done` event carrying `known_failures`, `sha`,
   `reason` (the failed checks' text) and `checks`. They are on that event,
   not on `sprint-start`, which `start_sprint` logs before the boundary
   runs. The liaison gets an `update` (`Sprint N starts with K known
   failures on <team> at <sha12>: <ids>. Nothing is held and the sprint
   goes on; the PO asks you for a story for them (request_story).`), and
   the PO gets the `known_failures` hand-over: unless an open story
   already covers them, it asks the liaison for a story with
   `request_story`, with the failing output as evidence. The liaison writes
   it and places it with `story new --sprint current` (the top of this
   sprint) or `next`, `backlog` or `--after <id>` (later).
3. **push-replayed**: only when `sync` replayed and the newest stack
   entry's PR is still open. It pushes the replayed head to that entry's
   next branch `<prefix><N>-r<k+1>`, as the end's **push-replayed** does,
   once the team may push. With an empty stack, or a merged PR, nothing is
   pushed.
4. **open** (s159, AC2.17): the sprint's own stack entry. It creates the
   remote branch `<prefix><N>` at the start head (a new branch; deferred
   while the push permission is `unasked`) and appends the entry
   (`sprint`, `branch`, `start`, `end`, `head` = the start head, `pushed`
   = that head or `""`), logging `opened`. The end's **sync** reuses this
   entry. Then it replays every **carried story**: one in the new sprint,
   not landed, whose branch was made from an older sprint head. In the
   story's worktree (rebuilt if needed) the runner stashes a cut-off
   step's edits (`git stash push --include-untracked -m
   agile-team-replay`), runs `git checkout -b <story_prefix><id>-r<k>` and
   `git rebase --onto <head> <base_sha>`, and pops the stash. On success it
   remaps the story's shas and records the new `branch`, `base_sha`,
   `replays` and worktree head. Once the team may push, it pushes the new
   branch, opens a new draft PR and closes the old one with a link. The old
   branch and the role sessions are kept. A conflict is aborted (the stash
   stays) and becomes a story rebase step with no round (see "Story
   rebases"); the boundary goes on. A Product Backlog story with a branch
   is replayed the same way when it next starts.

**End** (opened when the sprint is finished: every sprint story is done,
cancelled or reverted (s124), before the `sprint_end` hand-over). The stages run in this order:

1. **sync**: fetch, record the sprint branch, and take the sprint's own
   entry, made by the start's **open** (s159; an older run without one adds
   it here: branch `<prefix><N>`, range `start..end`, start = the previous
   entry's end, or `git merge-base HEAD <remote>/<branch>` for the first
   one). A sprint that landed nothing (`head` is still `start`) finishes
   the boundary at once with `sprint N added no commit since the last
   sprint end; nothing to push or rebase`. Otherwise every earlier entry leaves
   `upstream.stack` with a `superseded` event (`sprint K's PR #n is
   superseded: sprint N's branch holds its commits`). Its PR number goes
   into the new PR's body, and its PR is left open: the runner closes
   nothing. After an end sync the stack holds only the sprint's own entry.
2. **check**: the full checks on the sprint branch.
3. **push**, the sprint branch as built (s151, s159; needs `gh` and
   permission): when its HEAD, with any fix commits from **check**, moved
   past the sha last pushed to `<prefix><N>` by the landings, it is pushed
   as it is (a fast-forward, see "Pushes"). No local `<prefix><N>` branch
   is made. The entry copies `branch`, `pushed` and `pr` into `as_is_branch`,
   `as_is` and `as_is_pr`. The sprint's PR is the draft opened at its
   first landing, and it stays a draft; an older run with no PR gets one
   here (found, or created ready with base `[upstream] branch`), and only
   then does the liaison get `Sprint N's branch <prefix><N> holds the team
   branch as built (<sha>): PR #n <url>. …`. While the push permission is
   `unasked`, the stage raises `push_permission` (once per run) and waits,
   holding nothing. Without `gh`, or with the human's `no`, nothing is pushed:
   the boundary finishes with the local report (`… is checked but not
   pushed (<why>). No CI result exists. The team branch is not rebased onto
   <remote>/<branch>: the rebase waits for green CI.`).

   A refused push holds `push_rejected` and the stage stays;
   `continue_boundary` reruns it, and a sha already pushed is not pushed
   again.
4. **ci** (s81), the gate: for the sprint's PR the runner runs
   `gh pr checks <n> --watch`, all under one deadline of `[gates]
   ci_timeout_s` (default 1800 s). It then reads `gh pr checks <n> --required --json
   name,state,bucket,link,workflow`, or every check when the repo marks none as
   required (s111). While no checks are reported yet (right
   after a push), it looks again every 10 s, at most 12 times. For each
   failing or cancelled Actions check it reads `gh run view --job <id>
   --log-failed` and keeps the lines that name the failure, by tier (s172).
   The test tier is pytest `FAILED …` and `ERROR …::`, go `--- FAIL:` and
   `N failed` (not a linter's `Found N errors`). Only if no test line is
   there does it keep the lint findings: `::error file=…,line=…::msg` or
   `##[error]msg` annotations (not `Process completed with exit code`),
   ruff's `path:line:col: CODE msg`, its two-line `-->` form joined into
   one, house-rules' `path:line: fail …` lines, and `Would reformat:`.
   Warnings never count. It keeps at most 20 lines, and the last 10 lines
   when neither tier has a hit. For each Actions check the runner also reads its job
   (`gh api repos/{owner}/{repo}/actions/jobs/<id>`: commit and steps) and
   gives the check a **kind** (s111, `ci_triage.py`):
   - `stale`: its job ran on another commit than the one the runner
     pushed. It is ignored, so it counts as not reported yet.
   - `green`, `skipped`, `pending`: from its bucket.
   - `ours`: it failed or was cancelled after a step ran (GitHub's `Set up
     job` and `Complete job` don't count). A failing check with no job is
     `ours` too.
   - `infra`: it failed or was cancelled with no step run.
   - `main`: an `ours` check whose name and failing step also fail on
     `[upstream] branch`'s head (`gh api …/commits/<branch>/check-runs`,
     read only when something is `ours`).

   The result is saved on the sprint's entry as `ci` (`pr`, `url`,
   `head`, `verdict`, `checks` with `name`, `workflow`, `bucket`, `link`,
   `lines`, `kind`, `step`, `head`). It is also logged on the stage's `boundary` event (`ci`, `prs`,
   `checks`, `results`). A PR's verdict is the first of red (`ours`), infra,
   main, pending (`pending`, `stale`, `rerun`) and green among its checks.
   A PR with no checks makes it **none**. No merge is followed at this
   stage: a PR merged during the wait is handled at the next sprint end.
   Verdicts:
   - **green** (every check passed on the pushed head or was skipped, at
     least one passed): a `pass` event, and the boundary moves on to
     **replay**. Nothing is called ready yet. Green is the gate: nothing is
     replayed before it. (The `ci` stage reads the sprint's PR whether it
     is a draft or ready.)
   - **red** (a check is `ours`, even with others still pending): the
     boundary is held `ci_failed`, and nothing is rebased. The liaison gets
     an `update`: `Sprint N's CI failed on the team branch as built (<prs>);
     the boundary holds and nothing is rebased:` and the check lines. The
     PO gets the failing checks with job
     names, failing steps and test lines. `continue_boundary` is
     **refused** (it names each job and step, and "flaky" is no reason).
     The PO asks the liaison for a bug story at once (`request_story`), or
     picks an open story that fixes it, calls `record_ci_bug(story)` once
     the story is open and tells the human the PR is NOT ready.
   - **infra** (a check is `infra`): the runner re-runs each such job once
     for the pushed head (`gh run rerun --job <id>`; the key is kept in the
     entry's `reran`). It emits a `rerun` boundary event, waits until GitHub
     shows the new attempt, and reads the checks again on the next tick.
     A check whose re-run also runs no step holds `ci_infra`.
     `continue_boundary` reads again with no further re-run, and
     `record_ci_bug(story)` ends the boundary, not done (`ci: infra`).
   - **main** (a check is `main`): held `main_broken`. The PO asks the liaison
     for a bug story for main (`request_story`) and, once the runner has
     opened it, calls `record_ci_bug(story)`, which ends the
     boundary with `ci: main` and the `Review:` text "Sprint N ended, CI
     blocked by main …". The sprint is not done and its PR stays unmerged.
     The story goes first in the next sprint, and the next sprint's PR,
     which holds these commits too, is watched at the next sprint end.
   - **pending** (the deadline passed, or a check ran on another commit):
     held `ci_pending`, naming the running checks. The PR is not ready;
     `continue_boundary` waits again.
   - **none** (no checks reported, only skipped ones, a closed PR, or no
     open PR): the boundary finishes. The human is told that no CI result
     exists, that the PR is not called ready, and that the team branch is
     not rebased (the rebase waits for green CI).

   A `record_ci_bug(story)` after `ci_failed`, `ci_infra` or `main_broken`
   ends the boundary without a rebase, and its text says so too. Note that
   GitHub runs no `pull_request` workflow on a PR that conflicts with its
   base, so an as-built branch that conflicts with main gets **none**, and
   the team branch stays where it is until the human rebases it.

   The CI stages block the router while they wait, as a runner chore
   (`sprint boundary: ci`), so health stays green. If the run is stopped
   during the wait, resume waits again. The sprint-end hand-over then says
   `Review: …` with the CI text.

   **A fix pushed by hand is followed** (s159, AC2.14). While the boundary
   holds `ci_failed`, `ci_infra` or `ci_pending`, the runner reads the
   remote sprint branch at most once per health beat. When it moved past
   the sha the runner pushed, the runner fetches, fast-forwards the sprint
   branch to it, records the checkout, logs `followed`, clears the hold and
   reads CI again for the new head. If it can't fast-forward, the run halts
   as checkout drift naming both heads. `continue_boundary` at `ci_failed`
   is accepted once the pushed head differs from the head CI was read on.
5. **replay** (only after green): the stage first checks the gate in code
   (`boundary.get_rebase_refusal`): the sprint's entry must have a CI read
   that is green on the sha it pushed. If not, nothing runs: no fetch, no
   git call, no hash rewritten. The boundary holds `error` with a
   `refused` event (`the rebase waits for green CI on the team branch as
   built: <branch> at <sha> has <verdict>`), and its stage goes back to
   **ci**, so `continue_boundary` waits for CI again. After the gate it
   fetches and **replays** the sprint branch onto `<remote>/<branch>` (see
   "Replay" below). There is never `-s ours` or `-X ours` (s59, ADR-012).
   `upstream.checked` is not rewritten, so the full checks run again. A
   path only one side touched must keep that side's version. Otherwise the
   sprint branch stays where it was and the boundary holds `error`.

   **A conflict goes to DevOps** (s151 AC6, s159, ADR-0076, ADR-0084). The
   replay stops in the replay worktree `.team/run/replay` on the scratch
   branch `agile-team/replay-sprint-<N>`, and the sprint branch is
   unchanged. The runner emits `conflict` (no hold) and runs a `rebase-fix`
   step for `devops`. Its brief names the stopped story and commit, its
   subject and files, the worktree and the branch. The step may write only
   the worktree, and git may change only the worktree (`GIT_EDITOR=true`).
   DevOps resolves the conflicting files, keeping both sides' intent, and
   finishes the stopped rebase or cherry-pick; it never merges, squashes,
   reorders, rewords, skips or drops a commit. When it is back, the runner
   checks, in order: the operation is finished, the worktree is clean, HEAD
   is on the scratch branch and descends from the replay's tip, and the
   stopped story's commits match the old ones by subject and in order,
   with none of them a merge. No path only one side touched may change. If
   all pass, the replay goes on from the next commit (re-making the story
   merge first when it stopped inside a story). A new conflict is a new
   DevOps step, under the boundary's rounds. A sprint whose line holds no
   story merge (one run before the switch to story branches) is still
   rebased as in s151. Its conflict stops in `.team/run/rebase` on
   `agile-team/rebase-sprint-<N>`, and the brief gives s151's rebase text.
   On either path, if DevOps can't resolve it or a check fails, it holds
   `rebase_conflict`: the PO's handover and an `update` to the liaison
   carry the conflict, the reason, DevOps's notes and the scratch branch,
   which is kept. `continue_boundary(note)` starts a new DevOps step with
   the note. `sync_conflict` is no longer emitted; a saved boundary held
   there still loads.

   If git stops the replay for a reason other than a conflict (for
   example, an untracked file would be overwritten), the boundary holds
   `error`. Hashes quoted in reviews and stories are not rewritten. The
   replayed sprint branch is checked at the next start's **check**.
6. **push-replayed**: when the replay changed nothing (HEAD is still the
   sha pushed at **push**), a `pass` event (`the rebase changed nothing;
   <branch> stays at <sha>`), the draft PR is made ready, and the boundary
   finishes green: the as-built CI is that head's CI, and the PO gets
   `ci_green`. Otherwise the runner pushes the replayed HEAD as a **new
   branch** `<prefix><N>-r<k>` (`k = replays + 1`) and opens a ready PR
   from it. It closes the old draft PR with `Replayed onto <target> as
   <url>; this PR is superseded.` and keeps the old branch. The entry's
   `branch`, `head`, `pushed`, `pr`, `url` and `mode` now describe the
   replay branch, and `replays = k`. Nothing is force-pushed. A refused
   push holds `push_rejected`.
7. **ci-replayed**: the same CI read as **ci**, for the replayed head. Its
   result replaces the entry's `ci`, so the Board shows the PR's current
   head. An `infra` check still gets its one re-run (keyed by the new head).
   - **green**: the boundary finishes and the sprint is done. The PO gets
     `ci_green` ("ready to merge") and tells the human. This is the only
     way a sprint is done: no tool, note or answer can do it.
   - **anything else** (red, main, pending, none, infra after its re-run):
     the boundary still finishes, **never held**, with `ci: <verdict>` on
     the `done` event. The PO's `Review:` text and the liaison's `update`
     read `Sprint N's CI was green on the team branch as built (<sha>),
     and is <verdict> on it rebased onto <remote>/<branch> (<prs>). The PR
     is NOT ready; do not merge it.`, with the check lines. The PO asks the
     liaison for a bug story when the failure is ours.

**Replay** (s159, ADR-0084). A replay copies the sprint branch's
first-parent line onto a target in the replay worktree `.team/run/replay`
(detached at the target). For each commit of `git rev-list --first-parent
--reverse <base>..<head>`:

- a story merge `M` (two parents): `git rebase --onto <tip> M^1 M^2` (empty
  commits kept), then `git checkout --detach <tip>` and `git merge --no-ff
  --no-edit -m "<M's full message>" <rebased tip>`, so the story stays one
  merge with its own commits;
- any other commit (a story-admin commit, a boundary fix):
  `git cherry-pick --allow-empty <c>`.

The progress (`boundary.replay`: `old_head`, `base`, `target`, `done`,
`tip`, `story`, `moved`) is saved after each commit, so a crash or a
conflict resumes at the right place. When it finishes, the runner moves the
sprint branch to the tip only if the branch is still where the replay
started, records the checkout, removes the worktree, and remaps every
recorded hash **story by story**: each story's commits pair with their
copies by subject and in order, each merge pairs with the copy whose subject
is `merge(<id>): …` for the same id, and other commits pair by subject, in
order. The remap rewrites each story's `commit`, `code_commits` and
interrupted sha, each open story's `base_sha`, each `landed.merge`, each
revert record's `merge` and `revert`, the run's interrupted shas,
`upstream.last_end` and the entry's `start`/`end` (never `as_is`, `pushed`
or `ci`).

**main moves only by fast-forward** (s159, AC2.8). The runner never pushes
main; the push guard refuses it. The PR body, the green report and the
`ci_green` line give the command (`git push <remote> <sha>:<branch>`); the
human or the liaison runs it. No text says "Rebase and merge": it would
rewrite the story merges.

**Full checks**: the `[toolchain]` `lint`, `static` and `coverage` commands
(coverage must reach the gate or the baseline), then each acceptance
environment's `e2e` command. The boundary runs the suite **once** (s73), as
the `coverage` command: that one run proves the suite green and gives the
coverage figure. `test` runs only when no `coverage` command is set. Every configured check runs, and the failed ones
are quoted (`<name> failed (<why>): <command>` plus the last 30 lines). For
the coverage check, a failing suite gives `exit N`, and a coverage
shortfall gives `coverage X% is below Y%`. A shortfall gives that text
whether the run exited 0 or pytest-cov's `fail_under` stopped it with no
failing test. That is the same rule the implement gate uses
(`gates.coverage_shortfall`, s68). A non-zero exit never passes.

**Failures.** At a sprint end (at a start they are known failures, see
**Start** above), a failed full check becomes a **DevOps fix step**, whose
brief quotes the output. It is fixed on the team branch. For that step
DevOps may also write source, tests and e2e tests, and the runner commits
it and checks again. (Since s151 there is no review branch to rebuild and
no review worktree; `.team/run/review/` from an older run is left alone.)
A fix step that hands over (blocked, questions…) holds the
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

**Permission.** The run asks once, before its first push of any kind (a
story branch, a landing, the sprint branch at the start's **open**, or a
boundary push; s159): the PO gets `push_permission`, asks the human once,
and records the answer with `set_push_permission` (`yes` or `no`).
`state.json` keeps it in `upstream.push` for every later sprint, and
`permission_asked` keeps the hand-over from being raised twice. Until the
answer, steps commit and nothing is pushed. With `no`, or without `gh`
(missing or logged out), nothing is pushed: landings pass on green full
checks alone, and the boundary finishes after **check**, the human is told
the branch name, that no CI result exists and that the sprint is not
replayed (`done` event with `ci: none`).

**Safety** (s159, ADR-0084: no push replaces a branch's history). The
runner pushes only branches that start with `[upstream] prefix` or
`story_prefix`, never the checked-out branch, never `[upstream] branch`. It
pushes a sha (`<sha>:refs/heads/<branch>`), so no local sprint branch is
made. Every push names the sha it expects the remote branch to be at (the
recorded `pushed`, or nothing for a new branch) as
`--force-with-lease=refs/heads/<b>:<expect>`, and the runner first checks
that the new sha descends from it (`git merge-base --is-ancestor`); if not,
it sends nothing and reports `NOT_FAST_FORWARD` as `push_rejected`. A bare
`--force-with-lease` or `--force` never appears. A refused push is never
retried with another expected sha. The only branches the runner deletes
are its landing branches (`<story_prefix><id>-land`). Roles still cannot
run git commands that write.

**PO tools.** `continue_boundary(note)` releases a held boundary. Its stage
reruns, and the note reaches the next fix brief. After an escalation it
also resets the streak and rounds. At the `ci` stage it waits for the checks
again; at `ci_failed` it is refused (s111). `set_push_permission(answer)`.
`record_ci_bug(story)` works only while the boundary is held `ci_failed`,
`ci_infra` or `main_broken`, and only for a story that exists and is not
done. It records the story in `upstream.ci_bug` and finishes the boundary
with a `done` event (`ci: red`, `infra` or `main`, `story`), never green.
The `Review:` text reads `checks failed, story sN opened`, or, at
`main_broken`, `Sprint N ended, CI blocked by main …`. While `ci_bug` names a story that is not
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
on `ci_failed` the PO reads the failing lines first, then opens the bug
story and `record_ci_bug`s it. Since s111 the runner enforces the rule
itself. It reads each job's commit and steps from GitHub, and counts a green
run only on the pushed head. It re-runs, once, a job that never ran a step
(`no runner was assigned`, or a cancel whose steps never started), and
refuses `continue_boundary` at `ci_failed`, where our code ran. A failure
that main's head has too is `main_broken`: the sprint ends as "ended, CI
blocked by main", not done, and the team carries on.

`state.json` `upstream`: `team_branch`, `push` (`unasked`/`yes`/`no`),
`stack` (after an end sync, only the sprint's own entry: `sprint`,
`branch`, `start`, `end`, `title`, `stories`, `head`, `pushed`, `as_is`
(the sha of the as-built push, s151), `as_is_branch` and `as_is_pr` (the
branch and PR it went to, s159), `replays` (the `k` of the newest
`-r<k>` branch), `supersedes` (earlier sprints' PR numbers still open),
`pr`, `url`, `base`, `mode`, `ci` (the latest CI read: the
as-built one until **ci-replayed** replaces it), `reran`, `reverted`, and
`commits`: the PR's commit count against main, set at each push; the old
`checked` and `check` keys are dropped on load),
`last_end`, `checked` (the last team sha that passed), `closed` (the last
sprint whose end boundary finished), `report` and `ci_bug` (the bug story
for a failed CI, until a sprint lists it first).

CI: the sprint's PR is based on main, a draft while the sprint is built and
watched as built, then replaced by the ready PR of the replay branch, which
is watched again. Once `ci_green` says it is ready, main is fast-forwarded
to its head (the command is in the report). It holds the commits of any
earlier sprint PR still open, so those can then be closed. For a PR of more
than 100 commits the push, green and none reports add `PR #<n> (<branch>)
has <count> commits, more than the 100 GitHub merges in one step. Merge it
by fast-forward: git fetch <remote> && git push <remote> <sha>:<target>`.

Boundary outcomes since s151: `pushed` (each push: `branch`, `sha`, and
`as_is` on the second), `superseded` (an earlier entry left the stack),
`refused` (the replay gate; warning), and since s159 `opened` (the start's
stack entry) and `followed` (a fix pushed by hand). The s108 outcomes `restacked`,
`rebuild`, `merged` and `built` are no longer logged, and old
`events.jsonl` lines with them still render. Stage names in `runner-stage`
events: `boundary.sync`, `boundary.check`, `boundary.push`,
`boundary.ci-wait`, `boundary.replay`, `boundary.push-replayed`,
`boundary.ci-replayed`, `boundary.open`, and `story.land` for each land
attempt (old lines may name `boundary.rebase`, `boundary.push-rebased`,
`boundary.ci-rebased`, `boundary.review` or
`boundary.restack`).

### Picks (mid-sprint) (s141)

Mid-sprint, the team branch takes nothing from main by merge or rebase. A
change the team needs now comes in as a **pick**: one commit or a range
`A..B`, from main or from an open PR, cherry-picked onto the team branch
between steps, with no hash rewritten. Picks are for a change needed now (a
test fix, a charter rule, a fix the team is blocked on), never for whole
sprints of work. Design: `docs/design/s141.md`; ADR-0072.

- **Asking.** Requests come from three places, all through one queue,
  `.team/run/picks/p<N>.json` (`{commits: [{sha, subject}], reason, kind,
  at}`, full shas oldest first). The file is never rewritten:

  | kind | how | asked by | decided |
  |---|---|---|---|
  | `request` | `agile-team pick SPEC --reason R` | `liaison` | the PO: `accept_pick` / `deny_pick` |
  | `forced` | `agile-team pick SPEC --reason R --force` (TTY, sha12 typed back) | `human` | `forced`: no PO decision |
  | `own` | the PO's `pick_commits(commits, reason)` | `product-owner` | `own`: no accept step |

  **The runner never fetches.** Whoever asks makes sure the commits are in
  the local repo.
- **Checks.** Every check runs, and on any refusal every reason is given and
  nothing is queued: a blank reason; a spec that is not a commit or `A..B`;
  a side that is not a commit in the local repo; an empty range; and for
  each commit, a merge (or root) commit, an ancestor of HEAD, or a commit
  whose patch is already on the team branch (`git cherry`). Asking uses only
  read-only git and works in any run state.
- **The safe point.** At each router tick, after the story intake and
  before anything is handed to the PO, the runner handles the queue. It
  never does this while a sprint boundary is open. It receives new
  requests in number order: a `request` becomes `pending` and is handed to
  the PO once as `pick-request`, while a `forced` or `own` one is applied at
  once. It then applies every `accepted` pick.
- **Applying.** The commit checks run again. A dirty tree gives `failed`
  (`the working tree has changes (…); nothing was picked`). Otherwise the
  runner runs `git -c core.hooksPath=/dev/null -c core.editor=true
  cherry-pick -x <sha>…` over every commit, oldest first, so each source
  commit becomes its own commit with its author and message, plus
  `(cherry picked from commit <sha>)` and no `Co-Authored-By` trailer. It
  keeps the pick's patch in `.team/run/picks/patches/p<N>.patch` and
  records the new HEAD for the checkout guard. On a **conflict in any
  commit**, the whole pick is aborted (`cherry-pick --abort`, then a reset
  to the old HEAD if needed), and the outcome is `conflict` with the files.
  Any other failure, an empty result included, is `failed`. The branch
  always ends where it was.
- **Records.** `state.json` `picks` maps each id to `{status, sprint, shas,
  why, revert}`. Each outcome logs a `pick` event (role = who asked;
  `request`, `kind`, `decided` (`accepted`, `forced`, `own`), `asked_by`,
  `reason`, `commits`, `subjects`, `target`, `on_target` (one bool per
  commit), `outcome`, `shas` (new commits), `files`, `why`). It also posts
  an `update` to the liaison, who tells the human, and adds a hand-over
  line: `pick-forced` for an applied forced pick, otherwise `pick-settled`.
- **Deciding.** `accept_pick(request)` and `deny_pick(request, reason)`
  work only on a `pending` request. A denial logs `pick-denied`, posts the
  reason to the liaison and the human, and leaves the branch alone. An
  unanswered request stays `pending`: `status` lists it in `pending_picks`,
  and the dashboard's Questions tab shows it under "Picks waiting on the
  PO".
- **Reverting.** `revert_pick(pick, reason)` reverts an accepted pick or the
  PO's own, applied this sprint, in **one** revert commit (with the
  runner's trailer). It logs `pick-reverted` and posts to the liaison. It
  refuses a forced pick (`<id> was forced by the human; a forced pick can't
  be reverted`), a pick not in force this sprint, a blank reason, an open
  boundary, and a moved checkout.
- **Picks stay applied.** A pick is in force when it was applied this sprint
  and not reverted. Every story step's gate (unless the hand-off is
  `blocked` or `failed`) checks each pick in force with `git apply --reverse
  --check <patch>`. A step that undid one bounces back to itself, with the
  reason `this step undid pick <id> (…)`. A step that must change picked
  lines needs the PO to `revert_pick` first.
- **The sprint end doesn't change.** Picks and their reverts are ordinary
  commits in the sprint's history and are pushed as they are. At the END
  rebase, git drops a pick whose patch main already has, as it would any
  commit.

### Self re-pin (s128)

This applies only when the runner runs from `.team/run/runner-pin`
(self-hosting, see `self-hosting.md`). Installed skills never re-pin.

1. When the end boundary's `check` stage passes (or finds the head already
   checked) and the head differs from `runner-pin.commit`, the runner records
   `repin` in `state.json`. The boundary has already moved on to its next
   stage. The start edge and a skipped boundary never re-pin.
2. The router loop ends with no hand-over, and the status is `idle` with
   `re-pinning the runner at <sha7>`. The runner removes `runner.pid` and runs
   `sh agile-team/runner/scripts/pin-runner.sh <head>`, which keeps the old pin
   as `runner-pin.prev`. Then it runs
   `uv run --frozen --quiet --project .team/run/runner-pin agile-team --repo <repo>
   [--home <home>] config check`. The run's `--repo` and `--home` always go
   before the subcommand, where the CLI accepts them (s158).
3. If both pass, it writes `repin.json` (`trial`) and replaces its own process
   (`os.execv`, same pid) with `.team/run/runner-pin/.venv/bin/agile-team --repo
   <repo> [--home <home>] start --resume`. An unattended job sees no exit. The new runner
   logs one `runner-repin` event `{"old", "new", "sprint", "outcome":
   "pinned", "reason": ""}` and removes the marker. The rest of the boundary
   runs on the new code.
4. If the pin script, the config check or the exec fails, or the new runner's
   start fails before its loop, the runner runs `pin-runner.sh --rollback`
   (only if the swap happened). The restored old pin then takes over through
   the same exec. It logs `runner-repin` with `"outcome": "rolled_back"` and
   the reason, and posts an `update` naming both commits. The failed pin stays
   in `runner-pin.failed`.
5. A stop requested at the same time wins. `repin` stays in `state.json`, and
   the next `start --resume` re-pins first. A start that is not pinned drops a
   leftover `repin`.

## Enforcement

- Stop hook (s126): a `done` handoff ends the step only after the role's stop
  checks pass, or after 3 refusals, or once the stop-check budget is spent.
  See "Stop checks (s126)".
- PreToolUse hook: Write/Edit/NotebookEdit outside the role's write globs are
  denied. The Customer Proxy's Read/Grep/Glob are limited to its sandbox
  (which holds the presentation copy), `.team/stories/`, `.team/acceptance/`
  (so it can read and rewrite its own report) and `<docs>/customer/`; its
  Bash may not name a forbidden root, `..`, or repo paths outside the
  sandbox. The Integration Tester may also write `.team/run/presentation/**`;
  from a story worktree that is the main checkout's, the only part of the
  main checkout a worktree step may write (within its globs).
- Runner-only files: every story file, `.team/stories/**` (s135). The hook refuses any role's Write/Edit/NotebookEdit
  there, whatever its write globs say (`<role> may not write <path>; only the
  runner writes it`), and a step's Bash change there is quarantined.
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
  `describe`, `cat-file`, `merge-base`, `ls-tree`, `rev-list`, `name-rev`,
  `worktree list` and `cherry-pick -n`, so no role can commit, rewrite history
  or push. The subcommand is found past git's global options, so
  `git -C <dir> status` and `--git-dir`/`--work-tree` pass; a `-c`,
  `--config-env`, `--exec-path`, `--output` or `--ext-diff` makes the call
  not read-only (#61). Outside a confined step, a `-C`, `env -C`, `--git-dir`
  or `--work-tree` place must stay in the repo: an absolute place outside it,
  or one with `..`, or one the shell rewrites (starting with `~`, `$` or a
  quote: `-C ~`, `-C "$HOME"`, `-C $PWD`) is refused (`git-outside-workspace`),
  and Bash may not set
  `GIT_EXTERNAL_DIFF` (`git-env`; it is also locked in confined steps). Only the runner pushes, and only sprint branches (see "Sprint
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
- The OS sandbox is the Proxy's read wall (s12, ADR-0079). The Bash text check
  is only an early refusal: it cannot see what the shell expands. On macOS, an
  e2e test runs a table of escape probes through the real settings: `cd ..`,
  `cd` alone, `cd /`, `~`, `$HOME`, `$VAR`, `$(…)`, a wildcard, `--file=/abs/path`
  and a differently cased path. A control run without the sandbox shows each
  probe reads a source file. With the sandbox, every read is refused. The
  platforms these tests run on are listed in
  `tests/e2e/scripted_cli.PROXY_SANDBOX_PLATFORMS`, and s60 adds Linux there.

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
