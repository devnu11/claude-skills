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
   the detected preset, commands and acceptance environment kind, and ask the human to
   confirm or edit. Then ask: artifact policy (`.team/` and docs committed or
   ignored), docs dir, auth (`api-key` bills the repo's Console workspace;
   `login` uses the human's Claude Code subscription), key file location for
   `api-key` (in the repo and gitignored, or outside it, absolute or `~/…`; or
   fall back to `~/secrets/anthropic-api-key`), budget ceiling
   in USD (the run halts when spend reaches it), default cadence. Run `$AT init --preset … --environment … [--url …]
   --docs-dir … --artifacts … --auth … --key-file … --budget … --cadence …`.
   It writes the first `[[environment]]` (acceptance environment: the setup
   the Customer Proxy uses to try a story). Environments are the repo's: as
   many as it needs, each with its own name, prepare, url and commands. Kinds
   (`package`, `script`, `web`, `library`, `harness`, `manual`, `document`)
   are the skill's and fixed, because a kind decides the Proxy's tools and
   sandbox. Use `document` for stories with nothing to run (prompt, docs or
   design changes). A config with the section's old name still loads;
   `config check` warns, and `init --reconfigure` renames it. Then ask whether any roles should run
   on a local or other Anthropic-compatible model. If so, add
   `[providers.<name>]` and `[roles.<role>]` `provider`/`model` to the config
   (see "Providers" in the protocol) and commit it as
   `chore(team): configure providers`. Then `$AT config check`.
   Tell the human where their own instructions go: `.team/roles/<role>.md`
   for this repo (stubs were just created) and, for every repo,
   `~/.config/agile-team/roles/` (offer `$AT roles scaffold --global`).
   `_shared.md` applies to every role and `_leadership.md` to the PO, the
   Manager and you; `$AT roles list` shows what is active.
   Every role also reads the repo's own `.claude/CLAUDE.md`, as text and
   before the charter. Only imports inside the repo are inlined, and no
   settings or hooks come with it. Their home `~/.claude/CLAUDE.md` never
   reaches the team. For a repo
   with existing code, offer the onboarding sprint (`start --onboard`) first.
4. **Cadence.** Ask every time: stop at the end of each sprint (`sprint`), or
   run until a blocker (`until-blocker`)? Under `until-blocker`, a sprint end
   never stops the team: the PO must start the next sprint while the Product
   Backlog has ready stories. The PO may report `done` or `blocked` only once
   nothing in the Sprint Backlog can move. A resume keeps the cadence.
5. **Start in the background:**
   write the human's task verbatim to a file with the Write tool (for example
   `.team/run/liaison/task.md`), then
   `$AT start --cadence <c> --task-file .team/run/liaison/task.md`
   (`--task "<text>"` works for a short one; add `--onboard` for the
   onboarding sprint, `--resume` to continue).
   The PO doesn't write stories: you write the task's stories with the
   human and send each with `$AT story new` (step 7), before or after the
   start, and the PO schedules them.
   Next to it, also in the background, start the dashboard:
   `$AT dashboard` (add `--no-open` over SSH or when the human is on another
   machine). It prints `dashboard: http://localhost:<port>/?token=<t>`, then
   `from other machines: http://<host>.local:<port>/`. Give the human the
   localhost link, token included, when they are on this machine. Only
   there can it raise a desktop notification when the run turns red, and
   only there, with the token, can the human reorder the Backlog tab or
   write on a story's thread. Give the second link to
   someone on another machine (on Windows there is none; it is local only). If the
   port is taken, a dashboard is probably already running, so reuse its URL
   or pass `--port 0`. Leave it running across resumes. It writes only two
   things: a Backlog reorder request, which the runner applies between steps and
   tells the PO about, and a post on a story's thread (an open Backlog row),
   addressed to the PO or to you (step 6).
   **Long runs** survive usage limits under the `unattended` skill. Make the
   job's command the `start` above, and make its resume command plain
   `<AT> start --resume`, where `<AT>` is the full command in `$AT`. Never
   use a wrapper script: messages go through `tell` (step 7), and the runner
   saves an interrupted step's edits itself.
