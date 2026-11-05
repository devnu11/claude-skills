# ADR-0094: The END boundary judges the sprint's work head; bookkeeping commits ride to the next sprint

Story: s188. Design: `agile-team/docs/design/s188.md` (W1 to W7).
Extends ADR-0093 (bookkeeping commits stay local) to the sprint end, and
amends ADR-0075 (see its "Amended by s188" section).

## Context

The END boundary compared HEAD with the sprint's pushed sha. The PO's own
storyless step commits `chore(team): product-owner step` (only
`.team/po/handoff.md`) after the boundary's CI stage hands it `ci_green`.
In sprint 53 that commit made `push-replayed` push `-r1`, close the green
PR #74, open #76 and wait for CI again. In sprint 54 the human had already
fast-forwarded main to the green PR #82; the push stage pushed the chore
commit, and every CI read called #82's checks stale, so the boundary held
`ci_pending` until the liaison closed it by hand. `ci_green` also fired at
the CI stage's `pass`, before the boundary had finished, so the PO called
#74 ready before the runner closed it.

## Decision

1. **Bookkeeping is a plain commit that changes only the team dir.** One
   parent, every changed path under `.team/` (or none). A merge, or a commit
   that touches any other path, is work.
2. **The work head.** When HEAD adds only bookkeeping commits to the
   entry's pushed sha, the END boundary works on the pushed sha: the push
   stage pushes it (so nothing), and `push-replayed`'s shipped and
   unchanged checks compare it. Otherwise the work head is HEAD, as before.
3. **Bookkeeping commits stay on the team branch, unpushed.** They are not
   deferred, made elsewhere or rewritten. `last_end` is the work head, so
   they fall in the next sprint's range and reach main with its PR. This is
   ADR-0093's rule ("stay local until the next landing or the sprint end")
   carried through the sprint end.
4. **`ci_green` fires only on the boundary's `done`.** The CI stage's green
   `pass` keeps its `ci` field and raises no hand-over.

## Consequences

- A green sprint PR stays the one the human merges; a bookkeeping commit
  costs no `-r<k>` branch, PR churn or CI run.
- main lags the team branch by the bookkeeping commits until the next
  sprint's PR. A sprint that lands nothing doesn't push them either; they
  wait on the team branch for the first sprint that does.
- The rule keys on paths, not commit subjects, so a storyless step that
  changes code (a DevOps config fix) is still work and still gets CI.
- Deferring the PO's commit during a boundary was rejected for the same
  reasons as in ADR-0093: many writers, and one already running could still
  move the head.
