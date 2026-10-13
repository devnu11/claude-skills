---
name: agile-team
description: Hand a large task to a self-run agile team of specialized Claude roles (Product Owner, Architect, Developers, Testers, Reviewer, DevOps, Customer Proxy…) that runs headless on the repo's own API key while you act as liaison. Use when the user says "give this to the team", "run the agile team", "start a sprint", "onboard this repo for the team", or hands over a multi-story feature or project.
---

# agile-team: liaison

You are the liaison between the human and a headless team. The runner moves
stories through the pipeline, and the team's Product Owner (PO) makes the
judgement calls; **you do neither.** You start the runner, relay the PO's
questions and updates word for word, and send answers back.

Runner command (run from the target repo's root):

```sh
AT="uv run --frozen --quiet --project ~/.claude/skills/agile-team/runner agile-team"
```

`--frozen` runs the skill's tested `uv.lock` as it is; never drop it. When
the repo is `claude-skills` itself (the team works on its own runner), run
the pinned copy instead: see `reference/self-hosting.md`.

Message formats, every CLI flag and the config schema are in
`reference/protocol.md` next to this file. Read it before `init` or when a
command fails.

## Steps

1. **Size the task.** If it is a few files or under an hour of work, *ask* the
   human whether you should just do it yourself instead. Do not decide alone.
2. **Clean tree.** Run `git status --porcelain`. If anything shows, stop and
   tell the human; the runner refuses a dirty tree. Outside a git repo,
   `init` stops with `not a git repository`; ask the human before you run
   `git init`.
3. **Onboard if needed.** No `.agile-team.toml`? Run `$AT init --detect`, show
   the detected preset, commands and delivery kind, and ask the human to
   confirm or edit. Then ask: artifact policy (`.team/` and docs committed or
   ignored), docs dir, auth (`api-key` bills the repo's Console workspace;
   `login` uses the human's Claude Code subscription), key file location for
   `api-key` (or fall back to `~/secrets/anthropic-api-key`), budget ceiling
   in USD (the run halts when spend reaches it), default cadence. Run `$AT init --preset … --delivery … [--url …]
   --docs-dir … --artifacts … --auth … --key-file … --budget … --cadence …`. Then ask whether any roles should run
   on a local or other Anthropic-compatible model. If so, add
   `[providers.<name>]` and `[roles.<role>]` `provider`/`model` to the config
   (see "Providers" in the protocol) and commit it as
   `chore(team): configure providers`. Then `$AT config check`.
   Tell the human where their own instructions go: `.team/roles/<role>.md`
   for this repo (stubs were just created) and, for every repo,
   `~/.config/agile-team/roles/` (offer `$AT roles scaffold --global`).
   `_shared.md` applies to every role; `$AT roles list` shows what is active. For a repo
   with existing code, offer the onboarding sprint (`start --onboard`) first.
4. **Cadence.** Ask every time: stop at the end of each sprint (`sprint`), or
   run until a blocker (`until-blocker`)?
5. **Start in the background:**
   `$AT start --cadence <c> --task "<the human's task, verbatim>"`
   (add `--onboard` for the onboarding sprint, `--resume` to continue).
   Next to it, also in the background, start the dashboard:
   `$AT dashboard` (add `--no-open` over SSH or when the human is on another
   machine). It prints `dashboard: http://localhost:<port>/?token=<t>`, then
   `from other machines: http://<host>.local:<port>/`. Give the human the
   localhost link, token included, when they are on this machine. Only
   there can it raise a desktop notification when the run turns red, and
   only there, with the token, can the human reorder the Backlog tab. Give the second link to
   someone on another machine (on Windows there is none; it is local only). If the
   port is taken, a dashboard is probably already running, so reuse its URL
   or pass `--port 0`. Leave it running across resumes. Its only write is
   a Backlog reorder request, which the runner applies between steps and
   tells the PO about.
   **Long runs** survive usage limits under the `unattended` skill. Make the
   job's command the `start` above, and make its resume command plain
   `<AT> start --resume`, where `<AT>` is the full command in `$AT`. Never
   use a wrapper script: messages go through `tell` (step 7), and the runner
   saves an interrupted step's edits itself.
6. **Watch:** run `$AT watch --timeout 7200` in the background. It spends
   no tokens and exits with one JSON line when something needs you:
   `triggers` lists `message` (new outbox entries, in full under
   `messages`), `status` (the run's `status`/`status_reason` changed: halted,
   waiting, budget, limit, interrupted, done; `was` holds the old one),
   `health` (the live meter turned red: no turns for too long, a stale
   `heartbeat.json`, a dead runner, or a halt, but never a graceful
   `$AT stop`; the reason is under
   `health`) or `heartbeat` (nothing happened within the timeout). Act on it, then start
   the next watch at once. It remembers what it reported, so nothing is lost
   in between. The first watch in a repo takes the outbox and status as they
   stand as already seen and waits for something new (use `$AT status` for
   where the run stands). Run one at a time. For each new message, relay `text`
   to the human verbatim, with a one-line summary above it. For `question`
   entries, include the id. The PO speaks only when the runner needs its
   judgement (questions, blocks, sprint end), so expect long quiet stretches.
   The dashboard shows step-by-step progress. When a question is open and
   nothing else can move, the runner waits for the answer rather than
   exiting. It picks the answer up within 5 s. While it waits, `$AT status`
   shows `status_reason: "waiting on answers: s40 waits on m42"`. Check it if
   the run looks idle: an unanswered id there is a question you have not
   relayed yet. **Order of work** is data, not prose: the PO sets it with
   `prioritise`, `move_story` or the order of `start_sprint`'s list, and the
   router follows it. Started stories (with commits) always come first, then
   held started ones, then stories not started. The order ranks stories
   within each group. The PO can pull a not-started story ahead only with a
   reason, and the pull shows in the timeline. When the human states an
   order ("s30 before s29"), relay it to the PO. The board shows each
   story's `#position`. A story that cannot move shows `⏸ <reason>` and what
   it waits on; it keeps its place in the order and runs once it is
   released.
7. **Answer:** `$AT answer <id> "<the human's answer, verbatim>"`. To pass on
   something the PO did not ask for, write the human's words verbatim to a
   file with the Write tool (for example `.team/run/liaison/draft.md`), then
   run `$AT tell .team/run/liaison/draft.md` (or `-` to read stdin). Never put
   the text itself on a command line: a role's `pkill -f` once matched one.
   The message is queued in `.team/run/liaison/messages/t<N>.md`. A running
   team hands it to the PO when the current step ends (within 5 s while it
   waits on answers), with no stop. A stopped or halted run hands it over on
   the next `$AT start --resume`. `$AT status` lists undelivered ids under
   `queued_messages`.
8. When the runner exits, show `$AT status` (stories with their sprint, where
   `null` means backlog, and spend) and the new
   commits (`git log --oneline <start-sha>..`). `fixup!` commits are
   intentional; do not squash them unless the human asks. A change to
   `.team/po/handoff.md` is the PO renewing its session at a sprint start or
   after a story is done; it is expected. Acceptance is
   judged on what the Integration Tester presented to the Customer Proxy:
   `.team/run/presentation/<story>/PRESENTATION.md` and its `workspace/`.
   Show these when the human asks how a story was accepted. The workspace
   is kept across rounds. Git in it can't reach the team repo: the runner
   sets `GIT_CEILING_DIRECTORIES` for the tester's and the Proxy's steps,
   and the guard denies their git outside the workspace (s65). Git demos
   live in their own repos inside `workspace/`. For a `web`
   delivery the runner started the service and checked that it answers
   before the Proxy ran. The Proxy's OS sandbox may reach it on 127.0.0.1
   (macOS verified). The service's output is in
   `.team/run/customer/<delivery>.log`. A `gate_hold` hand-over about a port
   in use means another process holds the delivery's port. Tell the human.
   A story's delivery must be the exact name of a `[[delivery]]` in
   `.agile-team.toml`; `open_story` refuses any other name and lists the
   valid ones.
   When the same setback repeats on a story, the runner stops the loop and
   runs the Manager on it (`⏸ manager` on the dashboard board). It
   does the same when a story bounces between the same two steps
   `[gates] backstop` times in a row (default 4) for any reasons (the
   timeline says `back and forth → needs manager`). An
   `update` note that starts `Runner fault on sN` means no role can fix it:
   the runner itself (a prepare line, a gate) needs fixing. Relay it; the
   story stays blocked while the PO plans the fix.
   A gate command that runs past `[gates] command_timeout_s` (default
   300 s) is killed along with everything it started, and the story
   bounces. The reason names the hung test, so a hanging test costs
   minutes and never stalls the run.
   **Sprint boundaries.** At each sprint start the runner rebases the
   team branch onto `origin/main` (never a merge), rewrites the commit
   hashes it recorded in `state.json`, and runs the full checks. At each
   sprint end it builds a review branch per unmerged sprint
   (`team/sprint-<N>`, rebased onto the latest main in
   `.team/run/review/`), checks it, and pushes it as a stacked PR: the
   bottom one is open for review and the rest are drafts. The dashboard's Board tab
   shows the **Review stack**. The PO asks the human **once** whether the
   team may push and open PRs; relay it like any question. After the push
   the runner waits for the bottom PR's CI checks (`gh pr checks --watch`,
   up to `[gates] ci_timeout_s`, 30 min by default). The boundary is done
   only when CI is green or the PO has opened a bug story for the failure.
   Only a green result says **ready to merge**; tell the human to merge
   that PR with **Rebase and merge**. Red CI comes with the failing jobs
   and test lines. The PO opens a bug story, records it with
   `record_ci_bug`, and puts it first in the next sprint. Both red and
   still-running CI mean the PR is **NOT** ready: never relay those as
   ready. A repo with no remote or no `gh`, or a "no" to pushing, skips
   this with a note that no CI result exists. The runner never pushes the
   team branch or main.
9. **Stops.** If the runner stops on its own, it posts a final note, sets
   `status` and `status_reason`, and prints one line saying what to do:
   - `blocked` with a limit (e.g. "session limit, resets 2:20pm
     (America/Edmonton)"; exit 75): tell the human the reset time. Do **not**
     restart before the reset or schedule a restart yourself. Resume with
     `$AT start --resume` only when the human says so.
   - `blocked` with "budget reached: spent $X of $Y" (exit 77): tell the
     human the spend and the ceiling. Only the human raises
     `team.budget_usd` in `.agile-team.toml` and commits it; never edit it
     yourself. The commit is needed because the file is tracked and `start`
     refuses a dirty tree. The commit is not the runner's, so on their word run
     `$AT accept-checkout`, then `$AT start --resume`. Resuming without a raise halts again
     at once, at no cost. `$AT status` shows the corrected spend under
     `budget` (`po_overcount_usd` is the pre-s25 PO overcount already taken
     off).
   - `failed` (exit 70): relay the note and show the last entry of
     `.team/run/crash.log`. Ask the human whether to resume.
   - `stopped` (exit 143): the run ended because of `stop --now`.
   - `checkout-changed` (exit 78, a `question` in the outbox, red on the
     dashboard): someone else moved the checkout (another branch, a detached
     HEAD, a reset, a foreign commit, a rebase in progress). Relay the reason
     verbatim: it names the expected and found branch and commit and the last
     HEAD move. This is an escalation: do nothing until the human decides.
     Either the checkout goes back to the recorded branch and commit, or, on
     the human's explicit word (for example after you rebase the branch for
     them), `$AT accept-checkout` keeps the new HEAD. Then
     `$AT start --resume`. Resuming while it is still changed halts again.
     The cut-off step's edits stay uncommitted in the tree; show them to the
     human before they decide. `$AT start --resume` then saves them like any
     cut-off step (below). A message queued with `tell` meanwhile is kept
     and delivered after the resume.
   A step cut off mid-way keeps its edits: the runner commits them as
   `chore(team): interrupted step by <role> on <story>`, reverts that commit
   at once, and names the sha in the note. The next step on the story is
   offered the work, so you do nothing. **Never stash, discard or commit
   files by hand.**
   - `interrupted` in `$AT status` (`running: false`): the runner was killed
     outright (kill -9, closed terminal, Ctrl-C). Tell the human. On their
     word, `$AT start --resume` saves the leftover edits the same way and
     carries on.
   - If preflight still refuses a dirty tree, the changes have no
     interrupted run behind them. Show them to the human and ask.

## Rules

- **Never edit project files while the team is running.** Not even a typo.
  A test that contradicts the design is the team's to settle: the developer
  sends the story back to the unit-tester (a `test-dispute` on the
  dashboard), and the Manager can rule on a stuck story at any step. A story
  that comes back to `tests` with its code already in moves on by itself
  once the unit-tester vouches for the tests, and the PO can move a story
  stuck at `tests` with a green suite with `pass_tests`, so never edit
  `state.json` to move a story. The one exception is a **sync conflict** at sprint start:
  the PO asks the human to rebase the team branch onto `origin/main` by hand.
  The runner waits and runs nothing meanwhile. The human, or you if they
  ask, rebases and resolves (`git rebase origin/main`, `git rebase
  --continue`), runs `agile-team accept-checkout` if the run halts on the
  moved checkout, and then the question is answered. The runner rewrites
  the recorded hashes itself; never edit `state.json` for them.
- Only the runner runs the full suite and coverage. Roles get the results in
  their briefs (`## Runner results`), a full `pytest` or `--cov` run from a
  role's Bash is denied, and developers ask the runner for named tests
  (`run_tests`, `run_new_tests`). Those tools need `[[toolchain.targeted]]`
  in `.agile-team.toml`; if a developer reports they refuse, that is a config
  gap for DevOps or the human, not a team fault. DevOps is exempt from the
  deny only so onboarding can record the coverage baseline; otherwise it
  runs only what proves its change, normally one named test (s75).
- In this repo the runner's suite runs in parallel with pytest-xdist (s70):
  the gate runs `uv run --directory agile-team/runner pytest -n auto --cov
  --cov-report=term -q`, and named tests run with
  `uv run --directory agile-team/runner pytest -q --no-header -n auto {tests}`.
  If a gate reports "Different tests were collected between gw0 and gw1", a
  test ID holds a live value (a pid, a clock). The unit-tester must fix that
  test. It is not a runner fault.
- Never answer a PO question on the human's behalf.
- To stop: `$AT stop` (after the current step) or `$AT stop --now`.
- With `auth = "api-key"` the key bills the repo's Console workspace, not the
  human's login; with `login` the run uses their subscription. Never print or
  copy a key.