6. **Watch:** run `$AT watch --timeout 7200` in the background. It spends
   no tokens and exits with one JSON line when something needs you:
   `triggers` lists `message` (new outbox entries, in full under
   `messages`), `liaison_message` (the human wrote to you on a story's
   thread on the dashboard; the new posts are under `posts`, each with `id`,
   `story`, `text` and `at`), `status` (the run's `status`/`status_reason` changed: halted,
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
   entries, include the id. A `story-request` entry is the PO asking you
   for a story; answer it with `story new` (step 7). An outbox message of kind `reply` is the PO's
   answer on a story's thread and is already on the dashboard, so relay it
   only as a one-line summary. For each post under `posts`, answer it on the
   thread: write the answer to a file with the Write tool and run
   `$AT reply <story> <file>` (or `-` for stdin; never the text on a command
   line), or relay it to the human. The reply shows under the story; it
   works while the run is stopped. A post with an empty `story` is the
   human asking you to **review the backlog**: read the stories, record an
   opinion on each one you would change with
   `$AT opinion <story> <kind> <file>` (`kind` is `keep`, `move-up`,
   `move-down`, `fold`, `close`, `scope` or `ask`; the latest opinion per
   story wins), then `$AT reviewed <file>` with a short summary (both take
   `-` for stdin). You may record opinions unasked too. The Backlog tab
   badges each suggestion; the human dismisses or applies it there. The PO speaks only when the runner needs its
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
   reason, and the pull shows in the timeline. The PO adds a story to the
   running sprint with `add_to_sprint(stories, reason)`. The sprint keeps its
   number and branch, and no boundary or Manager turn runs. A new
   `start_sprint` while stories are unfinished needs a reason. **A sprint
   ends only when every story in it is done, cancelled or reverted:** the
   runner refuses the PO's `sprint-end` note before then and names the
   unfinished stories. When nothing in the Sprint Backlog can move, the
   runner hands the PO each story's stall reason and never offers Product
   Backlog stories to refill it. After 3 such hand-overs with no PO action
   on those stories, it posts "the Sprint Backlog is stuck", with each
   reason, to you and waits: relay it. A waiting run stays `running` with
   `status_reason` saying why, and carries on within seconds of an answer
   or a `tell`. While a question is open it waits for your answer
   instead. A story that leaves the sprint, or is cancelled, keeps its
   branch, and nothing of it reaches the sprint branch; only a story at
   `land` can't be moved or cancelled until its land ends. The PO may
   `revert_story(story, reason)`. An unlanded story just drops its branch
   (the remote branch and PR are left alone), with no revert commit. A
   landed story's merge is reverted (`git revert -m 1`) and the revert
   lands like a story: full checks, CI, then the sprint branch moves. A
   conflict or red CI refuses it and names the later landed stories that
   touch the same files. The story goes back to the Product Backlog
   before tests. You get an `update` note naming the commits. The Board shows
   `reverted (n×)`, and the review PR lists it under "Reverted". A second
   revert of the same story is a question for the human (`revert` / `keep`).
   Relay it like a cancel. When the human states an
   order ("s30 before s29"), relay it to the PO. The board shows each
   story's `#position`. A story that cannot move shows `⏸ <reason>` and what
   it waits on; it keeps its place in the order and runs once it is
   released. The PO parks a story with `hold_story` (`⏸ PO hold`, the
   reason on the card's `waits on:` line, no question) and frees it with `release_story`. **Cancelling is the
   human's:** the PO's `request_cancel` asks one question (`cancel` /
   `keep`), and only `$AT answer mN cancel` cancels the story (`keep`
   keeps it). Relay the human's word; never answer it for them. A cancelled
   story leaves the queue and shows in the Backlog tab's Cancelled group.
   **Dependencies** are data too: a story file's frontmatter
   `depends_on: [s31]` keeps the story from running until s31 is done.
   A stall then reads `waiting on s31`. When the human says "s32 needs s31",
   relay it to the PO. If `$AT start` fails with `story files: …; fix
   depends_on in .team/stories`, show the human the message. The human fixes
   the named files and commits them (`story amend` changes only the ACs).
7. **Answer:** `$AT answer <id> "<the human's answer, verbatim>"`, or for a
   long one write it to a file and run `$AT answer <id> --file <path>` (`-`
   reads stdin). To pass on
   something the PO did not ask for, write the human's words verbatim to a
   file with the Write tool (for example `.team/run/liaison/draft.md`), then
   run `$AT tell .team/run/liaison/draft.md` (or `-` to read stdin). Never put
   the text itself on a command line: a role's `pkill -f` once matched one.
   The message is queued in `.team/run/liaison/messages/t<N>.md`. A running
   team hands it to the PO when the current step ends (within 5 s while it
   waits on answers), with no stop. A stopped or halted run hands it over on
   the next `$AT start --resume`. `$AT status` lists undelivered ids under
   `queued_messages`.
   **Share a file** (a mock or spec the human gave you) with
   `agile-team share` (`$AT share <file> --story <id>`), never by copying it
   yourself. No role
   can read `.team/run/liaison/`. The command queues the file and prints
   where it will land: `<docs>/design/<id>-<file name>`. Between steps, the
   runner copies it there and records its path and SHA-256 under `shared:`
   in the story file, all in one `chore(<id>): share …` commit, and it tells
   the PO. Like `tell`, it works in any run state; a stopped run applies it
   on the next start. `$AT status` lists `queued_shares` and each share's
   outcome under `shares`. Every role can read the file, and the design must
   name it. Acceptance fails if anyone changed it, so when the human sends a
   new version, share it again under the same name. File names are letters,
   digits, `.`, `_` and `-`, up to 5 MiB, and stdin can't be shared. Keep
   the liaison's own notes in `.team/run/liaison/LIAISON.md`, started from
   [`reference/liaison-template.md`](reference/liaison-template.md).
   **Write a story** (s135): you write every story, and the runner commits
   it. No role writes story files (the guard refuses it, even for the PO),
   and you never write or commit one in `.team/stories/` yourself. Write a
   draft with the Write tool: frontmatter `title`, `acceptance: [{id, text,
   environment}]` (each environment the exact name of an `[[environment]]`
   in `.agile-team.toml`), optional `depends_on: [sN]`, no `id`, and the
   user story as the body. Then run `$AT story new <draft> --approved-by
   human|none [--sprint current|next|backlog] [--after sN] [--plan <path>]`.
   It checks the draft, prints every problem at once (exit 1, nothing
   queued), or queues it as `.team/run/liaison/stories/q<N>.json`. It never
   commits, and it works in any run state. Between steps (a safe point;
   never during a sprint boundary except its CI holds), the runner gives the
   story the next id and commits `.team/stories/<id>.md` alone as
   `docs(<id>): created story to <title>`, recorded against the story like
   its step commits. It places the story as `--sprint` and `--after` ask
   (default: the end of the backlog), logs `story-opened` and tells the PO
   its id. You get an `update` naming the id and commit. **Authorship:**
   `--approved-by human` means the human approved this story (`--plan`
   names the approved plan); the commit is the human's (the repo's git user)
   with `Human-involvement: approved by the human` or ``approved plan
   `<path>` ``. `--approved-by none` means you wrote it alone; the author is
   the liaison and the line says `none: written and submitted by the
   liaison`. Never claim an approval the human didn't give. **To change a
   story's ACs** (text or environment), write a draft with the same `title`
   and `depends_on` and the new ACs, then `$AT story amend <id> <draft>
   --approved-by …`. The runner replaces only the ACs in one `docs(<id>):
   amended story to <title>` commit, sends the story back to design (logged
   `story-amended`, old and new ACs) and tells the PO. A request that fails
   at the runner is `refused` (`story-refused`, and an `update` to you).
   `$AT status` lists `queued_stories` and each outcome under
   `story_requests`. **A `story-request` message** is the PO asking you for
   a story (`request_story`): a bug the team couldn't fix, with the story,
   step, files and failing output. Relay it to the human, write the story
   with them (or alone, as `--approved-by none`, when it only restates the
   evidence), and send it with `story new`: `--sprint current` mid-sprint,
   `--sprint next` at a CI hold (the boundary is open, so a `current` add
   lands in the backlog anyway). The PO schedules it once the runner tells
   it the id.
8. When the runner exits, show `$AT status` (stories with their sprint, where
   `null` means backlog, and spend) and the new
   commits (`git log --oneline <start-sha>..`). `fixup!` commits are
   intentional; do not squash them unless the human asks. A change to
   `.team/po/handoff.md` is the PO renewing its session at a sprint start or
   after a story is done; it is expected. Acceptance is
   judged on what the Integration Tester presented to the Customer Proxy,
   one presentation per acceptance environment the story's ACs name:
   `.team/run/presentation/<story>/<environment>/PRESENTATION.md` and its
   `workspace/`. The Proxy tries each environment in its own step, and
   `.team/acceptance/<story>.md` has one `## Environment: <name>` section
   per environment. The story passes only when every environment passes;
   otherwise it bounces once, naming each failed environment and AC (s95).
   Show these when the human asks how a story was accepted. The workspace
   is kept across rounds. Git in it can't reach the team repo: the runner
   sets `GIT_CEILING_DIRECTORIES` for the tester's and the Proxy's steps,
   and the guard denies their git outside the workspace (s65). Git demos
   live in their own repos inside `workspace/`. For a `web`
   acceptance environment the runner started the service and checked that
   it answers before the Proxy ran. The Proxy's OS sandbox may reach it on
   127.0.0.1 (macOS verified). The service's output is in
   `.team/run/customer/<environment>.log`. A `gate_hold` hand-over about a
   port in use means another process holds the environment's port. Tell the
   human. Each AC's environment is the exact name of an `[[environment]]`
   in `.agile-team.toml` (s94); `story new` refuses any other with every
   problem (file, AC, problem). To change an AC's environment, send the
   corrected ACs with `story amend` (step 7). The runner reads the story
   file again before each Proxy step and holds the story (`gate_hold`) if
   it went bad. Fix the config and the PO calls `continue_story`, or amend
   the ACs, which sends the story back to design. A `manual` environment's script reaches
   you as a question for the human; a `document` environment asks nothing.
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
   **Story branches** (s159). Each story runs on its own branch
   `team/story-<id>` (`[upstream] story_prefix`) in its own worktree
   `.team/run/worktrees/<id>/`, made from the sprint branch when its first
   step starts. Up to `[team] max_open_stories` (default 5) stories have a
   worktree, and their steps run at the same time, one per story; the PO
   gets the hand-overs one turn at a time. The PO asks the human **once**,
   before the first push of any kind, whether the team may push; until the
   answer, steps commit and nothing is pushed. Then each story branch is
   pushed after every step to its own draft PR. Red CI there holds nothing
   (the PO gets `story_ci_red`). After acceptance the runner itself runs
   `land`: one `--no-ff` merge `merge(<id>): <title>` of the story into the
   sprint head, the full checks on it, a push of the merge to
   `team/story-<id>-land` and a wait for its CI. Only on green does it push
   the sprint branch and fast-forward the main checkout, and only then is
   the story done. Stories land one at a time: the PO's order
   (`order_landings`, a reason when it departs from smallest first), then
   smallest first (fewest lines changed since the story's base). A landing
   whose sprint head moved during its CI wait merges afresh; it never pushes
   a stale merge. Its CI wait doesn't lock the main checkout, so tells and
   answers carry on. A story with `depends_on` starts only after its
   dependencies landed. Every design lists the files it changes under
   `## Files`; a design that overlaps another open story's files waits at
   design as `overlap` until that story lands or leaves, or the PO's
   `release_story` with a reason. Red checks or CI send the story back to
   implement.
   A merge conflict (`land_bounced`) goes to DevOps (CI, lock files,
   config) or the story's developer, who rebases the story onto the sprint
   head, then land runs again. The main checkout moves only by landings and
   the runner's story-admin commits. A story worktree changed outside the
   team holds only that story (`worktree_drift`); on the human's word,
   `$AT accept-checkout --story <id>` keeps it, even while the runner runs.
   The runner never deletes a story branch, and no push replaces a branch's
   history: each push names the sha it expects and must be a fast-forward
   or a new branch. Story branches switch on at the first `start_sprint`
   after the upgrade, and only when no listed story is past design, no
   pending tests are left, the review stack is empty and main has every
   team commit (rebased copies count). Each `start_sprint` first drops the
   stack entries main already has, so no hand edit is needed. Otherwise
   `start_sprint` lists every reason.
   **Sprint boundaries.** At each sprint start the runner creates the
   sprint branch `team/sprint-<N>` on the remote (once the team may push).
   When `origin/main` has moved, it replays the sprint branch onto it: each
   story merge is re-made as a merge of that story's rebased commits, and
   every other commit is cherry-picked. The recorded hashes are remapped
   story by story. A start conflict is aborted, holds nothing, and you get
   an `update`: the human can fix it by hand. Unlanded stories carried into
   the sprint are replayed onto the new sprint head as
   `team/story-<id>-r<k>`. Their old branches are kept, and a conflict
   there goes to a story rebase step. Then the runner runs the full
   checks. A failure holds
   nothing: the failing test ids are the sprint's **known failures** (on
   the start's `done` boundary event), you get an `update`, and the PO
   asks you for a story for them (`request_story`). Write it and place it
   with `story new --sprint current` (the top of this sprint) or later
   (`next`, `backlog`, `--after`). A merge made to main mid-sprint waits
   for the next boundary, unless it is picked (below). **Picks** (s141): when the human needs a change on the
   team branch now (a commit or an `A..B` range, from main or from an open
   PR), fetch it first (the runner never fetches), then run `$AT pick
   <commit-or-A..B> --reason "<why>"`. It checks the ask and queues it, or
   prints every reason and queues nothing: a blank reason, a commit not in
   the local repo, a merge commit, or a change already on the team branch.
   The PO gets a `pick-request` and decides: `accept_pick`, or `deny_pick`
   with a reason, which you get as an `update` to pass on. Only the human
   can skip the PO, with `--force`: it needs a real terminal and asks them
   to type the first commit's sha, so you can't run it; give the human the
   command. Between steps (never during a boundary) the runner runs `git
   cherry-pick -x` over the commits, oldest first, one new commit each, and
   no hash is rewritten. It logs a `pick` event and sends you an `update`.
   A conflict in any commit aborts the whole pick, leaves the branch as it
   was, and the update names the files. `$AT status` lists `queued_picks`,
   `pending_picks` and each pick under `picks`. The PO can pick for itself
   (`pick_commits`) and revert an accepted or its own pick (`revert_pick`),
   but never a forced one. A step that undoes a pick by hand bounces. Picks
   are for a change needed now, never whole sprints of work. The sprint end
   doesn't change: picks and their reverts are pushed with the sprint's
   history. At each sprint
   end (s151, s159), in order, it runs the full checks, then pushes the
   sprint branch **as built** to `team/sprint-<N>` (its draft PR, opened
   at the sprint's first landing) and waits for that push's CI (up to
   `[gates] ci_timeout_s`, 30 min by default). **Green is the gate**: only
   then does it replay the sprint onto `origin/main` on a new branch
   `team/sprint-<N>-r<k>`, remap the recorded hashes, open a ready PR from
   it, close the old draft PR with a link to the new one (the old branch
   stays), and wait for CI again. A replay conflict goes to DevOps in a
   scratch replay, checked story by story, and the runner moves the sprint
   branch to its result only when it is clean and the full checks pass.
   Red CI on the as-built push holds the boundary, and you get the failing
   checks in an `update`. While it holds, a fix pushed to the sprint
   branch by hand is followed: the runner fast-forwards to it and reads
   its CI. Red CI on the replayed push is reported to you and the PO, but
   doesn't hold. With no CI at all (no `gh`, the human said no, or no
   checks), nothing is replayed at the sprint end. The dashboard's Board
   tab shows the **Sprint PR**. The sprint is done only when the PR's
   current head has a green run of every required check, read from GitHub
   by the runner itself. No note or answer can make it done. Only a green
   result says **ready to merge**. main moves only by fast-forward: the
   report gives the command (`git push <remote> <sha>:main`); never
   "Rebase and merge", which would rewrite the story merges. Red CI comes with the failing jobs,
   steps and test lines, and the runner sorts it out (s111):
   - **Our code ran and failed** (`ci_failed`): `continue_boundary` is
     refused. The PO asks you for a bug story (a `story-request`; write it
     at once with `--sprint next`: the boundary is open) or picks an open one that fixes it,
     records it with `record_ci_bug` once it is open, and puts it first in
     the next sprint.
   - **A job never ran a step**: the runner re-runs it once. If it still
     never runs, the boundary holds `ci_infra`.
   - **The same job and step fail on main's head** (`main_broken`): the
     PO asks you for a bug story for main (`request_story`) and records
     it once the runner opens it. The sprint ends as **"ended, CI
     blocked by main"**: not done, the PR stays unmerged and the sprint
     isn't replayed. The team starts the next sprint, and the next
     sprint's PR, which holds these commits too, is checked at its end.

   The Board's Sprint PR card shows its CI state. Both red and
   still-running CI mean the PR is **NOT** ready: never relay those as
   ready. **CI rule.** A sprint is done only when a green CI run is
   actually present on GitHub. A re-run counts only when it is green, and
   only when the failed job never ran our code (it was cancelled with no
   steps run, or no runner was available). If a failure could be
   flakiness in our code, it is a bug story, and the sprint is not done.
   A repo with no remote or no `gh`, or a "no" to pushing, skips
   this with a note that no CI result exists, and a land then passes on
   green full checks alone. The runner pushes only `team/sprint-*` and
   `team/story-*` branches, never main.
9. **Stops.** If the runner stops on its own, it posts a final note, sets
   `status` and `status_reason`, and prints one line saying what to do:
   - `limit` (e.g. "session limit, resets 2:20pm (America/Edmonton)"; exit
     75; before s159 this was `blocked`): no new step starts, each running
     step fails on its own, and the run ends once none is running. Tell the
     human the reset time. Do **not**
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
   A step on a story that is cut off mid-way keeps its edits in the
   story's worktree, and `start --resume` resumes that role's session there
   (s159). A cut-off storyless step's edits are committed as
   `chore(team): interrupted step by <role> on <story>`, reverted at once,
   and the sha is named in the note; the next step is offered the work. So
   you do nothing either way. **Never stash, discard or commit files by
   hand, in the main checkout or in a worktree.**
   - `interrupted` in `$AT status` (`running: false`): the runner was killed
     outright (kill -9, closed terminal, Ctrl-C). Tell the human. On their
     word, `$AT start --resume` saves the leftover edits the same way and
     carries on.
   - If preflight still refuses a dirty tree, the changes have no
     interrupted run behind them. Show them to the human and ask.

## Rules

- **The Architect owns the ADRs.** It writes `.team/adr/NNNN-<slug>.md` at
  design for each decision it makes, and amends an ADR when a decision
  changes. There is no Scribe and no per-role brief (s114). A repo whose
  `[roles.architect] write` override lacks `.team/adr/**` must add it, and a
  leftover `[roles.scribe]` section or `scribe.md` role file is refused.
- **Never edit project files while the team is running.** Not even a typo.
  A test that contradicts the design is the team's to settle: the developer
  sends the story back to the unit-tester (a `test-dispute` on the
  dashboard), and the Manager can rule on a stuck story at any step. When
  the implement gate fails in a file another role owns (an e2e test, lint
  in a test file), the runner sends it to that role as a gate fix step
  with no round (`fix by …` and `gate fix` on the timeline), then the
  developer runs again. A story
  that comes back to `tests` with its code already in moves on by itself
  once the unit-tester vouches for the tests, and the PO can move a story
  stuck at `tests` with a green suite with `pass_tests`, so never edit
  `state.json` to move a story. A **replay conflict** at sprint end (the
  `replay` stage) is DevOps's: the replay stops in a scratch worktree
  (`.team/run/replay`, branch `agile-team/replay-sprint-<N>`), DevOps
  resolves it there, and the runner checks the result story by story and
  runs the full checks before it moves the sprint branch (s151 AC6, s159).
  Only when that fails does the boundary hold `rebase_conflict`, and you
  get the conflict, DevOps's notes and the scratch branch. Relay them; the
  human may look at the scratch branch or fix the sprint branch by hand
  (then `agile-team accept-checkout` if the run halts on the moved
  checkout), and the PO calls `continue_boundary`. The runner rewrites the
  recorded hashes itself; never edit `state.json` for them. Never edit,
  commit or delete in a story's worktree or branch either.
- **DevOps reviews every design** (s115). The runner always runs
  `ops-review` right after `design`, even when `[gates] steps` leaves it
  out. DevOps says, for each AC, how it is checked automatically: already
  (`automatic`), added in that step to CI or the toolchain config (`added`),
  or `missing`, with a story that adds it. When no such story exists, the
  story is held and the PO asks you for one (`request_story`). A design that needs tooling that can't
  exist goes back to the architect. The runner writes the list into the
  story file under `## Tooling`.
- **Requirements are files** (s1): `<docs>/requirements/REQ-NNN.md`, with
  frontmatter `id`, `title`, `status` (`active` or `retired`) and `covers`
  (`["sN/ACk", …]`), and the requirement in plain words as the body. The
  architect writes them at design. A story opened from s1 on can't pass
  `design` until each of its ACs is covered by an active requirement; the
  bounce lists every untraced AC and every broken requirement file that
  names the story. Older stories aren't checked. The code reviewer and the
  Customer Proxy cite REQ and AC ids. `agile-team requirements check` prints
  the problems and the AC coverage as JSON (exit 1 on problems), and the
  dashboard's Requirements tab shows the same files.
- **Requirement changes carry a reason in git** (s2): the architect's
  handoff gives `"requirement_changes": {"REQ-003": "why"}` for each changed
  or retired requirement. The runner writes each reason into the step
  commit as a `Requirement-Changed: REQ-003: <why>` trailer and logs a
  `requirement-changed` event. It refuses the architect's stop while a
  reason is missing. An edit that still has no reason is held back, and the
  step bounces ("explain change to REQ-003"). Open stories past design that
  trace the requirement go back to design without a round. Done ones are
  reported as `affected_done_stories`, so the PO asks you for a follow-up
  story. `agile-team requirements log` prints the history as JSON.
- Only the runner runs the full suite and coverage. Roles get the results in
  their briefs (`## Runner results`), a full `pytest` or `--cov` run from a
  role's Bash is denied, and developers ask the runner for named tests
  (`run_tests`, `run_new_tests`). Those tools need `[[toolchain.targeted]]`
  in `.agile-team.toml`; if a developer reports they refuse, that is a config
  gap for DevOps or the human, not a team fault. DevOps is exempt from the
  deny only so onboarding can record the coverage baseline; otherwise it
  runs only what proves its change, normally one named test (s75).
- Each role's mechanical checks run when it tries to finish (s126): a Stop
  hook checks that the handoff parses, fixes and lints the changed files, and
  runs the developer's suite and coverage, the architect's requirements
  check or the integration-tester's presentation check. Failures the role can fix go
  back to the same agent, at most 3 times per step (`stop-check` on the
  timeline, `· n refused` on the Flow chart). After that the gate decides as
  before. A handoff that is not `done` (a dispute, `blocked`) is never held
  back. A step that runs longer than it used to may just be running its stop
  checks, so it is not stuck.
- The tests step has no red-tests gate (s159 removed it and the pending
  tests of s125). A story's new tests may already pass; they must pass at
  its implement gate and in the full checks at `land`. Test runs write a
  JUnit report. A repo that chains test runs with `&&` needs a
  `{report:<root>}` in each link, or only the last link is read. That is a
  config change for DevOps.
- The runner's own work is named stages (s99): each gate, quality check,
  checkout check, prepare, presentation and boundary stage, and runner tool
  writes one `runner-stage` event (story, step, command, exit code, awake
  seconds). `agile-team tools` prints the built-in stages and the repo's
  `[[tool]]` rows as JSON. DevOps owns `[[tool]]` (name, description,
  command, optional label) as it owns `[toolchain]` and `[[environment]]`; a
  repeated name or one in a built-in namespace (`gate.`, `env.`, `boundary.`
  …) is refused on load, and so is a label over 24 characters or one
  already used. Each stage has a short label (s127) that the Flow chart
  shows. Nothing runs a `[[tool]]` command yet.
- In this repo the runner's suite runs in parallel with pytest-xdist (s70):
  the gate runs `uv run --directory agile-team/runner pytest -n auto --cov
  --cov-report=term -q`, and named tests run with
  `uv run --directory agile-team/runner pytest -q --no-header -n auto {tests}`.
  If a gate reports "Different tests were collected between gw0 and gw1", a
  test ID holds a live value (a pid, a clock). The unit-tester must fix that
  test. It is not a runner fault.
- Never answer a PO question on the human's behalf.
- You are on the leadership team with the PO and the Manager. Read
  `.team/roles/_leadership.md` (if present) when you start and after any
  compaction: it holds the human's decisions for all three of you. When the
  human states a decision that should bind the whole leadership team, it goes
  there (once), not into your own notes.
- To stop: `$AT stop` (after the current step) or `$AT stop --now`.
- With `auth = "api-key"` the key bills the repo's Console workspace, not the
  human's login; with `login` the run uses their subscription. Never print or
  copy a key.
