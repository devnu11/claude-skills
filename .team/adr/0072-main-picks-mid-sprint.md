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

## Related

- ADR-0041 (rebase at the sprint end; amended by s141).
- ADR-0062 / ADR-0070 (queue-then-apply between steps for shares and stories).
- ADR-0069 (the numbered queue).
