# ADR-0072: Main reaches the team mid-sprint only by single-commit picks

**Date:** 2026-10-15 · **Story:** s141 · **Design:** `agile-team/docs/design/s141.md`

## Context

Since s108 (ADR-0041 amended) the team branch takes main in only at the
sprint-end rebase, and the start sync changes nothing. That keeps hashes
stable within a sprint. However, a fix that lands on main mid-sprint, such as
a test fix or a charter rule, then waits a whole sprint. The human wants that
one commit on the team branch at once, with no merge and no hash rewrite
(t104), asked for by the human or the liaison, or by the PO when the team
finds the need itself.

## Decision

1. **A pick is one `git cherry-pick -x` commit on top of the team branch.**
   It is made by the runner between steps (the router tick, after the
   story intake), never while a boundary is open. No existing hash
   changes. A conflict, an empty result or any git failure is aborted, and
   the branch is reset to where it was.
2. **One validated queue for both askers.** `agile-team pick <commit>
   --reason` and the PO tool `pick_from_main(commit, reason)` run the same
   checks with a fresh fetch, then queue `.team/run/picks/p<N>.json`
   (`NumberedQueue`, ADR-0069) with the full sha and the asker's origin. The
   runner checks again when it applies the pick. The checks refuse: a blank
   reason, no upstream, a value that isn't a commit, a commit not on
   `<remote>/<branch>`, a merge or root commit, and a commit whose patch is
   already on the team branch. The PO can't veto or reorder a pick. No tool
   reads or edits the queue.
3. **The PO is told after, never asked first.** The tick that settles a
   pick returns a `main_pick` hand-over with one line per pick, and the
   liaison gets a note for each. Every outcome is a `main-pick` event and a
   `state.picks` entry.
4. **The sprint end drops the pick.** The END rebase already drops commits
   whose patch is upstream, and drops those that come out empty
   (`--empty=drop`). The review build already leaves out commits whose patch
   is in the target, and skips empty picks. The pick is not a remapped
   field. Tests pin this behaviour, which needs no code.
5. **The pick keeps main's message and author** (plus the `-x` line) and has
   no `Co-Authored-By: Claude` trailer. It is main's commit, not Claude's.
   This is the one exception to the `git_ops` trailer rule. Hooks are off
   for it, as `--no-verify` is for every other runner commit.

## Consequences

- Mid-sprint, picks are the only way main reaches the team branch. The
  start sync still changes nothing.
- A pick lies inside the sprint's commit range, but no story owns it. It
  is no step's diff, and the review branches and the next rebase leave it
  out, so main never gets it twice.
- A pick that conflicts changes nothing. The change then reaches the team at
  the sprint-end rebase.
- The PO's role file states the limit: picks are for a fix or rule that is
  already on main and needed now, never for whole sprints of work.

## Amended by s141 (new ACs, t107, 2026-10-15)

The human replaced the story's ACs before any pick code shipped. Decisions
1 to 4 above are replaced as follows, and decision 5 stands.

1. **The source can be any commit in the local repo**, from main or from an
   open PR, and a pick can be a single commit or a range `A..B`. The runner
   **never fetches**: whoever asks fetches first. The checks refuse a commit
   that isn't local, a merge (or root) commit, and a commit whose patch is
   already on the team branch. They report **every** reason, and nothing is
   queued.
2. **The PO decides, and only the human can force.** `agile-team pick` queues
   a `request`, which reaches the PO as a `pick-request` hand-over. The PO
   answers with `accept_pick` or `deny_pick(reason)`. A denial is a
   `pick-denied` event and a note to the liaison. `agile-team pick --force`
   needs a TTY and the first commit's sha12 typed back. It skips the PO,
   which gets a `pick-forced` hand-over once it is applied. The PO's own
   `pick_commits` needs no accept step. All three go through the one queue
   `.team/run/picks/p<N>.json`, and the decisions live in `state.picks`.
3. **Applying stays between steps**, never during a boundary. It is one
   `cherry-pick -x` over every commit, oldest first, so each source commit
   becomes its own commit and no hash is rewritten. A conflict in any commit
   aborts the whole pick and resets the branch. Each outcome is a `pick`
   event (the `main-pick` event renamed) that records how the pick was
   decided and whether each source commit is on `<remote>/<branch>`.
4. **The sprint end changes nothing for picks.** Picks and their reverts are
   ordinary commits and are pushed with the sprint's history. Git drops one
   whose patch main already has, as it would any commit. The earlier
   "rebase drops the pick" guarantee is withdrawn.
5. **Picks stay applied.** `revert_pick` reverts an accepted pick or the
   PO's own in one revert commit. It refuses a forced pick. The runner keeps
   each applied pick's patch (`.team/run/picks/patches/p<N>.patch`), and
   every story step's gate checks that each pick in force this sprint still
   reverse-applies. A step that undid one bounces back to itself.

Consequences of the amendment:

- A step that has to change lines a pick touched will bounce (P12). The PO
  must `revert_pick` first, and for a forced pick only the human can help.
  Two picks in one sprint that touch the same lines make the older one fail
  the reverse-apply check, so the PO should avoid overlapping picks.
- A pick of a commit that is not yet on main ends up in the sprint's review
  branch, and main gets it through the sprint's PR. If the PR it came from
  merges first, git drops the duplicate at the next rebase.

## Related

- ADR-0041 (rebase at the sprint end; amended by s141).
- ADR-0062 / ADR-0070 (queue-then-apply between steps for shares and stories).
- ADR-0069 (the numbered queue).
